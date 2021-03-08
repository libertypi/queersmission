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

unset IFS
export LC_ALL=C LANG=C

((BASH_VERSINFO[0] >= 4)) 1>/dev/null 2>&1 || die 'Bash >=4 required.'
cd "${BASH_SOURCE[0]%/*}" || die 'Unable to enter script directory.'
source ./config || die "Loading config file failed."
hash curl jq || die 'Curl and jq required.'

readonly -- \
  logfile="${PWD}/logfile.log" \
  categorize="${PWD}/component/categorize.awk" \
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
  -s FILE    save formated json to FILE
  -q NUM     set disk quota to NUM GiB (default: $((quota / GiB)))
  -t TARGET  unit test, TARGET: "all", "tr", "tv", "film" or custom path
EOF
  exit 1
}

# Normalize path, eliminating double slashes, etc.
# Usage: new_path="$(normpath "${old_path}")"
# Translated from Python's posixpath.normpath:
# https://github.com/python/cpython/blob/master/Lib/posixpath.py#L337
normpath() {
  local IFS=/ s='' c cs=()
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
  printf '%s\n' "${c:-.}"
}

init() {
  local i
  # varify configurations
  [[ ${seed_dir} == /* && ${locations['default']} == /* && ${tr_api} == http* && ${quota} -ge 0 ]] ||
    die 'Invalid configuration.'
  seed_dir="$(normpath "${seed_dir}")"

  # init variables
  tr_header='' tr_json='' tr_totalsize='' tr_paused='' logs=() dryrun=0 savejson=''
  declare -Ag tr_names=()

  # parse arguments
  while getopts 'hds:q:t:' i; do
    case "$i" in
      d) dryrun=1 ;;
      s) savejson="$(normpath "${OPTARG}")" && [[ ! -d ${savejson} ]] || die 'Invalid json filename.' ;;
      q) [[ ${OPTARG} =~ ^[0-9]+$ ]] || die 'QUOTA must be integer >= 0.' && ((quota = OPTARG * GiB)) ;;
      t) unit_test "${OPTARG}" ;;
      *) print_help ;;
    esac
  done
  readonly tr_api seed_dir watch_dir GiB quota locations dryrun savejson

  # acquire lock
  printf 'Acquiring lock...' 1>&2
  exec {i}<"${BASH_SOURCE[0]##*/}"
  if [[ ${TR_TORRENT_DIR} && ${TR_TORRENT_NAME} ]]; then
    flock -x "$i"
    readonly tr_path="${TR_TORRENT_DIR}/${TR_TORRENT_NAME}"
  elif flock -xn "$i"; then
    readonly tr_path=''
  else
    printf 'Failed.\n' 1>&2
    exit 1
  fi
  printf 'Done.\n' 1>&2
  trap 'write_log' EXIT
}

# Copy finished downloads to destination.
# This function only runs when the script was invoked by transmission as
# "script-torrent-done".
copy_finished() {
  [[ ${tr_path} ]] || return
  local root dest

  get_tr_header
  if [[ ${TR_TORRENT_DIR} -ef ${seed_dir} ]]; then
    # decide the destination location
    root="${locations[$(
      request_tr "{\"arguments\":{\"fields\":[\"files\"],\"ids\":[${TR_TORRENT_ID:?}]},\"method\":\"torrent-get\"}" |
        jq -j '.arguments.torrents[].files[]|"\(.length)\u0000\(.name)\u0000"' |
        awk -v regexfile="${regexfile}" -f "${categorize}"
    )]}"
    # fallback to default if failed
    root="$(normpath "${root:-${locations[default]}}")"
    # append a sub-directory if needed
    if [[ -d ${tr_path} ]]; then
      dest="${root}"
    elif [[ ${dest} =~ ([^/]*[^/.][^/]*)\.[^/.]*$ ]]; then
      dest="${root}/${BASH_REMATCH[1]}"
    else
      dest="${root}/${dest}"
    fi
    # copy file
    if [[ -e ${dest} ]] || mkdir -p -- "${dest}" &&
      cp -r -f -- "${tr_path}" "${dest}/"; then
      append_log 'Finish' "${root}" "${TR_TORRENT_NAME}"
      return 0
    fi
  elif [[ -e ${seed_dir} ]] || mkdir -p -- "${seed_dir}" &&
    cp -r -f -- "${tr_path}" "${seed_dir}/" &&
    request_tr "$(jq -acn --argjson i "${TR_TORRENT_ID}" --arg d "${seed_dir}" '{"arguments":{"ids":[$i],"location":$d},"method":"torrent-set-location"}')" >/dev/null; then
    append_log 'Finish' "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    return 0
  elif [[ -e "${seed_dir}/${TR_TORRENT_NAME}" ]]; then
    rm -r -f -- "${seed_dir:?}/${TR_TORRENT_NAME:?}"
  fi

  append_log 'Error' "${root:-${TR_TORRENT_DIR}}" "${TR_TORRENT_NAME}"
  return 1
}

get_tr_header() {
  if [[ "$(curl -s -I -- "${tr_api}")" =~ 'X-Transmission-Session-Id:'[[:blank:]]*[[:alnum:]]+ ]]; then
    tr_header="${BASH_REMATCH[0]}"
    return 0
  else
    printf 'Getting API header failed.\n' 1>&2
    return 1
  fi
}

# Send an API request.
# Arguments: $1: data to send
request_tr() {
  if [[ -z $1 ]]; then
    printf 'Error: Empty argument.\n' 1>&2
    return 1
  fi
  local i
  for i in {1..4}; do
    if curl -s -f --header "${tr_header}" -d "$1" -- "${tr_api}"; then
      return 0
    elif ((i < 4)); then
      printf 'Querying API failed. Retries: %d\n' "${i}" 1>&2
      get_tr_header
    fi
  done
  printf 'Querying API failed: url: "%s", data: "%s"\n' "${tr_api}" "$1" 1>&2
  return 1
}

# Get and parse transmission json.
# torrent status number:
# https://github.com/transmission/transmission/blob/master/libtransmission/transmission.h#L1658
query_json() {
  local i result

  [[ ${tr_header} ]] || get_tr_header
  tr_json="$(
    request_tr '{"arguments":{"fields":["activityDate","id","name","percentDone","sizeWhenDone","status","trackerStats"]},"method":"torrent-get"}'
  )" || exit 1
  if [[ ${savejson} ]]; then
    printf 'Save json to %s\n' "${savejson}" 1>&2
    printf '%s' "${tr_json}" | jq '.' >"${savejson}"
  fi

  {
    for i in 'result' 'tr_paused' 'tr_totalsize'; do
      read -r -d '' "$i"
    done && while IFS= read -r -d '' i; do
      tr_names["${i}"]=1
    done
  } < <(
    printf '%s' "${tr_json}" | jq -j '
      "\(.result)\u0000",
      "\(.arguments.torrents|map(select(.status == 0))|length)\u0000",
      "\([.arguments.torrents[].sizeWhenDone]|add)\u0000",
      "\(.arguments.torrents[].name)\u0000"'
  ) && [[ ${result} == 'success' ]] ||
    die "Parsing json failed. Status: '${result}'"

  printf 'Torrents: %d, size: %d GiB, paused: %d\n' \
    "${#tr_names[@]}" "$((tr_totalsize / GiB))" "${tr_paused}" 1>&2
  return 0
}

# Clean junk files in seed_dir and watch_dir. This function runs in a subshell.
clean_disk() (
  shopt -s nullglob dotglob globstar
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
      sort_by(.activityDate, ([.trackerStats[].leecherCount]|add))[]|
      select(.percentDone == 1)|
      "\(.id)/\(.sizeWhenDone)/\(.name)\u0000"'
  )

  if ((${#names[@]})); then
    printf 'Remove %d torrents.\n' "${#names[@]}" 1>&2
    ((dryrun)) || {
      request_tr "{\"arguments\":{\"ids\":[${ids%,}],\"delete-local-data\":true},\"method\":\"torrent-remove\"}" >/dev/null
    } && for name in "${names[@]}"; do
      append_log 'Remove' "${seed_dir}" "${name}"
    done
  fi
}

# Restart paused torrents, if there is any.
resume_paused() {
  if ((tr_paused > 0)); then
    printf 'Resume torrents.\n'
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
    if ((dryrun)); then
      printf 'Logs (%d entries):\n' "${#logs[@]}" 1>&2
      print_log 1>&2
    else
      local backup
      [[ -f ${logfile} ]] && backup="$(tail -n +3 -- "${logfile}")"
      {
        print_log
        [[ ${backup} ]] && printf '%s\n' "${backup}"
      } >"${logfile}"
    fi
  fi
}

unit_test() {

  test_tr() {
    local name files key
    get_tr_header || die "Connecting failed."
    while IFS=/ read -r -d '' name files; do
      printf 'Name: %s\n' "${name}" 1>&2
      key="$(
        printf '%s' "${files}" |
          jq -j '.[]|"\(.length)\u0000\(.name)\u0000"' |
          awk -v regexfile="${regexfile}" -f "${categorize}"
      )"
      examine "${name}" "${key}"
    done < <(
      request_tr '{"arguments":{"fields":["name","files"]},"method":"torrent-get"}' |
        jq -j '.arguments.torrents[]|"\(.name)/\(.files)\u0000"'
    )
  }

  test_dir() {
    local root="$1" name="$2" key
    printf 'Name: %s\n' "${name}" 1>&2
    key="$(
      if [[ ${root} ]] && { [[ ${PWD} == "${root}" ]] || cd "${root}"; }; then
        find "${name}" -name '[.#@]*' -prune -o -type f -printf '%s\0%p\0'
      else
        printf '%d\0%s\0' 0 "${name}"
      fi | awk -v regexfile="${regexfile}" -f "${categorize}"
    )"
    examine "${name}" "${key}" "${root}"
  }

  examine() {
    local name="$1" key="$2" root="$3" color
    if [[ -z ${key} ]]; then
      error+=("Runtime Error: '${name}' -> ${key}")
      color=31
    elif [[ ${root} && ! ${locations[${key}]} -ef ${root} ]]; then
      error+=("Differ: '${root}/${name}' -> '${locations[${key}]}' (${key})")
      color=31
    else
      case "${key}" in
        default) color=0 ;;
        av) color=32 ;;
        film) color=33 ;;
        tv) color=34 ;;
        music) color=35 ;;
        adobe) color=36 ;;
        *)
          error+=("Invalid type: '${name}' -> '${key}'")
          color=31
          ;;
      esac
    fi
    printf "\033[${color}m%s\n%s\033[0m\n" "Type: ${key}" "Root: ${locations[${key}]}" 1>&2
  }

  case "$1" in
    all) set -- tr tv film ;;
    '') die "Empty unittest target." ;;
  esac
  local arg name error=()

  for arg in "$@"; do
    printf '=== %s ===\n' "${arg}" 1>&2
    case "${arg}" in
      tr) test_tr ;;
      tv | film)
        pushd "${locations[${arg}]}" >/dev/null || die "Unable to enter: '${locations[${arg}]}'"
        shopt -s nullglob
        for name in [^.\#@]*; do
          test_dir "${PWD}" "${name}"
        done
        popd >/dev/null
        ;;
      *)
        if [[ -e ${arg} ]]; then
          test_dir "$(dirname "${arg}")" "$(basename "${arg}")"
        else
          test_dir "" "$(normpath "${arg}")"
        fi
        ;;
    esac
    printf '\n' 1>&2
  done

  if ((${#error})); then
    printf '%s\n' 'Errors:' "${error[@]}" 1>&2
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
