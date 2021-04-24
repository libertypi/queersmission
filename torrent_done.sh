#!/usr/bin/env bash

# Bash script for transmission maintenance and torrent management.
# Author: David Pi

die() {
  printf 'Fatal: %s\n' "$1" 1>&2
  exit 1
}
export LC_ALL=C LANG=C
[[ ${BASH_VERSINFO} -ge 4 ]] 1>/dev/null 2>&1 || die 'Bash >=4 required.'

################################################################################
#                                  Functions                                   #
################################################################################

print_help() {
  cat <<EOF 1>&2
usage: ${BASH_SOURCE[0]} [OPTION]...

Transmission maintenance and management tool.
Author: David Pi

Transmission maintenance:
  -j FILE    save json format data to FILE
  -q NUM     set rm_thresh to NUM GiB, override config file

Torrent management:
  -f ID      force copy torrent ID, like "script-torrent-done"
  -l         show transmission torrent list
  -s ID      show detail information of torrent ID

Miscellaneous:
  -d         perform a dry run with no changes made
  -h         show this message and exit
  -t TEST    categorizer unit test
             TEST: "all", "tr", "tv", "film" or any path
EOF
  exit 0
}

arg_error() {
  [[ $1 ]] && printf '%s: %s -- %s\n' "${BASH_SOURCE[0]}" "$1" "$2"
  printf "Try '%s -h' for more information.\n" "${BASH_SOURCE[0]}"
  exit 1
} 1>&2

# Normalize path, eliminating double slashes, etc.
# Usage: normpath var path
# Result is assigned to shell variable var.
# Translated from Python's posixpath.normpath:
# https://github.com/python/cpython/blob/master/Lib/posixpath.py#L337
normpath() {
  local IFS=/ c s a
  if [[ $2 == /* ]]; then
    s='/'
    [[ $2 == //* && $2 != ///* ]] && s='//'
  fi
  for c in $2; do
    [[ -z ${c} || ${c} == '.' ]] && continue
    if [[ ${c} != '..' || (-z ${s} && ${#a[@]} -eq 0) || (${#a[@]} -gt 0 && ${a[-1]} == '..') ]]; then
      a+=("${c}")
    elif ((${#a[@]})); then
      unset 'a[-1]'
    fi
  done
  c="${s}${a[*]}"
  printf -v "$1" '%s' "${c:-.}"
}

# Return 0 if the string is a digit string, otherwise 1.
isdigit() {
  [[ $1 && $1 != *[!0-9]* ]]
}

# Get the X-Transmission-Session-Id header.
# Global: rpc_header
set_rpc_header() {
  if [[ "$(curl -sI --retry 3 "${rpc_auth[@]}" -- "${rpc_url}")" =~ X-Transmission-Session-Id[[:blank:]]*:[[:blank:]]*[[:alnum:]]+ ]]; then
    rpc_header="${BASH_REMATCH[0]}"
    return 0
  fi
  return 1
}

# Send an API request.
# Usage: `request_rpc DATA [VAR]`
# VAR: assign response to VAR rather than display on the stdout.
request_rpc() {
  local i
  for i in 1 0; do
    [[ ${rpc_header} ]] || set_rpc_header || break
    if [[ $2 ]]; then
      eval "${2}"'="$(curl -sf --retry 3 -H "${rpc_header}" -d "$1" "${rpc_auth[@]}" -- "${rpc_url}")"'
    else
      curl -sf --retry 3 -H "${rpc_header}" -d "$1" "${rpc_auth[@]}" -- "${rpc_url}"
    fi && return 0
    ((i)) && unset rpc_header
  done
  printf "Connection failed. URL: '%s', POST: '%s', Session-Id: '%s'\n" "${rpc_url}" "$1" "${rpc_header}" 1>&2
  return 1
}

# Record one line of log.
# Global: logs
# param  column            width
#    --  mm/dd/yy hh:mm:ss    17
#    $1  Finish/Remove/Error   6
#    $2  location             30
#    $3  name                 --
append_log() {
  printf -v "logs[${#logs[@]}]" '%(%D %T)T  %-6.6s  %-30.30s  %s\n' \
    -1 "$1" "${2//[[:cntrl:]]/ }" "${3//[[:cntrl:]]/ }"
}

# Print logs in reversed order.
print_log() {
  local i
  printf -v i '%.0s-' {1..80} # "-" * 80
  printf '%-17s  %-6s  %-30s  %s\n%s\n' 'Date' 'Status' 'Location' 'Name' "${i}"
  for ((i = ${#logs[@]} - 1; i >= 0; i--)); do
    printf '%s' "${logs[i]}"
  done
}

# Prepend logs to logfile.
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

set_colors() {
  if [[ -t 1 ]]; then
    readonly -- RED='\e[31m' GREEN='\e[32m' YELLOW='\e[33m' BLUE='\e[94m' \
      MAGENTA='\e[95m' CYAN='\e[36m' ENDCOLOR='\e[0m'
  else
    readonly -- RED='' GREEN='' YELLOW='' BLUE='' MAGENTA='' CYAN='' ENDCOLOR=''
  fi
}

# Copy finished downloads to destination.
copy_finished() {
  [[ ${TR_TORRENT_ID} ]] || return 0

  _copy_to_dest() {
    if ((use_rsync)); then
      rsync -a --exclude='*.part' --progress -- "${src}" "${dest}/"
    else
      [[ -e ${dest} ]] || mkdir -p -- "${dest}" && cp -a -f -- "${src}" "${dest}/"
    fi || return 1
    if [[ ${dest} == "${download_dir}" ]]; then
      request_rpc "$(jq -acn --argjson i "${TR_TORRENT_ID}" --arg d "${download_dir}" \
        '{"arguments":{"ids":$i,"location":$d},"method":"torrent-set-location"}')" >/dev/null || return 1
    fi
    return 0
  }

  _query_tr_id() {
    request_rpc "{\"arguments\":{\"fields\":[\"name\",\"downloadDir\",\"files\"],\"ids\":${TR_TORRENT_ID}},\"method\":\"torrent-get\"}" "$@"
  }

  ### begin ###
  local src dest logdir data use_rsync=0

  [[ ${TR_TORRENT_NAME} && ${TR_TORRENT_DIR} ]] || {
    _query_tr_id data || die "Connection failed."
    IFS=/ read -r -d '' TR_TORRENT_NAME TR_TORRENT_DIR < <(
      printf '%s' "${data}" | jq -j '.arguments.torrents[]|"\(.name)/\(.downloadDir)\u0000"'
    ) && [[ ${TR_TORRENT_NAME} && ${TR_TORRENT_DIR} ]] ||
      die "Invalid torrent ID '${TR_TORRENT_ID}'. Run '${BASH_SOURCE[0]} -l' to show torrent list."
  }
  normpath src "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}"

  # decide the destination
  if [[ ${TR_TORRENT_DIR} -ef ${download_dir} ]]; then # source: download_dir
    # categorization
    logdir="$(
      if [[ ${data} ]]; then printf '%s' "${data}"; else _query_tr_id; fi |
        jq -j '.arguments.torrents[].files[]|"\(.name)\u0000\(.length)\u0000"' |
        awk "${categorizer[@]}"
    )"
    # fallback to default if failed
    normpath logdir "${locations[${logdir:-default}]:-${locations[default]}}"
    # if source is not a dir, append a sub-directory
    if [[ -d ${src} ]]; then
      dest="${logdir}"
    elif [[ ${TR_TORRENT_NAME} =~ (.*[^/.][^/]*)\.[^/.]*$ ]]; then # strip extension
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
  else # dest: download_dir
    logdir="${TR_TORRENT_DIR}"
    dest="${download_dir}"
  fi
  if ((use_rsync)); then data='Syncing'; else data='Copying'; fi
  printf '%s: "%s" -> "%s/"\n' "${data}" "${src}" "${dest}" 1>&2

  # copy file
  append_log 'Error' "${logdir}" "${TR_TORRENT_NAME}"
  if ((dryrun)) || _copy_to_dest; then
    unset 'logs[-1]'
    append_log 'Finish' "${logdir}" "${TR_TORRENT_NAME}"
    printf 'Done.\n' 1>&2
    return 0
  else
    printf 'Failed.\n' 1>&2
    return 1
  fi
}

# Query and parse API maindata.
# Globals: tr_maindata, tr_paused, tr_totalsize, tr_names
# torrent status code:
# https://github.com/transmission/transmission/blob/master/libtransmission/transmission.h#L1658
process_maindata() {
  local total name dir
  declare -Ag tr_names=()

  # save to `tr_maindata`
  request_rpc '{"arguments":{"fields":["activityDate","downloadDir","id","name","percentDone","sizeWhenDone","status"]},"method":"torrent-get"}' tr_maindata ||
    die 'Unable to connect to transmission API.'
  if [[ ${savejson} ]]; then
    printf '%s' "${tr_maindata}" | jq '.' >"${savejson}" &&
      printf 'Json data saved to: "%s"\n' "${savejson}" 1>&2
  fi

  {
    IFS=/ read -r -d '' total tr_paused tr_totalsize || die "Invalid json response."
    while IFS=/ read -r -d '' name dir; do
      [[ ${download_dir} == "${dir}" || ${download_dir} -ef ${dir} ]] && tr_names["${name}"]=1
    done
  } < <(printf '%s' "${tr_maindata}" | jq -j '
    if .result == "success" then
    .arguments.torrents|
    ("\(length)/\(map(select(.status == 0))|length)/\(map(.sizeWhenDone)|add + 0)\u0000"),
    (.[]|"\(.name)/\(.downloadDir)\u0000")
    else empty end')

  printf 'torrents: %d, paused: %d, size: %d GiB\n' "${total}" "${tr_paused}" "$((tr_totalsize / GiB))" 1>&2
}

# Clean junk files in `download_dir` and `watch_dir`, runs in a subshell.
clean_junk() {
  (
    shopt -s nullglob dotglob || exit 1
    arr=()

    if ((${#tr_names[@]})) && cd -- "${download_dir}"; then
      for i in *; do
        [[ ${tr_names["${i}"]} || ${tr_names["${i%.part}"]} ]] ||
          arr+=("${PWD:-${download_dir}}/${i}")
      done
    else
      printf 'Skip cleanup: "%s"\n' "${download_dir}" 1>&2
    fi
    if [[ ${watch_dir} == /?* ]]; then
      for i in "${watch_dir}/"*.torrent; do
        [[ -s ${i} ]] || arr+=("${i}")
      done
    fi

    if ((${#arr[@]})); then
      printf 'Cleanup: %s\n' "${arr[@]}" 1>&2
      ((dryrun)) || for ((i = 0; i < ${#arr[@]}; i += 100)); do
        rm -r -f -- "${arr[@]:i:100}"
      done
    fi
  )
}

# Remove inactive torrents to free up space.
remove_inactive() {
  local i m n target ids names

  case "${rm_strategy}" in
    'freespace')
      {
        read -r _
        # disksize, freespace
        read -r m n && isdigit "${m}" && isdigit "${n}"
      } < <(df --block-size=1 --output='size,avail' -- "${download_dir}") || {
        printf 'Reading disk stat failed.\n' 1>&2
        return 1
      }
      ((i = n / GiB, m = rm_thresh + tr_totalsize - m, n = rm_thresh - n, target = m > n ? m : n))
      m='free space'
      ;;
    'sizesum')
      ((i = rm_thresh / GiB, target = tr_totalsize - rm_thresh))
      m='quota'
      ;;
    *) die "Invalid rm_strategy '${rm_strategy}'." ;;
  esac

  if ((target > 0)); then
    printf '%s: %d GiB, will remove: %d GiB\n' "${m}" "${i}" "$((target / GiB))" 1>&2
  else
    printf '%s: %d GiB, availability: %d GiB. System is healthy.\n' "${m}" "${i}" "$((-target / GiB))" 1>&2
    return 0
  fi

  # id, size, name
  while IFS=/ read -r -d '' i m n; do
    [[ ${tr_names["${n}"]} ]] || continue
    ids+="${i},"
    names+=("${n}")
    (((target -= m) <= 0)) && break
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
      request_rpc "{\"arguments\":{\"ids\":[${ids%,}],\"delete-local-data\":true},\"method\":\"torrent-remove\"}" >/dev/null &&
      for n in "${names[@]}"; do
        append_log 'Remove' "${download_dir}" "${n}"
      done
  fi
}

# Restart paused torrents, if any.
resume_paused() {
  if ((tr_paused > 0)); then
    printf 'Resume torrents.\n' 1>&2
    ((dryrun)) || request_rpc '{"method":"torrent-start"}' >/dev/null
  fi
}

# Show transmission torrent list, tabular output.
show_tr_list() {
  local id size pct name arr w0=2 w1=4 gap=' '

  while IFS=/ read -r -d '' id size pct name; do
    printf -v size '%.1fG' "${size}"
    ((${#id} > w0)) && w0="${#id}"
    ((${#size} > w1)) && w1="${#size}"
    arr+=("${id}" "${size}" "${pct}" "${name//[[:cntrl:]]/ }")
  done < <(
    request_rpc '{"arguments":{"fields":["id","sizeWhenDone","percentDone","name"]},"method":"torrent-get"}' |
      jq -j --argjson g "${GiB}" '.arguments.torrents[]|"\(.id)/\(.sizeWhenDone/$g)/\(.percentDone*100)/\(.name)\u0000"'
  )
  ((${#arr[@]})) || exit 1

  printf "%${w0}s${gap}%${w1}s${gap}%5s${gap}%s\n" 'ID' 'SIZE' 'PCT' 'NAME'
  printf "%${w0}d${gap}${MAGENTA}%${w1}s${gap}%5.1f${gap}${YELLOW}%s${ENDCOLOR}\n" "${arr[@]}"
}

# Show torrent details, yaml output.
# $1: torrent ID
show_tr_info() {

  _format_read() {
    local fmt="${kfmt} ${YELLOW}${1}${ENDCOLOR}\n" k v
    shift
    for k; do
      IFS= read -r v || exit 1
      printf "${fmt}" "${k}" "${v}"
    done
  }

  ### begin ###
  local data jqprog files \
    kfmt="${MAGENTA}%s${ENDCOLOR}:" \
    strings=('name' 'downloadDir' 'hashString' 'id' 'status') \
    percents=('percentDone') \
    sizes=('totalSize' 'sizeWhenDone' 'downloadedEver' 'uploadedEver') \
    dates=('addedDate' 'activityDate')

  printf -v data '"%s",' "${strings[@]}" "${percents[@]}" "${sizes[@]}" "${dates[@]}" 'files'
  printf -v data '{"arguments":{"fields":[%s],"ids":%d},"method":"torrent-get"}' "${data%,}" "$1"
  jqprog=("${strings[@]}" "${percents[@]/%/'*100'}" "${sizes[@]/%/'/$g'}" "${dates[@]}")
  IFS=',' eval 'jqprog=".arguments.torrents[]|(${jqprog[*]/#/.}),(.files[]|.name,.length)|@json"'

  {
    _format_read '%s' "${strings[@]}"
    _format_read '%.2f%%' "${percents[@]}"
    _format_read '%.2f GiB' "${sizes[@]}"
    _format_read '%(%c)T' "${dates[@]}"
    mapfile -t files
  } < <(request_rpc "${data}" | jq -r --argjson g "${GiB}" "${jqprog}")
  ((${#files[@]})) || exit 1

  printf "${kfmt}\n" 'files'
  printf -- "- ${YELLOW}%s%.0s${ENDCOLOR}\n" "${files[@]}"

  data="$(printf '%s\n' "${files[@]}" | jq -j '"\(.)\u0000"' | awk "${categorizer[@]}")"
  printf "${kfmt} ${YELLOW}%s${ENDCOLOR}\n" 'category' "${data:-null}"
}

# Categorizer unit test, yaml output.
# $1: "all", "tr", "tv", "film" or any path
unit_test() {

  _test_tr() {
    local name files
    while IFS=/ read -r -d '' name files; do
      _examine_test "$(printf '%s' "${files}" | jq -j '.[]|"\(.name)\u0000\(.length)\u0000"' |
        awk "${categorizer[@]}")" "${name}"
    done < <(
      request_rpc '{"arguments":{"fields":["name","files"]},"method":"torrent-get"}' |
        jq -j '.arguments.torrents[]|"\(.name)/\(.files)\u0000"'
    )
  }

  _test_dir() {
    local name="$1" path="$2"
    _examine_test "$(
      if [[ ${path} ]] && { [[ ${PWD} == "${path}" ]] || cd -- "${path}" 1>/dev/null 2>&1; }; then
        find "${name}" -type f -printf '%p\0%s\0' -o -name '[#@]*' -prune
      else
        printf '%s\0' "${name}" 1
      fi | awk "${categorizer[@]}"
    )" "$@"
  }

  _examine_test() {
    local key="$1" name="$2" path="$3" dest err i fmt result

    case "${key}" in
      av) fmt="${YELLOW}" ;;
      film) fmt="${BLUE}" ;;
      tv) fmt="${CYAN}" ;;
      music) fmt="${GREEN}" ;;
      default) ;;
      '') err='runtime error' ;;
      *) err='invalid type' ;;
    esac
    if [[ -z ${err} ]]; then
      dest="${locations[${key}]}"
      [[ -z ${path} || ${path} -ef ${dest} ]] || err='different path'
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
    if ((empty)); then
      printf -- "${kfmt}\n" "results"
      empty=0
    fi
    fmt="${kfmt} ${fmt}%s${ENDCOLOR}\n"
    printf -- "- ${fmt}" "${result[@]::2}"
    printf -- "  ${fmt}" "${result[@]:2}"
  }

  ### begin ###
  local arg i kfmt="${MAGENTA}%s${ENDCOLOR}:" empty=1 error=()
  [[ $1 == 'all' ]] && set -- tr tv film

  for arg; do
    case "${arg}" in
      tr) _test_tr ;;
      tv | film)
        pushd -- "${locations[${arg}]}" 1>/dev/null 2>&1 ||
          die "Unable to enter: '${locations[${arg}]}'"
        shopt -s nullglob
        for i in [!\#@]*; do
          _test_dir "${i}" "${PWD}"
        done
        shopt -u nullglob
        popd 1>/dev/null 2>&1
        ;;
      ?*)
        if [[ -e ${arg} ]]; then
          _test_dir "$(basename "${arg}")" "$(dirname "${arg}")"
        else
          _test_dir "${arg}"
        fi
        ;;
    esac
  done

  if ((${#error[@]})); then
    printf -- "${kfmt}\n" 'errors'
    arg="${kfmt} ${RED}%s${ENDCOLOR}\n"
    for ((i = 0; i < ${#error[@]}; i += 10)); do
      printf -- "- ${arg}" "${error[@]:i:2}"
      printf -- "  ${arg}" "${error[@]:i+2:8}"
    done
    exit 1
  elif ((empty)); then
    exit 1
  fi
}

################################################################################
#                                     Main                                     #
################################################################################

# init variables
unset IFS rpc_url rpc_username rpc_password download_dir watch_dir rm_strategy \
  rm_thresh locations rpc_auth rpc_header logs dryrun savejson _opt _arg

# dependencies
hash curl jq || die 'Curl and jq required.'

# read config file
cd -- "${BASH_SOURCE[0]%/*}" || die 'Unable to enter script directory.'
source ./config || die 'Reading config file failed.'

# verify configurations
[[ ${rpc_url} == http* && ${download_dir} == /?* && ${locations['default']} == /?* && (\
${rm_strategy} == 'freespace' || ${rm_strategy} == 'sizesum') ]] && isdigit "${rm_thresh}" ||
  die 'Error in config file.'

# parse arguments
while getopts 'j:q:f:ls:dht:' i; do
  case "${i}" in
    h) print_help ;;
    d) dryrun=1 ;;
    [jt]) [[ ${OPTARG} ]] || arg_error 'empty argument' "${i}" ;;&
    [qfs]) isdigit "${OPTARG}" || arg_error 'requires a non-negative integer argument' "${i}" ;;&
    [flst]) [[ ${_opt} && ${_opt} != "${i}" ]] && arg_error 'mutually exclusive options' "${_opt}, ${i}" ;;&
    j) savejson="${OPTARG}" ;;
    q) rm_thresh="${OPTARG}" ;;
    f) _opt="${i}" TR_TORRENT_ID="${OPTARG}" ;;
    [lst]) _opt="${i}" _arg="${OPTARG}" ;;
    *) arg_error ;;
  esac
done
(($# >= OPTIND)) && arg_error 'unrecognized argument' "${@:OPTIND:1}"

# constants
normpath download_dir "${download_dir}"
[[ ${rpc_username} ]] && rpc_auth=(--anyauth --user "${rpc_username}${rpc_password:+:${rpc_password}}")
((GiB = 1073741824, rm_thresh *= GiB))
readonly -- rpc_url download_dir watch_dir rm_strategy rm_thresh locations \
  rpc_auth GiB dryrun savejson logfile="${PWD}/logfile.log" \
  categorizer=(-v regexfile="${PWD}/component/regex.txt" -f "${PWD}/component/categorizer.awk")

# begin
if [[ ${_opt} == [lst] ]]; then

  # stand-alone functions
  set_colors
  set_rpc_header || die 'Unable to connect to transmission API.'

  case "${_opt}" in
    l) show_tr_list ;;
    s) show_tr_info "${_arg}" ;;
    t) unit_test "${_arg}" ;;
  esac

else

  # acquire lock
  exec {i}<"./${BASH_SOURCE[0]##*/}"
  if [[ ${TR_TORRENT_ID} ]]; then
    flock -x "${i}"
  elif ! flock -x -n "${i}"; then
    die 'Unable to acquire lock, another instance running?'
  fi
  trap 'write_log' EXIT

  # copy finished download
  set_rpc_header
  copy_finished

  # maintenance
  process_maindata
  clean_junk
  remove_inactive
  resume_paused

fi
exit 0
