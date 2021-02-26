#!/usr/bin/env bash

################################################################################
#                                Configurations                                #
################################################################################

tr_api='http://localhost:9091/transmission/rpc'
seed_dir='/volume2/@transmission'
watch_dir='/volume1/video/Torrents'
logfile='transmission.log'
categorize='component/categorize.awk'
regexfile='component/regex.txt'
((GiB = 1024 ** 3, quota = 100 * GiB)) # Disk space quota: 100 GiB

#------------------------- That's all, stop editing! --------------------------#
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
  -s        save json to query.json
  -q NUM    set disk quota to NUM GiB (default: $((quota / GiB)))
EOF
  exit 1
}

init() {
  local i
  export LC_ALL=C LANG=C
  unset IFS tr_path tr_header tr_json tr_totalsize tr_paused logs
  declare -Ag tr_names
  dryrun=0 savejson=0

  while getopts 'hdsq:' i; do
    case "$i" in
      d) dryrun=1 ;;
      s) savejson=1 ;;
      q) [[ ${OPTARG} =~ ^[0-9]+$ ]] || print_help && ((quota = OPTARG * GiB)) ;;
      *) print_help ;;
    esac
  done

  [[ "${seed_dir}" && "${logfile}" && "${categorize}" && "${regexfile}" && "${tr_api}" && "${quota}" -ge 0 ]] || {
    printf '[DEBUG] Error: Invalid configuration values.\n' 1>&2
    exit 1
  }
  hash curl jq || printf '[DEBUG] Warning: This program requires curl and jq. Most functionality will be limited.\n' 1>&2

  cd "${BASH_SOURCE[0]%/*}" || exit 1
  printf '[DEBUG] Acquiring lock...' 1>&2
  exec {i}<"${BASH_SOURCE[0]##*/}"

  if [[ -n ${TR_TORRENT_DIR} && -n ${TR_TORRENT_NAME} ]]; then
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
  [[ -n "${tr_path}" ]] || return

  if [[ ${TR_TORRENT_DIR} == "${seed_dir}" ]]; then
    local i dest root
    for i in 'dest' 'root'; do
      IFS= read -r -d '' "$i"
    done < <(
      awk -v REGEX_FILE="${regexfile}" \
        -v TR_TORRENT_DIR="${TR_TORRENT_DIR}" \
        -v TR_TORRENT_NAME="${TR_TORRENT_NAME}" \
        -f "${categorize}"
    ) && {
      if [[ -d "${dest}" ]] || mkdir -p -- "${dest}" && cp -rf -- "${tr_path}" "${dest}/"; then
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
      printf '[DEBUG] Querying API failed. Retries: %s\n' "${i}" 1>&2
      get_tr_header
    else
      printf '[DEBUG] Querying API failed: "%s"\n' "$*" 1>&2
      return 1
    fi
  done
}

query_json() {
  local i result

  [[ -z "${tr_header}" ]] && get_tr_header
  tr_json="$(
    request_tr '{"arguments":{"fields":["activityDate","id","name","percentDone","sizeWhenDone","status","trackerStats"]},"method":"torrent-get"}'
  )" || exit 1
  if ((savejson)); then
    printf '[DEBUG] Save json to query.json\n' 1>&2
    printf '%s' "${tr_json}" | jq '.' >'query.json'
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
      "\([.arguments.torrents[]|select(.status<=0)]|length)\u0000",
      (.arguments.torrents[]|"\(.name)\u0000")'
  ) && [[ ${result} == 'success' ]] || {
    printf '[DEBUG] Parsing json failed. Content:\n%s\n' "${tr_json}" 1>&2
    exit 1
  }

  printf '[DEBUG] Total torrents: %d, size: %d GiB, paused: %d\n' \
    "${#tr_names[@]}" "$((tr_totalsize / GiB))" "${tr_paused}" 1>&2
  return 0
}

clean_disk() {
  local i obsolete
  shopt -s nullglob dotglob globstar

  if ((${#tr_names[@]})) && pushd "${seed_dir}" >'/dev/null'; then
    for i in [^.\#@]*; do
      if [[ -z "${tr_names[${i}]}" && -z "${tr_names[${i%.part}]}" ]]; then
        append_log 'Cleanup' "${seed_dir}" "${i}"
        obsolete+=("${seed_dir}/${i}")
      fi
    done
    unset tr_names
    popd >'/dev/null'
  else
    printf '[DEBUG] Skip cleaning seed_dir (%s)\n' "${seed_dir}" 1>&2
  fi

  if [[ -n "${watch_dir}" ]] && pushd "${watch_dir}" >'/dev/null'; then
    for i in **; do
      [[ -s ${i} ]] || obsolete+=("${watch_dir}/${i}")
    done
    popd >'/dev/null'
  else
    printf '[DEBUG] Skip cleaning watch_dir (%s)\n' "${watch_dir}" 1>&2
  fi

  if ((${#obsolete[@]})); then
    printf '[DEBUG] Delete %d files:\n' "${#obsolete[@]}" 1>&2
    printf '%s\n' "${obsolete[@]}" 1>&2
    ((dryrun)) || rm -rf -- "${obsolete[@]}"
  fi

  shopt -u nullglob dotglob globstar
}

remove_inactive() {
  local disksize freespace target m n id size name ids names

  {
    read _
    read -r 'disksize' 'freespace'
  } < <(df --block-size=1 --output='size,avail' -- "${seed_dir}") && [[ ${disksize} =~ ^[0-9]+$ && ${freespace} =~ ^[0-9]+$ ]] || {
    printf '[DEBUG] Reading disk stat failed.\n' 1>&2
    return 1
  }
  if ((m = quota - disksize + tr_totalsize, n = quota - freespace, (target = m > n ? m : n) > 0)); then
    printf '[DEBUG] Free space: %d GiB, Space to free: %d GiB.\n' \
      "$((freespace / GiB))" "$((target / GiB))" 1>&2
  else
    printf '[DEBUG] Free space: %d GiB. System is healthy.\n' "$((freespace / GiB))" 1>&2
    return 0
  fi

  while IFS='/' read -r -d '' id size name; do
    [[ "${id}" && "${size}" && "${name}" ]] || continue
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
      sort_by(([.trackerStats[].leecherCount]|add),.activityDate)[]|
      select(.percentDone==1)|
      "\(.id)/\(.sizeWhenDone)/\(.name)\u0000"'
  )
}

resume_paused() {
  if ((tr_paused > 0 && !dryrun)); then
    request_tr '{"method":"torrent-start"}' >'/dev/null'
  fi
}

append_log() {
  printf -v "logs[${#logs[@]}]" '%-20(%D %T)T%-10s%-35s%s' '-1' "$1" "${2:0:33}" "$3"
}

write_log() {
  if ((${#logs[@]})); then
    if ((dryrun)); then
      printf '[DEBUG] Logs (%d entries):\n' "${#logs[@]}" 1>&2
      printf '%s\n' "${logs[@]}" 1>&2
    else
      local i backup
      [[ -f "${logfile}" ]] && backup="$(tail -n +3 -- "${logfile}")"
      {
        printf '%-20s%-10s%-35s%s\n%s\n' \
          'Date' 'Status' 'Location' 'Name' \
          '--------------------------------------------------------------------------------'
        for ((i = ${#logs[@]} - 1; i >= 0; i--)); do
          printf '%s\n' "${logs[i]}"
        done
        [[ -n ${backup} ]] && printf '%s\n' "${backup}"
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
