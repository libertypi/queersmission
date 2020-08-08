#!/usr/bin/env bash

export LC_ALL=C LANG=C

seed_dir='/volume2/@transmission'
watch_dir='/volume1/video/Torrents'
log_file='transmission.log'
categorize='component/categorize.awk'
av_regex='component/av_regex.txt'
tr_api='http://localhost:9091/transmission/rpc'

prepare() {
  printf '[DEBUG] %s' "Acquiring lock..." 1>&2
  cd "${BASH_SOURCE[0]%/*}" || exit 1
  exec {i}<"${BASH_SOURCE[0]##*/}"
  if [[ -n ${TR_TORRENT_DIR} && -n ${TR_TORRENT_NAME} ]]; then
    flock -x "${i}"
    trDoneScript=1
  else
    flock -xn "${i}" || {
      printf '%s\n' 'Failed.' 1>&2
      exit 1
    }
    trDoneScript=0
  fi
  printf '%s\n' 'Done.' 1>&2
  trap 'write_log' EXIT
}

handle_torrent_done() {
  ((trDoneScript == 1)) || return
  [[ -e "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" ]] || {
    append_log "Missing" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    return
  }

  if [[ ${TR_TORRENT_DIR} == "${seed_dir}" ]]; then

    local dest dest_display

    for i in dest dest_display; do
      IFS= read -r -d '' "$i"
    done < <(
      awk -v av_regex="${av_regex}" -v torrentDir="${TR_TORRENT_DIR}" -v torrentName="${TR_TORRENT_NAME}" -f "${categorize}"
    )

    if [[ -d ${dest} ]] || mkdir -p "${dest}" && cp -rf "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" "${dest}/"; then
      append_log "Finish" "${dest_display}" "${TR_TORRENT_NAME}"
    else
      append_log "Error" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    fi

  else

    if cp -rf "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" "${seed_dir}/" &&
      query_tr_api "{\"arguments\":{\"ids\":[${TR_TORRENT_ID}],\"location\":\"${seed_dir}/\"},\"method\":\"torrent-set-location\"}"; then
      append_log "Finish" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    else
      append_log "Error" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    fi

  fi
}

get_tr_session_header() {
  if [[ "$(curl -sI "${tr_api}")" =~ 'X-Transmission-Session-Id:'[[:space:]]*[A-Za-z0-9]+ ]]; then
    tr_session_header="${BASH_REMATCH[0]}"
    printf '[DEBUG] API Header: "%s"\n' "${tr_session_header}" 1>&2
  fi
}

query_tr_api() {
  [[ -z ${tr_session_header} ]] && get_tr_session_header
  for i in {1..4}; do
    if curl -sf --header "${tr_session_header}" "${tr_api}" -d "$@"; then
      printf '[DEBUG] Querying API success: "%s"\n' "$*" 1>&2
      return 0
    elif ((i < 4)); then
      printf '[DEBUG] Querying API failed. Retries: %s\n' "${i}" 1>&2
      get_tr_session_header
    else
      printf '[DEBUG] Querying API failed: "%s"\n' "$*" 1>&2
      return 1
    fi
  done
}

get_tr_info() {
  if ! hash jq 1>/dev/null 2>&1; then
    printf '[DEBUG] %s\n' "Jq not found, will not proceed." 1>&2
    exit 1
  fi
  [[ -z ${tr_session_header} ]] && get_tr_session_header
  local result
  if tr_json="$(query_tr_api '{"arguments":{"fields":["activityDate","status","sizeWhenDone","percentDone","trackerStats","id","name"]},"method":"torrent-get"}')" &&
    IFS='/' read -r result totalTorrentSize errorTorrents < <(jq -r '"\(.result)/\([.arguments.torrents[].sizeWhenDone]|add)/\([.arguments.torrents[]|select(.status<4)]|length)"' <<<"${tr_json}") &&
    [[ ${result} == 'success' ]]; then
    printf '[DEBUG] Getting torrents info success, total size: %d GiB, error torrents: %d.\n' "$((totalTorrentSize / 1024 ** 3))" "${errorTorrents}" 1>&2
    return 0
  else
    printf '[DEBUG] Getting torrents info failed. Response: "%s"\n"' "${tr_json}" 1>&2
    exit 1
  fi
}

clean_local_disk() {
  local obsolete
  shopt -s nullglob dotglob globstar

  if pushd "${seed_dir}" >/dev/null; then
    declare -A dict
    while IFS= read -r -d '' i; do
      dict["${i}"]=1
    done < <(jq -j '.arguments.torrents[]|"\(.name)\u0000"' <<<"${tr_json}")

    for i in [^.\#@]*; do
      [[ -n ${dict["${i}"]} ]] || {
        append_log 'Cleanup' "${seed_dir}" "${i}"
        obsolete+=("${seed_dir}/${i}")
      }
    done
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

  if ((${#obsolete[@]} > 0)); then
    printf '[DEBUG] %s\n' 'Cleanup redundant files:' "${obsolete[@]}" 1>&2
    ((debug == 0)) && rm -rf -- "${obsolete[@]}"
  fi

  shopt -u nullglob dotglob globstar
}

clean_inactive_feed() {
  local diskSize freeSpace quota target m n id size name ids names

  for _ in 1 2; do
    read -r diskSize freeSpace
  done < <(df --block-size=1 --output=size,avail "${seed_dir}") && [[ ${diskSize} =~ ^[0-9]+$ && ${freeSpace} =~ ^[0-9]+$ ]] || {
    printf '[DEBUG] %s\n' 'Reading disk stats failed.' 1>&2
    return
  }

  if ((quota = 50 * (1024 ** 3), m = quota - diskSize + totalTorrentSize, n = quota - freeSpace, (target = m > n ? m : n) > 0)); then
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
      ((debug == 1)) || {
        query_tr_api "{\"arguments\":{\"ids\":[${ids%,}],\"delete-local-data\":true},\"method\":\"torrent-remove\"}" >/dev/null
      } && {
        for name in "${names[@]}"; do
          append_log "Remove" "${seed_dir}" "${name}"
        done
      }
      break
    fi
  done < <(jq -j '.arguments.torrents|sort_by(([.trackerStats[].leecherCount]|add),.activityDate)[]|select(.percentDone==1)|"\(.id)/\(.sizeWhenDone)/\(.name)\u0000"' <<<"${tr_json}")
}

resume_tr_torrent() {
  if ((errorTorrents > 0)); then
    query_tr_api '{"method":"torrent-start"}' >/dev/null
  fi
}

append_log() {
  printf -v "logs[${#logs[@]}]" '%-20(%D %T)T%-10s%-35s%s' '-1' "$1" "${2:0:33}" "$3"
}

write_log() {
  if ((${#logs[@]} > 0)); then
    if ((debug == 0)); then
      local logBackup
      [[ -s ${log_file} ]] && logBackup="$(tail -n +3 "${log_file}")"
      {
        printf '%-20s%-10s%-35s%s\n%s\n' \
          'Date' 'Status' 'Destination' 'Name' \
          '-------------------------------------------------------------------------------'
        for ((i = ${#logs[@]} - 1; i >= 0; i--)); do
          printf '%s\n' "${logs[i]}"
        done
        [[ -n ${logBackup} ]] && printf '%s\n' "${logBackup}"
      } >"${log_file}"
    else
      printf '[DEBUG] Logs: (%s entries)\n' "${#logs[@]}" 1>&2
      printf '%s\n' "${logs[@]}" 1>&2
    fi
  fi
}

# Main
case "$1" in
  'debug' | '-d' | '-debug') readonly debug=1 ;;
  *) readonly debug=0 ;;
esac

prepare
handle_torrent_done

get_tr_info
clean_local_disk
clean_inactive_feed

resume_tr_torrent
exit 0
