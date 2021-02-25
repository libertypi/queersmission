#!/usr/bin/env bash

export LC_ALL=C LANG=C

################################################################################
#                                Configurations                                #
################################################################################

seed_dir='/volume2/@transmission'
watch_dir='/volume1/video/Torrents'
log_file='transmission.log'
categorize='component/categorize.awk'
regex_file='component/regex.txt'
tr_api='http://localhost:9091/transmission/rpc'
((quota = 100 * 1024 ** 3)) # Disk space quota: 100 GiB

################################################################################
#                                  Functions                                   #
################################################################################

init() {
  local i
  debug=0
  unset 'torrent_path' 'tr_header' 'tr_json' 'logs'

  while getopts dh i; do
    if [[ $i == "d" ]]; then
      debug=1
    else
      printf '%s\n' "options:" "  -d  debug" "  -h  help" 1>&2
      exit 1
    fi
  done

  printf '[DEBUG] %s' "Acquiring lock..." 1>&2
  cd "${BASH_SOURCE[0]%/*}" || exit 1
  exec {i}<"${BASH_SOURCE[0]##*/}"

  if [[ -n ${TR_TORRENT_DIR} && -n ${TR_TORRENT_NAME} ]]; then
    flock -x "$i"
    torrent_path="${TR_TORRENT_DIR}/${TR_TORRENT_NAME}"
  elif ! flock -xn "$i"; then
    printf '%s\n' 'Failed.' 1>&2
    exit 1
  fi

  printf '%s\n' 'Done.' 1>&2
  trap 'write_log' EXIT
}

copy_finished() {
  [[ -z "${torrent_path}" ]] && return

  if [[ ${TR_TORRENT_DIR} == "${seed_dir}" ]]; then
    local i dest root
    for i in dest root; do
      IFS= read -r -d '' "$i"
    done < <(
      awk -v REGEX_FILE="${regex_file}" \
        -v TR_TORRENT_DIR="${TR_TORRENT_DIR}" \
        -v TR_TORRENT_NAME="${TR_TORRENT_NAME}" \
        -f "${categorize}"
    ) && {
      if [[ -d "${dest}" ]] || mkdir -p "${dest}" && cp -rf "${torrent_path}" "${dest}/"; then
        append_log "Finish" "${root}" "${TR_TORRENT_NAME}"
        return 0
      fi
    }
  elif cp -rf "${torrent_path}" "${seed_dir}/" && get_tr_header &&
    request_tr "{\"arguments\":{\"ids\":[${TR_TORRENT_ID}],\"location\":\"${seed_dir}/\"},\"method\":\"torrent-set-location\"}"; then
    append_log "Finish" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    return 0
  fi

  append_log "Error" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
  return 1
}

get_tr_header() {
  if [[ "$(curl -sI "${tr_api}")" =~ X-Transmission-Session-Id:[[:space:]]*[A-Za-z0-9]+ ]]; then
    tr_header="${BASH_REMATCH[0]}"
    printf '[DEBUG] API Header: "%s"\n' "${tr_header}" 1>&2
  fi
}

request_tr() {
  local i
  for i in {1..4}; do
    if curl -sf --header "${tr_header}" "${tr_api}" -d "$@"; then
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

query_torrent() {
  local result
  if ! hash jq 1>/dev/null 2>&1; then
    printf '[DEBUG] %s\n' "Jq not found, will not proceed." 1>&2
    exit 1
  fi
  [[ -z "${tr_header}" ]] && get_tr_header
  if tr_json="$(request_tr '{"arguments":{"fields":["activityDate","id","name","percentDone","sizeWhenDone","status","trackerStats"]},"method":"torrent-get"}')" &&
    IFS='/' read -r result totalTorrentSize errorTorrents < <(jq -r '"\(.result)/\([.arguments.torrents[].sizeWhenDone]|add)/\([.arguments.torrents[]|select(.status<=0)]|length)"' <<<"${tr_json}") &&
    [[ ${result} == 'success' ]]; then

    printf '[DEBUG] Getting torrents info success, total size: %d GiB, stopped torrents: %d.\n' "$((totalTorrentSize / 1024 ** 3))" "${errorTorrents}" 1>&2
    # ((debug)) && jq '.' <<<"${tr_json}" >'debug.json'
    return 0
  else
    printf '[DEBUG] Getting torrents info failed. Response: "%s"\n' "${tr_json}" 1>&2
    exit 1
  fi
}

clean_disk() {
  local obsolete i
  shopt -s nullglob dotglob globstar

  if pushd "${seed_dir}" >/dev/null; then
    declare -A names
    while IFS= read -r -d '' i; do
      names["${i}"]=1
    done < <(
      jq -j '.arguments.torrents[]|"\(.name)\u0000"' <<<"${tr_json}"
    ) && {
      for i in [^.\#@]*; do
        if [[ -z "${names[${i}]}" && -z "${names[${i%.part}]}" ]]; then
          append_log 'Cleanup' "${seed_dir}" "${i}"
          obsolete+=("${seed_dir}/${i}")
        fi
      done
    }
    popd >/dev/null
  else
    printf '[DEBUG] Unable to enter: %s\n' "${seed_dir}" 1>&2
  fi

  if pushd "${watch_dir}" >/dev/null; then
    for i in **; do
      [[ -s ${i} ]] || obsolete+=("${watch_dir}/${i}")
    done
    popd >/dev/null
  else
    printf '[DEBUG] Unable to enter: %s\n' "${watch_dir}" 1>&2
  fi

  if ((${#obsolete[@]})); then
    printf '[DEBUG] %s\n' 'Cleanup redundant files:' "${obsolete[@]}" 1>&2
    ((debug)) || rm -rf -- "${obsolete[@]}"
  fi

  shopt -u nullglob dotglob globstar
}

remove_inactive() {
  local diskSize freeSpace target m n id size name ids names

  {
    read _
    read -r diskSize freeSpace
  } < <(df --block-size=1 --output=size,avail "${seed_dir}") && [[ ${diskSize} =~ ^[0-9]+$ && ${freeSpace} =~ ^[0-9]+$ ]] || {
    printf '[DEBUG] %s\n' 'Reading disk stats failed.' 1>&2
    return
  }

  if ((m = quota - diskSize + totalTorrentSize, n = quota - freeSpace, (target = m > n ? m : n) > 0)); then
    printf '[DEBUG] Disk free space: %d GiB, Space to free: %d GiB. Cleanup inactive feeds.\n' "$((freeSpace / 1024 ** 3))" "$((target / 1024 ** 3))" 1>&2
  else
    printf '[DEBUG] Disk free space: %d GiB. Skip action.\n' "$((freeSpace / 1024 ** 3))" 1>&2
    return
  fi

  while IFS='/' read -r -d '' id size name; do
    [[ -z ${name} ]] && continue
    ids+="${id},"
    names+=("${name}")

    if (((target -= size) <= 0)); then
      printf '[DEBUG] %s\n' 'Remove torrents:' "${names[@]}" 1>&2
      ((debug)) || {
        request_tr "{\"arguments\":{\"ids\":[${ids%,}],\"delete-local-data\":true},\"method\":\"torrent-remove\"}" >/dev/null
      } && {
        for name in "${names[@]}"; do
          append_log "Remove" "${seed_dir}" "${name}"
        done
      }
      break
    fi
  done < <(
    jq -j '.arguments.torrents|sort_by(([.trackerStats[].leecherCount]|add),.activityDate)[]|select(.percentDone==1)|"\(.id)/\(.sizeWhenDone)/\(.name)\u0000"' <<<"${tr_json}"
  )
}

resume_paused() {
  if ((errorTorrents > 0)); then
    request_tr '{"method":"torrent-start"}' >/dev/null
  fi
}

append_log() {
  printf -v "logs[${#logs[@]}]" '%-20(%D %T)T%-10s%-35s%s' '-1' "$1" "${2:0:33}" "$3"
}

write_log() {
  if ((${#logs[@]})); then
    if ((debug)); then
      printf '[DEBUG] Logs: (%s entries)\n' "${#logs[@]}" 1>&2
      printf '%s\n' "${logs[@]}" 1>&2
    else
      local i logBackup
      [[ -f ${log_file} ]] && logBackup="$(tail -n +3 "${log_file}")"
      {
        printf '%-20s%-10s%-35s%s\n%s\n' \
          'Date' 'Status' 'Location' 'Name' \
          '--------------------------------------------------------------------------------'
        for ((i = ${#logs[@]} - 1; i >= 0; i--)); do
          printf '%s\n' "${logs[i]}"
        done
        [[ -n ${logBackup} ]] && printf '%s\n' "${logBackup}"
      } >"${log_file}"
    fi
  fi
}

################################################################################
#                                     Main                                     #
################################################################################

init "$@"
copy_finished

query_torrent
clean_disk
remove_inactive

resume_paused
exit 0
