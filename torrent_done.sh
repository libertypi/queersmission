#!/usr/bin/env bash

# Bash script for transmission maintenance and torrent management.
# Author: David Pi

################################################################################
#                                 Environment                                  #
################################################################################

die() {
  printf 'Error: %s\n' "$1" 1>&2
  exit 1
}

unset IFS tr_api seed_dir watch_dir GiB quota locations
export LC_ALL=C LANG=C

((BASH_VERSINFO[0] >= 4)) 1>/dev/null 2>&1 || die 'Bash >=4 required.'
hash curl jq || die 'Curl and jq required.'
cd "${BASH_SOURCE[0]%/*}" || die 'Unable to enter script directory.'
. ./config || die "Loading config file failed."

readonly -- \
  logfile="${PWD}/logfile.log" \
  categorizer="${PWD}/component/categorizer.awk" \
  regexfile="${PWD}/component/regex.txt"

################################################################################
#                                  Functions                                   #
################################################################################

print_help() {
  cat <<EOF 1>&2
usage: ${BASH_SOURCE[0]} [OPTION]...

Transmission Maintenance Tool
Author: David Pi

optional arguments:
  -h         show this message and exit
  -d         dryrun mode
  -f NAME    force copy torrent NAME, like "script-torrent-done"
  -q NUM     set disk quota to NUM GiB (default: $((quota / GiB)))
  -s FILE    save formated json to FILE
  -t TEST    unit test, TEST: "all", "tr", "tv", "film" or custom path
EOF
  exit 1
}

# Normalize path, eliminating double slashes, etc.
# Usage: new_path="$(normpath "${old_path}")"
# Translated from Python's posixpath.normpath:
# https://github.com/python/cpython/blob/master/Lib/posixpath.py#L337
normpath() {
  local IFS=/ c s cs=()
  if [[ $1 == /* ]]; then
    s='/'
    [[ $1 == //* && $1 != ///* ]] && s='//'
  fi
  for c in $1; do
    [[ -z ${c} || ${c} == '.' ]] && continue
    if [[ ${c} != '..' || (-z ${s} && ${#cs[@]} -eq 0) || (${#cs[@]} -gt 0 && ${cs[-1]} == '..') ]]; then
      cs+=("${c}")
    elif ((${#cs[@]})); then
      unset 'cs[-1]'
    fi
  done
  c="${s}${cs[*]}"
  printf '%s' "${c:-.}"
}

init() {
  local i
  # verify configurations
  [[ ${seed_dir} == /* && ${locations['default']} == /* && ${tr_api} == http* && ${quota} -ge 0 ]] ||
    die 'Invalid configuration.'
  seed_dir="$(normpath "${seed_dir}")"

  # init variables
  tr_header='' tr_json='' tr_totalsize='' tr_paused='' logs=() dryrun=0 savejson=''
  declare -Ag tr_names=()

  # parse arguments
  while getopts 'hdf:q:s:t:' i; do
    case "$i" in
      d) dryrun=1 ;;
      f) [[ ${OPTARG} ]] || die 'Empty NAME.' && set_tr_const "${OPTARG}" ;;
      q) [[ ${OPTARG} =~ ^[0-9]+$ ]] || die 'QUOTA must be integer >= 0.' && ((quota = OPTARG * GiB)) ;;
      s) [[ ${OPTARG} && ! -d ${OPTARG} ]] || die 'Invalid json filename.' && savejson="$(normpath "${OPTARG}")" ;;
      t) [[ ${OPTARG} ]] || die "Empty TEST." && unit_test "${OPTARG}" ;;
      *) print_help ;;
    esac
  done

  # acquire lock
  exec {i}<"${BASH_SOURCE[0]##*/}"
  if [[ ${TR_TORRENT_DIR} && ${TR_TORRENT_NAME} ]]; then
    flock -x "$i"
    tr_path="${TR_TORRENT_DIR}/${TR_TORRENT_NAME}"
  elif flock -x -n "$i"; then
    tr_path=''
  else
    die "Acquiring lock failed."
  fi
  readonly -- tr_api seed_dir watch_dir GiB quota locations dryrun savejson tr_path
  trap 'write_log' EXIT

  # get API header
  [[ ${tr_header} ]] || set_tr_header
}

set_tr_header() {
  if [[ "$(curl -s -I -- "${tr_api}")" =~ 'X-Transmission-Session-Id:'[[:blank:]]*[[:alnum:]]+ ]]; then
    tr_header="${BASH_REMATCH[0]}"
    return 0
  fi
  printf 'Getting API header failed.\n' 1>&2
  return 1
}

# Send an API request.
# $1: data to send
request_tr() {
  local i
  for i in {1..4}; do
    if curl -s -f --header "${tr_header}" -d "$1" -- "${tr_api}"; then
      return 0
    elif ((i < 4)); then
      set_tr_header
    fi
  done
  printf 'Querying API failed: url: "%s", data: "%s"\n' "${tr_api}" "$1" 1>&2
  return 1
}

set_tr_const() {
  set_tr_header
  IFS=/ read -r -d '' TR_TORRENT_ID TR_TORRENT_NAME TR_TORRENT_DIR < <(
    request_tr '{"arguments":{"fields":["id","name","downloadDir"]},"method":"torrent-get"}' |
      jq -j --arg n "$1" '.arguments.torrents[]|select(.name == $n)|"\(.id)/\(.name)/\(.downloadDir)\u0000"'
  ) && [[ ${TR_TORRENT_ID} =~ ^[0-9]+$ ]] ||
    die "No name '$1' in torrent list."
  export TR_TORRENT_ID TR_TORRENT_NAME TR_TORRENT_DIR
}

# Copy finished downloads to destination. This function only runs when the
# script was invoked as "script-torrent-done" or with "-f" option.
copy_finished() {
  [[ ${tr_path} ]] || return
  local to_seeddir=0 use_rsync=0 logdir dest

  _copy_to_dest() {
    if ((use_rsync)); then
      rsync -a --exclude='*.part' --progress -- "${tr_path}" "${dest}/"
    else
      [[ -e ${dest} ]] || mkdir -p -- "${dest}" && cp -a -f -- "${tr_path}" "${dest}/"
    fi || return 1
    if ((to_seeddir)); then
      request_tr "$(
        jq -acn --argjson i "${TR_TORRENT_ID}" --arg d "${seed_dir}" \
          '{"arguments":{"ids":[$i],"location":$d},"method":"torrent-set-location"}'
      )" >/dev/null || return 1
    fi
    return 0
  }

  # decide the destination
  if [[ ${TR_TORRENT_DIR} -ef ${seed_dir} ]]; then
    # copy from seed_dir to dest
    logdir="${locations[$(
      request_tr "{\"arguments\":{\"fields\":[\"files\"],\"ids\":[${TR_TORRENT_ID:?}]},\"method\":\"torrent-get\"}" |
        jq -j '.arguments.torrents[].files[]|"\(.name)\u0000\(.length)\u0000"' |
        awk -v regexfile="${regexfile}" -f "${categorizer}"
    )]}"
    # fallback to default if failed
    logdir="$(normpath "${logdir:-${locations['default']}}")"
    # append a sub-directory if needed
    if [[ -d ${tr_path} ]]; then
      dest="${logdir}"
    elif [[ ${TR_TORRENT_NAME} =~ ([^/]*[^/.][^/]*)\.[^/.]*$ ]]; then
      dest="${logdir}/${BASH_REMATCH[1]}"
    else
      dest="${logdir}/${TR_TORRENT_NAME}"
    fi
    # whether to use rsync
    if hash rsync 1>/dev/null 2>&1; then
      if [[ ${dest} == "${logdir}" ]]; then
        (
          shopt -s nullglob globstar || exit 1
          for _ in "${dest}/${TR_TORRENT_NAME}/"*; do exit 0; done
          for f in "${tr_path}/"**/*.part; do [[ -f ${f} ]] && exit 0; done
          exit 1
        ) && use_rsync=1
      elif [[ -e "${dest}/${TR_TORRENT_NAME}" ]]; then
        use_rsync=1
      fi
    fi
  else
    # copy to seed_dir
    to_seeddir=1
    logdir="${TR_TORRENT_DIR}"
    dest="${seed_dir}"
  fi

  # copy file
  printf 'Copying: "%s" -> "%s"\n' "${tr_path}" "${dest}" 1>&2
  if ((dryrun)) || _copy_to_dest; then
    printf 'Done.\n' 1>&2
    append_log 'Finish' "${logdir}" "${TR_TORRENT_NAME}"
    return 0
  else
    printf 'Failed.\n' 1>&2
    append_log 'Error' "${logdir}" "${TR_TORRENT_NAME}"
    if [[ ${to_seeddir} -eq 1 && -e "${seed_dir}/${TR_TORRENT_NAME}" ]]; then
      rm -r -f -- "${seed_dir:?}/${TR_TORRENT_NAME:?}"
    fi
    return 1
  fi
}

# Query and parse transmission torrent list.
# torrent status number:
# https://github.com/transmission/transmission/blob/master/libtransmission/transmission.h#L1658
query_json() {
  local i result

  tr_json="$(
    request_tr '{"arguments":{"fields":["activityDate","id","name","percentDone","sizeWhenDone","status"]},"method":"torrent-get"}'
  )" || exit 1
  if [[ ${savejson} ]]; then
    printf 'Save json to: "%s"\n' "${savejson}" 1>&2
    printf '%s' "${tr_json}" | jq '.' >"${savejson}"
  fi

  {
    IFS=/ read -r -d '' tr_totalsize tr_paused result &&
      [[ ${result} == 'success' ]] &&
      while IFS= read -r -d '' i; do
        tr_names["${i}"]=1
      done
  } < <(
    printf '%s' "${tr_json}" | jq -j '
      "\([.arguments.torrents[].sizeWhenDone]|add)/\(.arguments.torrents|map(select(.status == 0))|length)/\(.result)\u0000",
      "\(.arguments.torrents[].name)\u0000"'
  ) || die "Parsing json failed. Status: '${result}'"

  printf 'Torrents: %d, size: %d GiB, paused: %d\n' \
    "${#tr_names[@]}" "$((tr_totalsize / GiB))" "${tr_paused}" 1>&2
}

# Clean junk files in seed_dir and watch_dir. This function runs in a subshell.
clean_disk() {
  (
    shopt -s nullglob dotglob globstar || exit 1
    obsolete=()

    if ((${#tr_names[@]})) && cd "${seed_dir}"; then
      for i in [^.\#@]*; do
        [[ ${tr_names["${i}"]} || ${tr_names["${i%.part}"]} ]] ||
          obsolete+=("${PWD:?}/${i}")
      done
    else
      printf 'Skip cleaning seed_dir "%s"\n' "${seed_dir}" 1>&2
    fi

    if [[ ${watch_dir} ]] && cd "${watch_dir}"; then
      for i in **; do
        [[ -s ${i} ]] || obsolete+=("${PWD:?}/${i}")
      done
    else
      printf 'Skip cleaning watch_dir "%s"\n' "${watch_dir}" 1>&2
    fi

    if ((n = ${#obsolete[@]})); then
      printf 'Delete %d files:\n' "$n" 1>&2
      printf '%s\n' "${obsolete[@]}" 1>&2
      ((dryrun)) || for ((i = 0; i < n; i += 100)); do
        rm -r -f -- "${obsolete[@]:i:100}"
      done
    fi
  )
}

# Remove inactive torrents if disk space was bellow $quota.
remove_inactive() {
  local disksize freespace target m n id size name ids names

  {
    read -r _
    read -r 'disksize' 'freespace'
  } < <(df --block-size=1 --output='size,avail' -- "${seed_dir}") &&
    [[ ${disksize} =~ ^[0-9]+$ && ${freespace} =~ ^[0-9]+$ ]] || {
    printf 'Reading disk stat failed.\n' 1>&2
    return 1
  }

  if ((m = quota + tr_totalsize - disksize, n = quota - freespace, (target = m > n ? m : n) > 0)); then
    printf 'Free space: %d GiB, will free up: %d GiB\n' \
      "$((freespace / GiB))" "$((target / GiB))" 1>&2
  else
    printf 'Free space: %d GiB, avail space: %d GiB. System is healthy.\n' \
      "$((freespace / GiB))" "$((-target / GiB))" 1>&2
    return 0
  fi

  while IFS=/ read -r -d '' id size name; do
    [[ ${name} ]] || continue
    ids+="${id},"
    names+=("${name}")
    (((target -= size) <= 0)) && break
  done < <(
    printf '%s' "${tr_json}" | jq -j '
      .arguments.torrents|
      sort_by(.activityDate)[]|
      select(.percentDone == 1)|
      "\(.id)/\(.sizeWhenDone)/\(.name)\u0000"'
  )

  if ((${#names[@]})); then
    printf 'Remove %d torrents.\n' "${#names[@]}" 1>&2
    ((dryrun)) ||
      request_tr "{\"arguments\":{\"ids\":[${ids%,}],\"delete-local-data\":true},\"method\":\"torrent-remove\"}" >/dev/null &&
      for name in "${names[@]}"; do
        append_log 'Remove' "${seed_dir}" "${name}"
      done
  fi
}

# Restart paused torrents, if any.
resume_paused() {
  if ((tr_paused > 0)); then
    printf 'Resume torrents.\n' 1>&2
    ((dryrun)) || request_tr '{"method":"torrent-start"}' >/dev/null
  fi
}

# Record one line of log.
# columns & arguments, width:
#   --: mm/dd/yy hh:mm:ss     (17)
#   $1: Finish/Remove/Error   (6)
#   $2: location              (30)
#   $3: name
append_log() {
  local loc
  if ((${#2} <= 30)); then loc="$2"; else loc="${2::27}..."; fi
  printf -v "logs[${#logs[@]}]" '%(%D %T)T  %-6s  %-30s  %s\n' -1 "$1" "$loc" "$3"
}

# Print logs in reversed order.
print_log() {
  local i
  printf '%-17s  %-6s  %-30s  %s\n%s\n' \
    'Date' 'Status' 'Location' 'Name' \
    '--------------------------------------------------------------------------------'
  for ((i = ${#logs[@]} - 1; i >= 0; i--)); do
    printf '%s' "${logs[i]}"
  done
}

# Insert logs at the beginning of $logfile.
write_log() {
  if ((${#logs[@]})); then
    {
      printf 'Logs (%d entries):\n' "${#logs[@]}"
      print_log
    } 1>&2
    ((dryrun)) && return
    local backup
    [[ -f ${logfile} ]] && backup="$(tail -n +3 -- "${logfile}")"
    {
      print_log
      [[ ${backup} ]] && printf '%s\n' "${backup}"
    } >"${logfile}"
  fi
}

unit_test() {

  _test_tr() {
    local name files key
    set_tr_header || die "Connecting failed."
    while IFS=/ read -r -d '' name files; do
      printf 'Name: %s\n' "${name}" 1>&2
      key="$(
        printf '%s' "${files}" |
          jq -j '.[]|"\(.name)\u0000\(.length)\u0000"' |
          awk -v regexfile="${regexfile}" -f "${categorizer}"
      )"
      _examine_test "${key}" "${name}"
    done < <(
      request_tr '{"arguments":{"fields":["name","files"]},"method":"torrent-get"}' |
        jq -j '.arguments.torrents[]|"\(.name)/\(.files)\u0000"'
    )
  }

  _test_dir() {
    local name="$1" root="$2" key
    printf 'Name: %s\n' "${name}" 1>&2
    key="$(
      if [[ ${root} ]] && { [[ ${PWD} == "${root}" ]] || cd "${root}" 1>/dev/null 2>&1; }; then
        find "${name}" -name '[.#@]*' -prune -o -type f -printf '%p\0%s\0'
      else
        printf '%s\0%d\0' "${name}" 0
      fi | awk -v regexfile="${regexfile}" -f "${categorizer}"
    )"
    _examine_test "${key}" "$@"
  }

  _examine_test() {
    local key="$1" name="$2" root="$3" color
    case "${key}" in
      default) color=0 ;;
      av) color=32 ;;
      film) color=33 ;;
      tv) color=34 ;;
      music) color=35 ;;
      '')
        error+=("Runtime Error: '${name}'")
        color=31
        ;;
      *)
        error+=("Invalid type: '${name}' -> '${key}'")
        color=31
        ;;
    esac
    if [[ ${color} != 31 && ${root} && ! ${root} -ef ${locations[${key}]} ]]; then
      error+=("Differ: '${root}/${name}' -> '${locations[${key}]}' (${key})")
      color=31
    fi
    printf "\033[${color}m%s\n%s\033[0m\n---\n" "Type: ${key}" "Root: ${locations[${key}]}" 1>&2
  }

  local arg name error=()
  [[ $1 == 'all' ]] && set -- tr tv film

  for arg; do
    printf '=== %s ===\n' "${arg}" 1>&2
    case "${arg}" in
      tr) _test_tr ;;
      tv | film)
        pushd "${locations[${arg}]}" 1>/dev/null 2>&1 || die "Unable to enter: '${locations[${arg}]}'"
        shopt -s nullglob
        for name in [^.\#@]*; do
          _test_dir "${name}" "${PWD}"
        done
        shopt -u nullglob
        popd 1>/dev/null 2>&1
        ;;
      *)
        if [[ -e ${arg} ]]; then
          _test_dir "$(basename "${arg}")" "$(dirname "${arg}")"
        else
          _test_dir "$(normpath "${arg}")"
        fi
        ;;
    esac
  done

  if ((${#error})); then
    printf '%s\n' "Errors (${#error[@]}):" "${error[@]}" 1>&2
    exit 1
  else
    printf '%s\n' 'Finished.' 1>&2
    exit 0
  fi
}

################################################################################
#                                     Main                                     #
################################################################################

init "$@"
copy_finished
query_json
clean_disk
remove_inactive
resume_paused
exit 0
