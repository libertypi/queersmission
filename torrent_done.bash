#!/usr/bin/env bash

export LC_ALL=C LANG=C

seed_dir='/volume2/@transmission'
watch_dir='/volume1/video/Torrents'
log_file="transmission.log"
categorize="component/categorize.awk"
av_regex="component/av_regex.txt"
tr_api='http://localhost:9091/transmission/rpc'

case "$1" in
  'debug' | '-d' | '-debug') readonly debug=1 ;;
  *) readonly debug=0 ;;
esac
cd "${BASH_SOURCE[0]%/*}" || exit 1

prepare() {
  printf '[DEBUG] %s' "Acquiring lock..." 1>&2
  exec {i}<"${BASH_SOURCE[0]##*/}"
  flock -x "${i}"
  printf '%s\n' 'Done.' 1>&2
  trap 'write_log' EXIT
}

append_log() {
  printf -v "logs[${#logs[@]}]" '%-20(%D %T)T%-10s%-35s%s' '-1' "$1" "${2:0:33}" "$3"
}

write_log() {
  if ((${#logs[@]} > 0)); then
    if ((debug == 0)); then
      local log_bak
      [[ -s ${log_file} ]] && log_bak="$(tail -n +3 "${log_file}")"
      {
        printf '%-20s%-10s%-35s%s\n%s\n' \
          'Date' 'Status' 'Destination' 'Name' \
          '-------------------------------------------------------------------------------'
        for ((i = ${#logs[@]} - 1; i >= 0; i--)); do
          printf '%s\n' "${logs[i]}"
        done
        [[ -n ${log_bak} ]] && printf '%s\n' "${log_bak}"
      } >"${log_file}"
    else
      printf '[DEBUG] Logs: (%s entries)\n' "${#logs[@]}" 1>&2
      printf '%s\n' "${logs[@]}" 1>&2
    fi
  fi
}

get_tr_api_header() {
  if [[ "$(curl -sI "${tr_api}")" =~ 'X-Transmission-Session-Id:'[[:space:]]*[A-Za-z0-9]+ ]]; then
    tr_session_header="${BASH_REMATCH[0]}"
    printf '[DEBUG] API Header: "%s"\n' "${tr_session_header}" 1>&2
  fi
}

query_tr_api() {
  for i in {1..4}; do
    if curl -sf --header "${tr_session_header}" "${tr_api}" -d "$@"; then
      printf '[DEBUG] Querying API success. Query: "%s"\n' "$*" 1>&2
      return 0
    elif ((i < 4)); then
      printf '[DEBUG] Querying API failed. Retries: %s\n' "${i}" 1>&2
      get_tr_api_header
    else
      printf '[DEBUG] Querying API failed. Query: "%s"\n' "$*" 1>&2
      return 1
    fi
  done
}

handle_torrent_done() {
  [[ -n ${TR_TORRENT_DIR} && -n ${TR_TORRENT_NAME} ]] || return
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
      append_log "Error" "${dest_display}" "${TR_TORRENT_NAME}"
    fi

  else

    if cp -rf "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" "${seed_dir}/"; then
      append_log "Finish" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
      query_tr_api "{\"arguments\":{\"ids\":[${TR_TORRENT_ID}],\"location\":\"${seed_dir}/\"},\"method\":\"torrent-set-location\"}"
    else
      append_log "Error" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    fi

  fi
}

get_tr_info() {
  if ! hash jq 1>/dev/null 2>&1; then
    printf '[DEBUG] %s\n' "Jq not found, will not proceed." 1>&2
    exit 1
  elif tr_info="$(query_tr_api '{"arguments":{"fields":["activityDate","status","sizeWhenDone","percentDone","id","name"]},"method":"torrent-get"}')" &&
    [[ "$(jq -r '.result' <<<"${tr_info}")" == 'success' ]]; then
    printf '[DEBUG] %s\n' "Getting torrents info success." 1>&2
  else
    printf '[DEBUG] Getting torrents info failed. Response: "%s"\n"' "${tr_info}" 1>&2
    exit 1
  fi
}

clean_local_disk() {
  local obsolete
  shopt -s nullglob dotglob globstar

  if pushd "${seed_dir}" >/dev/null; then
    declare -A dict
    while IFS= read -r -d '' i; do
      [[ -n ${i} ]] && dict["${i}"]=1
    done < <(jq -j '.arguments.torrents[]|"\(.name)\u0000"' <<<"${tr_info}")

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
    printf '[DEBUG] %s\n' 'Cleanup local disk:' "${obsolete[@]}" 1>&2
    ((debug == 0)) && rm -rf -- "${obsolete[@]}"
  fi

  shopt -u nullglob dotglob globstar
}

clean_inactive_feed() {
  local ids names disk_size free_space total_torrent_size space_threshold space_to_free m n

  for i in 1 2; do
    read -r disk_size free_space
  done < <(df --block-size=1 --output=size,avail "${seed_dir}") && [[ ${disk_size} =~ ^[0-9]+$ && ${free_space} =~ ^[0-9]+$ ]] || {
    printf '[DEBUG] %s\n' 'Read disk stats failed.' 1>&2
    return
  }

  total_torrent_size="$(jq -r '[.arguments.torrents[].sizeWhenDone]|add' <<<"${tr_info}")"
  if ((space_threshold = 50 * (1024 ** 3), m = space_threshold - disk_size + total_torrent_size, n = space_threshold - free_space, (space_to_free = m > n ? m : n) > 0)); then
    printf '[DEBUG] Cleanup inactive feeds. Disk free space: %d GiB, Space to free: %d GiB.\n' "$((free_space / 1024 ** 3))" "$((space_to_free / 1024 ** 3))" 1>&2
  else
    printf '[DEBUG] Space enough, skip action. Disk free space: %d GiB.\n' "$((free_space / 1024 ** 3))" 1>&2
    return
  fi

  while IFS='/' read -r -d '' id size name; do
    [[ -z ${name} ]] && continue
    ids+="${id},"
    names+=("${name}")

    if (((space_to_free -= size) <= 0)); then
      printf '[DEBUG] %s\n' 'Remove torrents:' "${names[@]}" 1>&2
      ((debug == 1)) || {
        query_tr_api "{\"arguments\":{\"ids\":[${ids%,}],\"delete-local-data\":\"true\"},\"method\":\"torrent-remove\"}" >/dev/null
      } && {
        for name in "${names[@]}"; do
          append_log "Remove" "${seed_dir}" "${name}"
        done
      }
      break
    fi
  done < <(jq -j '.arguments.torrents|sort_by(.activityDate)[]|select(.percentDone==1)|"\(.id)/\(.sizeWhenDone)/\(.name)\u0000"' <<<"${tr_info}")
}

resume_tr_torrent() {
  if [[ -n "$(jq -r '.arguments.torrents[]|select(.status < 4)' <<<"${tr_info}")" ]]; then
    query_tr_api '{"method":"torrent-start"}' >/dev/null
  fi
}

# Main
prepare
get_tr_api_header

handle_torrent_done

get_tr_info
clean_local_disk
clean_inactive_feed

resume_tr_torrent
exit 0
