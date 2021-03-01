#!/usr/bin/env bash

################################################################################
#                                Configurations                                #
################################################################################

# Transmission rpc-url with authentication disabled.
tr_api='http://localhost:9091/transmission/rpc'

# Directory storing files for seeding, without trailing slash.
seed_dir='/volume2/@transmission'

# Directory where transmission monitors for new torrents, set an empty value to
# disable watch_dir cleanup.
watch_dir='/volume1/video/Torrents'

# Disk space quota (minimum free space on disk)
((GiB = 1024 ** 3, quota = 100 * GiB))

# ------------------------ That's all, stop editing! ------------------------- #

logfile='transmission.log'
categorize='component/categorize.awk'
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

init() {
  unset IFS
  export LC_ALL=C LANG=C
  local i
  declare -Ag tr_names
  tr_path= tr_header= tr_json= tr_totalsize= tr_paused= savejson= logs=()
  dryrun=0

  [[ ${tr_api} == http* && ${seed_dir} == /*[^/] && ${quota} -ge 0 ]] || {
    printf '[DEBUG] Error: Invalid configurations.\n' 1>&2
    exit 1
  }
  hash curl jq || {
    printf '[DEBUG] Error: This program requires curl and jq executables.\n' 1>&2
    exit 1
  }
  while getopts 'hds:q:' i; do
    case "$i" in
      d) dryrun=1 ;;
      s) [[ ${OPTARG} ]] || print_help && savejson="${OPTARG}" ;;
      q) [[ ${OPTARG} =~ ^[0-9]+$ ]] || print_help && ((quota = OPTARG * GiB)) ;;
      *) print_help ;;
    esac
  done

  cd "${BASH_SOURCE[0]%/*}" || exit 1
  printf '[DEBUG] Acquiring lock...' 1>&2
  exec {i}<"${BASH_SOURCE[0]##*/}"

  if [[ ${TR_TORRENT_DIR} && ${TR_TORRENT_NAME} ]]; then
    flock -x "$i"
    tr_path="${TR_TORRENT_DIR}/${TR_TORRENT_NAME}"
  elif ! flock -xn "$i"; then
    printf 'Failed.\n' 1>&2
    exit 1
  fi

  printf 'Done.\n' 1>&2
  trap 'write_log' EXIT
}

copy_finished() {
  [[ ${tr_path} ]] || return

  if [[ ${TR_TORRENT_DIR} == "${seed_dir}" ]]; then
    local i root path
    for i in 'root' 'path'; do
      IFS= read -r -d '' "$i"
    done < <(
      awk -v REGEX_FILE="${regexfile}" \
        -v TR_TORRENT_DIR="${TR_TORRENT_DIR}" \
        -v TR_TORRENT_NAME="${TR_TORRENT_NAME}" \
        -f "${categorize}"
    ) && {
      if [[ -d ${path} ]] || mkdir -p -- "${path}" && cp -rf -- "${tr_path}" "${path}/"; then
        append_log 'Finish' "${root}" "${TR_TORRENT_NAME}"
        return 0
      fi
    }
  elif cp -rf -- "${tr_path}" "${seed_dir}/" && get_tr_header &&
    request_tr "{\"arguments\":{\"ids\":[${TR_TORRENT_ID}],\"location\":\"${seed_dir}/\"},\"method\":\"torrent-set-location\"}" >'/dev/null'; then
    append_log 'Finish' "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    return 0
  fi

  append_log 'Error' "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
  return 1
}

get_tr_header() {
  if [[ "$(curl -sI -- "${tr_api}")" =~ X-Transmission-Session-Id:[[:space:]]*[A-Za-z0-9]+ ]]; then
    tr_header="${BASH_REMATCH[0]}"
    printf '[DEBUG] API header: "%s"\n' "${tr_header}" 1>&2
  fi
}

request_tr() {
  local i
  for i in {1..4}; do
    if curl -sf --header "${tr_header}" -d "$@" -- "${tr_api}"; then
      printf '[DEBUG] Querying API success: "%s"\n' "$*" 1>&2
      return 0
    elif ((i < 4)); then
      printf '[DEBUG] Querying API failed. Retries: %d\n' "${i}" 1>&2
      get_tr_header
    else
      printf '[DEBUG] Querying API failed: "%s"\n' "$*" 1>&2
      return 1
    fi
  done
}

query_json() {
  # transmission status number:
  # https://github.com/transmission/transmission/blob/master/libtransmission/transmission.h#L1658

  local i result

  [[ ${tr_header} ]] || get_tr_header
  tr_json="$(
    request_tr '{"arguments":{"fields":["activityDate","id","name","percentDone","sizeWhenDone","status","trackerStats"]},"method":"torrent-get"}'
  )" || exit 1
  if [[ ${savejson} ]]; then
    printf '[DEBUG] Save json to %s\n' "${savejson}" 1>&2
    printf '%s' "${tr_json}" | jq '.' >"${savejson}"
  fi
  {
    for i in 'result' 'tr_totalsize' 'tr_paused'; do
      read -r -d '' "$i"
    done
    while IFS= read -r -d '' i; do
      tr_names["${i}"]=1
    done
  } < <(
    printf '%s' "${tr_json}" | jq -j '
      "\(.result)\u0000",
      "\([.arguments.torrents[].sizeWhenDone]|add)\u0000",
      "\([.arguments.torrents[]|select(.status == 0)]|length)\u0000",
      "\(.arguments.torrents[].name)\u0000"'
  ) && [[ ${result} == 'success' ]] || {
    printf '[DEBUG] Parsing json failed. Status: "%s"\n' "${result}" 1>&2
    exit 1
  }
  printf '[DEBUG] Torrents: %d, size: %d GiB, paused: %d\n' \
    "${#tr_names[@]}" "$((tr_totalsize / GiB))" "${tr_paused}" 1>&2
  return 0
}

clean_disk() (
  # this function runs in a subshell

  shopt -s nullglob dotglob globstar
  obsolete=()

  if ((${#tr_names[@]})) && cd "${seed_dir}"; then
    for i in [^.\#@]*; do
      [[ ${tr_names[${i}]} || ${tr_names[${i%.part}]} ]] || obsolete+=("${seed_dir}/${i}")
    done
  else
    printf '[DEBUG] Skip cleaning seed_dir (%s)\n' "${seed_dir}" 1>&2
  fi
  if [[ ${watch_dir} ]] && cd "${watch_dir}"; then
    for i in **; do
      [[ -s ${i} ]] || obsolete+=("${watch_dir}/${i}")
    done
  else
    printf '[DEBUG] Skip cleaning watch_dir (%s)\n' "${watch_dir}" 1>&2
  fi
  if ((${#obsolete[@]})); then
    printf '[DEBUG] Delete %d files:\n' "${#obsolete[@]}" 1>&2
    printf '%s\n' "${obsolete[@]}" 1>&2
    ((dryrun)) || rm -rf -- "${obsolete[@]}"
  fi
)

remove_inactive() {
  local disksize freespace target m n id size name ids names

  {
    read _
    read -r 'disksize' 'freespace'
  } < <(df --block-size=1 --output='size,avail' -- "${seed_dir}") && [[ ${disksize} =~ ^[0-9]+$ && ${freespace} =~ ^[0-9]+$ ]] || {
    printf '[DEBUG] Reading disk stat failed.\n' 1>&2
    return 1
  }

  if ((m = quota + tr_totalsize - disksize, n = quota - freespace, (target = m > n ? m : n) > 0)); then
    printf '[DEBUG] Free space: %d GiB, free up: %d GiB\n' \
      "$((freespace / GiB))" "$((target / GiB))" 1>&2
  else
    printf '[DEBUG] Free space: %d GiB, avail space: %d GiB. System is healthy.\n' \
      "$((freespace / GiB))" "$((-target / GiB))" 1>&2
    return 0
  fi

  while IFS='/' read -r -d '' id size name; do
    [[ ${name} ]] || continue
    ids+="${id},"
    names+=("${name}")
    if (((target -= size) <= 0)); then
      printf '[DEBUG] Remove %d torrents.\n' "${#names[@]}" 1>&2
      ((dryrun)) || {
        request_tr "{\"arguments\":{\"ids\":[${ids%,}],\"delete-local-data\":true},\"method\":\"torrent-remove\"}" >'/dev/null'
      } && {
        for name in "${names[@]}"; do
          append_log 'Remove' "${seed_dir}" "${name}"
        done
      }
      break
    fi
  done < <(
    printf '%s' "${tr_json}" | jq -j '
      .arguments.torrents|
      sort_by(.activityDate, ([.trackerStats[].leecherCount]|add))[]|
      select(.percentDone == 1)|
      "\(.id)/\(.sizeWhenDone)/\(.name)\u0000"'
  )
}

resume_paused() {
  if ((tr_paused > 0 && !dryrun)); then
    request_tr '{"method":"torrent-start"}' >'/dev/null'
  fi
}

append_log() {
  #  0: mm/dd/yy hh:mm:ss     (17)
  # $1: Finish/Remove/Error   (6)
  # $2: location              (30)
  # $3: name
  local loc
  if ((${#2} <= 30)); then loc="$2"; else loc="${2::27}..."; fi
  printf -v "logs[${#logs[@]}]" '%(%D %T)T    %-6s    %-30s    %s\n' '-1' "$1" "$loc" "$3"
}

print_log() {
  local i
  printf '%-17s    %-6s    %-30s    %s\n%s\n' \
    'Date' 'Status' 'Location' 'Name' \
    '--------------------------------------------------------------------------------'
  for ((i = ${#logs[@]} - 1; i >= 0; i--)); do
    printf '%s' "${logs[i]}"
  done
}

write_log() {
  if ((${#logs[@]})); then
    if ((dryrun)); then
      printf '[DEBUG] Logs (%d entries):\n' "${#logs[@]}" 1>&2
      print_log 1>&2
    else
      local backup
      [[ -f "${logfile}" ]] && backup="$(tail -n +3 -- "${logfile}")"
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
