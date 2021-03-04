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

[[ ${BASH_VERSINFO[0]} -ge 4 ]] 1>/dev/null 2>&1 || die 'Bash >=4 required.'
cd "${BASH_SOURCE[0]%/*}" || die 'Unable to enter script directory.'
source ./config || die "Reading config file failed."
hash curl jq || die 'Curl and jq required.'

readonly -- \
  logfile='logfile.log' \
  categorize='component/categorize.awk' \
  regexfile='component/regex.txt'

################################################################################
#                                  Functions                                   #
################################################################################

print_help() {
  cat <<EOF 1>&2
usage: ${BASH_SOURCE[0]} [OPTION]...

Transmission Maintenance Tool
Author: David Pi

optional arguments:
  -h        show this message and exit
  -d        dryrun mode
  -s FILE   save formated json to FILE
  -q NUM    set disk quota to NUM GiB (default: $((quota / GiB)))
EOF
  exit 1
}

# Normalize path, eliminating double slashes, etc.
# Usage: new_path="$(normpath "${old_path}")"
# Translated from Python's posixpath.normpath:
# https://github.com/python/cpython/blob/master/Lib/posixpath.py#L337
normpath() {
  if [[ -z $1 ]]; then
    printf '.\n'
    return 0
  fi
  local IFS=/ initial_slashes='' comp comps new_comps=()
  if [[ $1 == /* ]]; then
    initial_slashes='/'
    [[ $1 == //* && $1 != ///* ]] && initial_slashes='//'
  fi
  read -r -a comps <<<"$1"
  for comp in "${comps[@]}"; do
    [[ -z ${comp} || ${comp} == '.' ]] && continue
    if [[ ${comp} != '..' || (-z ${initial_slashes} && ${#new_comps[@]} -eq 0) || (\
      ${#new_comps[@]} -gt 0 && ${new_comps[-1]} == '..') ]]; then
      new_comps+=("${comp}")
    elif ((${#new_comps[@]})); then
      unset 'new_comps[-1]'
    fi
  done
  comp="${initial_slashes}${new_comps[*]}"
  printf -- '%s\n' "${comp:-.}"
  return 0
}

init() {
  local i
  # varify configurations
  [[ ${seed_dir} == /* && ${locations['default']} == /* && ${tr_api} == http* && ${quota} -ge 0 ]] ||
    die 'Invalid configuration.'
  seed_dir="$(normpath "${seed_dir}")"

  # parse arguments
  dryrun=0 savejson=''
  while getopts 'hds:q:' i; do
    case "$i" in
      d) dryrun=1 ;;
      s) [[ ${OPTARG} ]] || die 'Empty json filename.' && savejson="${OPTARG}" ;;
      q) [[ ${OPTARG} =~ ^[0-9]+$ ]] || die 'QUOTA must be integer >= 0.' && ((quota = OPTARG * GiB)) ;;
      *) print_help ;;
    esac
  done

  # variables & constants
  tr_header='' tr_json='' tr_totalsize='' tr_paused='' logs=()
  declare -Ag tr_names=()
  readonly -- tr_api seed_dir watch_dir GiB quota locations dryrun savejson

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

  if [[ ${TR_TORRENT_DIR} == "${seed_dir}" ]]; then
    # fallback to default if the result is blank
    root="${locations[$(
      awk -v TR_TORRENT_DIR="${TR_TORRENT_DIR}" \
        -v TR_TORRENT_NAME="${TR_TORRENT_NAME}" \
        -v regexfile="${regexfile}" \
        -f "${categorize}"
    )]:-${locations['default']}}"
    # normalize the path
    root="$(normpath "${root}")"
    # append a sub-directory if needed
    if [[ -d ${tr_path} ]]; then
      dest="${root}"
    elif [[ ${TR_TORRENT_NAME} =~ ^(.+)\.[^./]+$ ]]; then
      dest="${root}/${BASH_REMATCH[1]}"
    else
      dest="${root}/${TR_TORRENT_NAME}"
    fi

    if [[ -e ${dest} ]] || mkdir -p -- "${dest}" &&
      cp -r -f -- "${tr_path}" "${dest}/"; then
      append_log 'Finish' "${root}" "${TR_TORRENT_NAME}"
      return 0
    fi
  elif cp -r -f -- "${tr_path}" "${seed_dir}/" &&
    get_tr_header &&
    request_tr "{\"arguments\":{\"ids\":[${TR_TORRENT_ID}],\"location\":\"${seed_dir}/\"},\"method\":\"torrent-set-location\"}" >/dev/null; then
    append_log 'Finish' "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    return 0
  fi

  append_log 'Error' "${root:-${TR_TORRENT_DIR}}" "${TR_TORRENT_NAME}"
  return 1
}

get_tr_header() {
  if [[ "$(curl -s -I -- "${tr_api}")" =~ X-Transmission-Session-Id:[[:blank:]]*[[:alnum:]]+ ]]; then
    tr_header="${BASH_REMATCH[0]}"
    printf 'API header: "%s"\n' "${tr_header}" 1>&2
    return 0
  fi
  return 1
}

# Send an API request.
# Arguments: $1: data to send
request_tr() {
  local i
  for i in {1..4}; do
    if curl -s -f --header "${tr_header}" -d "$1" -- "${tr_api}"; then
      printf 'Querying API success: "%s"\n' "$1" 1>&2
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
    request_tr '{"arguments":{"fields":["activityDate","downloadDir","id","name","percentDone","sizeWhenDone","status","trackerStats"]},"method":"torrent-get"}'
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
    printf '%s' "${tr_json}" | jq --arg d "${seed_dir}" -j '
      "\(.result)\u0000",
      "\(.arguments.torrents|map(select(.status == 0))|length)\u0000",
      (.arguments.torrents|map(select(.downloadDir == $d))|
      "\([.[].sizeWhenDone]|add)\u0000", "\(.[].name)\u0000")'
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
        obsolete+=("${PWD}/${i}")
    done
  else
    printf 'Skip cleaning seed_dir "%s"\n' "${seed_dir}" 1>&2
  fi

  if [[ ${watch_dir} ]] && cd "${watch_dir}"; then
    for i in **; do
      [[ -s ${i} ]] || obsolete+=("${PWD}/${i}")
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
    printf '%s' "${tr_json}" | jq --arg d "${seed_dir}" -j '
      .arguments.torrents|
      map(select(.downloadDir == $d and .percentDone == 1))|
      sort_by(.activityDate, ([.trackerStats[].leecherCount]|add))[]|      
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
  if ((tr_paused > 0 && !dryrun)); then
    request_tr '{"method":"torrent-start"}' >/dev/null
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
  printf -v "logs[${#logs[@]}]" '%(%D %T)T    %-6s    %-30s    %s\n' '-1' "$1" "$loc" "$3"
}

# Print logs in reversed order.
print_log() {
  local i
  printf '%-17s    %-6s    %-30s    %s\n%s\n' \
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
