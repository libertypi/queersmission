#!/usr/bin/env bash

# Bash script for transmission maintenance and torrent management.
# Author: David Pi

################################################################################
#                                 Environment                                  #
################################################################################

die() {
  printf 'Fatal: %s\n' "$1" 1>&2
  exit 1
}

export LC_ALL=C LANG=C
unset IFS seed_dir locations tr_api quota watch_dir

((BASH_VERSINFO >= 4)) 1>/dev/null 2>&1 || die 'Bash >=4 required.'
hash curl jq || die 'Curl and jq required.'
cd -- "${BASH_SOURCE[0]%/*}" || die 'Unable to enter script directory.'

readonly GiB=1073741824
. ./config || die "Loading config file failed."
[[ ${tr_api} == http* && ${seed_dir} == /* && ${quota} -ge 0 && ${locations['default']} == /* ]] ||
  die 'Invalid configuration.'

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
  -d         perform a trial run with no changes made
  -s         show transmission torrent list
  -f ID      force copy torrent ID, like "script-torrent-done"
  -j FILE    save json format data to FILE
  -q NUM     set disk quota to NUM GiB, override config file
  -t TEST    test categorizer. TEST: "all", "tr", "tv", "film",
             torrent ID or custom path
EOF
  exit 0
}

init() {
  # init variables
  local i
  readonly -- locations tr_api watch_dir \
    seed_dir="$(normpath "${seed_dir}")" \
    logfile="${PWD}/logfile.log" \
    categorizer="${PWD}/component/categorizer.awk" \
    regexfile="${PWD}/component/regex.txt" \
    RED='\e[31m' GREEN='\e[32m' YELLOW='\e[33m' BLUE='\e[94m' \
    MAGENTA='\e[95m' ENDCOLOR='\e[0m'
  tr_header='' savejson='' dryrun=0 logs=()

  # parse arguments
  while getopts 'hdsf:j:q:t:' i; do
    case "${i}" in
      h) print_help ;;
      d) dryrun=1 ;;
      s) show_tr_list ;;
      f) [[ ${OPTARG} =~ ^[0-9]+$ ]] || die 'ID must be integer >= 0' && TR_TORRENT_ID="${OPTARG}" ;;
      j) [[ ${OPTARG} ]] || die 'Empty json filename.' && savejson="${OPTARG}" ;;
      q) [[ ${OPTARG} =~ ^[0-9]+$ ]] || die 'QUOTA must be integer >= 0.' && ((quota = OPTARG * GiB)) ;;
      t) [[ ${OPTARG} ]] || die 'Empty TEST argument.' && unit_test "${OPTARG}" ;;
      *) die "Try '${BASH_SOURCE[0]} -h' for more information" ;;
    esac
  done
  readonly -- quota dryrun savejson

  # acuire lock
  exec {i}<"./${BASH_SOURCE[0]##*/}"
  if [[ ${TR_TORRENT_ID} ]]; then
    flock -x "${i}"
  elif ! flock -x -n "${i}"; then
    die "Unable to acquire lock, another instance running?"
  fi
  trap 'write_log' EXIT
}

# Copy finished downloads to destination. This function only runs when the
# script was invoked as "script-torrent-done" or with "-f" option.
copy_finished() {
  [[ ${TR_TORRENT_ID} ]] || return 0

  _copy_to_dest() {
    if ((use_rsync)); then
      rsync -a --exclude='*.part' --progress -- "${src}" "${dest}/"
    else
      [[ -e ${dest} ]] || mkdir -p -- "${dest}" && cp -a -f -- "${src}" "${dest}/"
    fi || return 1
    if [[ ${dest} == "${seed_dir}" ]]; then
      request_tr "$(
        jq -acn --argjson i "${TR_TORRENT_ID}" --arg d "${seed_dir}" \
          '{"arguments":{"ids":[$i],"location":$d},"method":"torrent-set-location"}'
      )" >/dev/null || return 1
    fi
    return 0
  }

  local src dest logdir data use_rsync=0

  [[ ${TR_TORRENT_NAME} && ${TR_TORRENT_DIR} ]] || {
    data="$(query_tr_by_id "${TR_TORRENT_ID}")" || die "Connecting failed."
    IFS=/ read -r -d '' TR_TORRENT_NAME TR_TORRENT_DIR < <(
      printf '%s' "${data}" | jq -j '.arguments.torrents[]|"\(.name)/\(.downloadDir)\u0000"'
    ) && [[ ${TR_TORRENT_NAME} && ${TR_TORRENT_DIR} ]] ||
      die "Invalid torrent ID '${TR_TORRENT_ID}'. Run '${BASH_SOURCE[0]} -s' to show torrent list."
  }
  src="$(normpath "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}")"

  # decide the destination
  if [[ ${TR_TORRENT_DIR} -ef ${seed_dir} ]]; then # source: seed_dir
    logdir="$(
      if [[ ${data} ]]; then printf '%s' "${data}"; else query_tr_by_id "${TR_TORRENT_ID}"; fi |
        jq -j '.arguments.torrents[].files[]|"\(.name)\u0000\(.length)\u0000"' |
        awk -v regexfile="${regexfile}" -f "${categorizer}"
    )"
    # fallback to default if failed
    logdir="$(normpath "${locations[${logdir:-default}]:-${locations[default]}}")"
    # if source is not a dir, append a sub-directory
    if [[ -d ${src} ]]; then
      dest="${logdir}"
    elif [[ ${TR_TORRENT_NAME} =~ (.*[^.].*)\.[^.]*$ ]]; then
      dest="${logdir}/${BASH_REMATCH[1]}"
    else
      dest="${logdir}/${TR_TORRENT_NAME}"
    fi
    # whether to use rsync
    if hash rsync 1>/dev/null 2>&1; then
      if [[ ${dest} == "${logdir}" ]]; then
        (
          shopt -s nullglob globstar || exit 1
          for f in "${dest}/${TR_TORRENT_NAME}/"**; do [[ -f ${f} ]] && exit 0; done
          for f in "${src}/"**/*.part; do [[ -f ${f} ]] && exit 0; done
          exit 1
        ) && use_rsync=1
      elif [[ -e "${dest}/${TR_TORRENT_NAME}" ]]; then
        use_rsync=1
      fi
    fi
  else # dest: seed_dir
    logdir="${TR_TORRENT_DIR}"
    dest="${seed_dir}"
  fi

  # copy file
  append_log 'Error' "${logdir}" "${TR_TORRENT_NAME}"
  if ((use_rsync)); then data='Syncing'; else data='Copying'; fi
  printf '%s: "%s" -> "%s/"\n' "${data}" "${src}" "${dest}" 1>&2
  if ((dryrun)) || _copy_to_dest; then
    unset 'logs[-1]'
    append_log 'Finish' "${logdir}" "${TR_TORRENT_NAME}"
    printf 'Done.\n' 1>&2
    return 0
  fi
  printf 'Failed.\n' 1>&2
  return 1
}

# Query and parse API maindata.
# torrent status number:
# https://github.com/transmission/transmission/blob/master/libtransmission/transmission.h#L1658
process_maindata() {
  local count pct size name dir
  declare -Ag tr_names=()

  tr_maindata="$(
    request_tr '{"arguments":{"fields":["activityDate","downloadDir","id","name","percentDone","sizeWhenDone","status"]},"method":"torrent-get"}'
  )" || die 'Unable to connect to transmission API.'
  if [[ ${savejson} ]]; then
    printf '%s' "${tr_maindata}" | jq '.' >"${savejson}" &&
      printf 'Json data saved to: "%s"\n' "${savejson}" 1>&2
  fi

  {
    IFS=/ read -r -d '' count tr_totalsize tr_paused || die "Invalid json response."
    while IFS=/ read -r -d '' pct size name dir; do
      if [[ ${seed_dir} == "${dir}" || ${seed_dir} -ef ${dir} ]]; then
        tr_names["${name}"]=1
      elif [[ ${pct} == 1 ]]; then
        # finished torrents outside seed_dir are excluded from size calculation
        ((tr_totalsize -= size))
      fi
    done
  } < <(
    printf '%s' "${tr_maindata}" | jq -j '
      if .result == "success" then
      .arguments.torrents|
      ("\(length)/\([.[].sizeWhenDone]|add)/\(map(select(.status == 0))|length)\u0000"),
      (.[]|"\(.percentDone)/\(.sizeWhenDone)/\(.name)/\(.downloadDir)\u0000")
      else empty end'
  )

  printf 'torrents: %d, paused: %d, size: %d GiB\n' \
    "${count}" "${tr_paused}" "$((tr_totalsize / GiB))" 1>&2
}

# Clean junk files in seed_dir and watch_dir. This function runs in a subshell.
clean_disk() {
  (
    shopt -s nullglob dotglob || exit 1
    obsolete=()

    if ((${#tr_names[@]})) && cd -- "${seed_dir}"; then
      for i in *; do
        [[ ${tr_names["${i}"]} || ${tr_names["${i%.part}"]} ]] ||
          obsolete+=("${PWD:-${seed_dir}}/${i}")
      done
    else
      printf 'Skip cleanup: "%s"\n' "${seed_dir}" 1>&2
    fi
    if [[ ${watch_dir} ]]; then
      for i in "${watch_dir}/"*.torrent; do
        [[ -s ${i} ]] || obsolete+=("${i}")
      done
    fi

    if ((${#obsolete[@]})); then
      printf 'Cleanup: %s\n' "${obsolete[@]}" 1>&2
      ((dryrun)) || for ((i = 0; i < ${#obsolete[@]}; i += 100)); do
        rm -r -f -- "${obsolete[@]:i:100}"
      done
    fi
  )
}

# Remove inactive torrents if disk space was bellow $quota.
remove_inactive() {
  local disksize freespace target m n id size ids names

  {
    read -r _
    read -r disksize freespace
  } < <(df --block-size=1 --output='size,avail' -- "${seed_dir}") &&
    [[ ${disksize} =~ ^[0-9]+$ && ${freespace} =~ ^[0-9]+$ ]] || {
    printf 'Reading disk stat failed.\n' 1>&2
    return 1
  }

  if ((m = quota + tr_totalsize - disksize, n = quota - freespace, (target = m > n ? m : n) > 0)); then
    printf 'disk free space: %d GiB, will remove: %d GiB\n' "$((freespace / GiB))" "$((target / GiB))" 1>&2
  else
    printf 'disk free space: %d GiB, availability: %d GiB. System is healthy.\n' \
      "$((freespace / GiB))" "$((-target / GiB))" 1>&2
    return 0
  fi

  while IFS=/ read -r -d '' id size n; do
    [[ ${tr_names["${n}"]} ]] || continue
    ids+="${id},"
    names+=("${n}")
    (((target -= size) <= 0)) && break
  done < <(
    printf '%s' "${tr_maindata}" | jq -j '
      .arguments.torrents|
      sort_by(.activityDate)[]|
      select(.percentDone == 1)|
      "\(.id)/\(.sizeWhenDone)/\(.name)\u0000"'
  )

  if ((${#names[@]})); then
    printf 'Remove: %s\n' "${names[@]}" 1>&2
    ((dryrun)) ||
      request_tr "{\"arguments\":{\"ids\":[${ids%,}],\"delete-local-data\":true},\"method\":\"torrent-remove\"}" >/dev/null &&
      for n in "${names[@]}"; do
        append_log 'Remove' "${seed_dir}" "${n}"
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

set_tr_header() {
  if [[ "$(curl -s -I -- "${tr_api}")" =~ 'X-Transmission-Session-Id:'[[:blank:]]*[[:alnum:]]+ ]]; then
    tr_header="${BASH_REMATCH[0]}"
    return 0
  fi
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
  printf 'Connection failure. url: \047%s\047, request: \047%s\047\n' "${tr_api}" "$1" 1>&2
  return 1
}

# query torrent info by id
query_tr_by_id() {
  request_tr "{\"arguments\":{\"fields\":[\"name\",\"downloadDir\",\"files\"],\"ids\":[${1:?}]},\"method\":\"torrent-get\"}"
}

# Record one line of log.
# columns & arguments, width:
#   --: mm/dd/yy hh:mm:ss     (17)
#   $1: Finish/Remove/Error   (6)
#   $2: location              (30)
#   $3: name
append_log() {
  printf -v "logs[${#logs[@]}]" '%(%D %T)T  %-6.6s  %-30.30s  %s\n' \
    -1 "$1" "${2//[[:cntrl:]]/ }" "${3//[[:cntrl:]]/ }"
}

# Print logs in reversed order.
print_log() {
  local i
  printf -v i '%.0s-' {1..80} # sep-line length: 80
  printf '%-17s  %-6s  %-30s  %s\n%s\n' 'Date' 'Status' 'Location' 'Name' "${i}"
  for ((i = ${#logs[@]} - 1; i >= 0; i--)); do
    printf '%s' "${logs[i]}"
  done
}

# Insert logs at the beginning of $logfile.
write_log() {
  if ((${#logs[@]})); then
    if ((dryrun)); then
      {
        printf 'Logs (%d entries):\n' "${#logs[@]}"
        print_log
      } 1>&2
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

show_tr_list() {
  local id name pct dir w1=2 w2=8 arr=()
  set_tr_header || die 'Connection failed.'

  while IFS=/ read -r -d '' id pct name dir; do
    arr+=("${id}" "${pct}" "${dir}" "${name}")
    ((${#id} > w1)) && w1="${#id}"
    ((${#dir} > w2)) && w2="${#dir}"
  done < <(
    request_tr '{"arguments":{"fields":["id","percentDone","name","downloadDir"]},"method":"torrent-get"}' |
      jq -j '.arguments.torrents[]|"\(.id)/\(.percentDone * 100)/\(.name)/\(.downloadDir)\u0000"'
  )
  ((${#arr[@]})) || exit 1

  printf "%${w1}s  %5s  %-${w2}s  %s\n" 'ID' 'PCT' 'LOCATION' 'NAME'
  if [[ -t 1 ]]; then
    w1="%${w1}d  ${MAGENTA}%5.1f  %-${w2}s  ${YELLOW}%s${ENDCOLOR}\n"
  else
    w1="%${w1}d  %5.1f  %-${w2}s  %s\n"
  fi
  printf "${w1}" "${arr[@]//[[:cntrl:]]/ }"
  exit 0
}

unit_test() {

  _test_tr() {
    local id="$1" name files key
    set_tr_header || die 'Unable to connect to transmission API.'
    while IFS=/ read -r -d '' name files; do
      key="$(
        printf '%s' "${files}" |
          jq -j '.[]|"\(.name)\u0000\(.length)\u0000"' |
          awk -v regexfile="${regexfile}" -f "${categorizer}"
      )"
      _examine_test "${key}" "${name}"
    done < <(
      if [[ ${id} ]]; then
        query_tr_by_id "${id}"
      else
        request_tr '{"arguments":{"fields":["name","files"]},"method":"torrent-get"}'
      fi | jq -j '.arguments.torrents[]|"\(.name)/\(.files)\u0000"'
    )
  }

  _test_dir() {
    local name="$1" path="$2" key
    key="$(
      if [[ ${path} ]] && { [[ ${PWD} == "${path}" ]] || cd -- "${path}" 1>/dev/null 2>&1; }; then
        find "${name}" -name '[.#@]*' -prune -o -type f -printf '%p\0%s\0'
      else
        printf '%s\0%d\0' "${name}" 1
      fi | awk -v regexfile="${regexfile}" -f "${categorizer}"
    )"
    _examine_test "${key}" "$@"
  }

  _examine_test() {
    local key="$1" name="$2" path="$3" dest err i fmt result

    case "${key}" in
      av) fmt="${YELLOW}" ;;
      film) fmt="${BLUE}" ;;
      tv) fmt="${MAGENTA}" ;;
      music) fmt="${GREEN}" ;;
      default) ;;
      '') err='runtime error' ;;
      *) err='invalid type' ;;
    esac
    if [[ -z ${err} ]]; then
      dest="${locations[${key}]}"
      [[ ${path} && ! ${path} -ef ${dest} ]] && err='different path'
    fi

    result=('name' "${name}" 'path' "${path}" 'dest' "${dest}" 'type' "${key}" 'stat' "${err:-pass}")
    for i in {1..7..2}; do
      case "${result[i]}" in
        '') result[i]='null' ;;
        *[[:cntrl:]\\\"]*) result[i]="$(jq -cn --arg s "${result[i]}" '$s')" ;;
        *) ((i < 7)) && result[i]="\"${result[i]}\"" ;;
      esac
    done

    if [[ ${err} ]]; then
      error+=("${result[@]}")
      fmt="${RED}"
    fi
    if ((isatty)); then
      fmt="%s: ${fmt}%s${ENDCOLOR}\n"
    else
      fmt='%s: %s\n'
    fi

    printf -- "- ${fmt}" "${result[@]::2}"
    printf -- "  ${fmt}" "${result[@]:2}"
  }

  local arg i isatty error=()
  if [[ -t 1 ]]; then isatty=1; else isatty=0; fi
  [[ $1 == 'all' ]] && set -- tr tv film

  printf '%s:\n' "results"
  for arg; do
    case "${arg}" in
      tr) _test_tr ;;
      tv | film)
        pushd -- "${locations[${arg}]}" 1>/dev/null 2>&1 ||
          die "Unable to enter: '${locations[${arg}]}'"
        shopt -s nullglob
        for i in [^.\#@]*; do
          _test_dir "${i}" "${PWD}"
        done
        shopt -u nullglob
        popd 1>/dev/null 2>&1
        ;;
      *)
        if [[ ${arg} =~ ^[0-9]+$ ]]; then
          _test_tr "${arg}"
        elif [[ -e ${arg} ]]; then
          _test_dir "$(basename "${arg}")" "$(dirname "${arg}")"
        else
          _test_dir "${arg}"
        fi
        ;;
    esac
  done

  if ((arg = ${#error[@]})); then
    printf '%s:\n' 'errors'
    for ((i = 0; i < arg; i += 10)); do
      printf -- "- %s: %s\n" "${error[@]:i:2}"
      printf -- "  %s: %s\n" "${error[@]:i+2:8}"
    done
    exit 1
  fi
  exit 0
}

################################################################################
#                                     Main                                     #
################################################################################

init "$@"
set_tr_header
copy_finished
process_maindata
clean_disk
remove_inactive
resume_paused
exit 0
