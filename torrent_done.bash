#!/usr/bin/env bash

export LC_ALL=C LANG=C

seed_dir='/volume2/@transmission'
watch_dir='/volume1/video/Torrents'
script_dir="$(cd "${BASH_SOURCE[0]%/*}" && pwd -P)"
log_file="${script_dir}/log.log"
av_regex="${script_dir}/component/av_regex.txt"
tr_api='http://localhost:9091/transmission/rpc'

prepare() {
  exec {lock_fd}<"${BASH_SOURCE[0]}"
  flock -x "${lock_fd}"
  trap 'write_log' EXIT
}

append_log() {
  printf -v "logs[${#logs[@]}]" '%-20(%D %T)T%-10s%-35s%s' '-1' "$1" "${2:0:33}" "${3}"
}

write_log() {
  if ((${#logs[@]} > 0)); then
    local log_bak
    [[ -s ${log_file} ]] && log_bak="$(tail -n +3 "${log_file}")"
    {
      printf '%-20s%-10s%-35s%s\n%s\n' \
        'Date' 'Status' 'Destination' 'Name' \
        '-------------------------------------------------------------------------------'
      for ((i = ${#logs[@]} - 1; i >= 0; i--)); do
        printf '%s\n' "${logs[i]}"
      done
      [[ -n ${log_bak} ]] && printf '%s\n' "${bak}"
    } >"${log_file}"
  fi
}

get_tr_api_header() {
  if [[ "$(curl -sI "${tr_api}")" =~ 'X-Transmission-Session-Id:'[[:space:]]+[A-Za-z0-9]+ ]]; then
    tr_session_header="${BASH_REMATCH[0]}"
  fi
}

query_tr_api() {
  for i in {1..4}; do
    if curl -sf --header "${tr_session_header}" "${tr_api}" -d "$@"; then
      return 0
    elif ((i < 4)); then
      get_tr_api_header
    else
      return 1
    fi
  done
}

get_tr_info() {
  tr_info="$(
    query_tr_api '{
      "arguments": {
          "fields": [ "activityDate", "percentDone", "id", "sizeWhenDone", "name" ]
      },
      "method": "torrent-get"
    }'
  )" && [[ ${tr_info} == *'"result":"success"'* ]] || {
    printf '%s\n' "Query API failed. Exit."
    exit 1
  }
}

resume_tr_torrent() {
  query_tr_api '{"method": "torrent-start"}' >/dev/null
}

handle_torrent_done() {
  [[ -n ${TR_TORRENT_DIR} && -n ${TR_TORRENT_NAME} ]] || return
  [[ -e "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" ]] || {
    append_log "Missing" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    return
  }

  local file_list is_directory destination dest_display

  if [[ ${TR_TORRENT_DIR} == "${seed_dir}" ]]; then

    if [[ -d "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" ]]; then
      file_list="$(cd "${TR_TORRENT_DIR}" && find "${TR_TORRENT_NAME}" -not -path '*/[@#.]*' -size +50M)"
      [[ -z ${file_list} ]] && file_list="$(cd "${TR_TORRENT_DIR}" && find "${TR_TORRENT_NAME}" -not -path '*/[@#.]*')"
      file_list="${file_list,,}"
      is_directory=1
    else
      file_list="${TR_TORRENT_NAME,,}"
      is_directory=0
    fi

    if grep -Eqf "${av_regex}" <<<"${file_list}"; then
      destination='/volume1/driver/Temp'

    elif [[ ${file_list} =~ [^a-z0-9]([se][0-9]{1,2}|s[0-9]{1,2}e[0-9]{1,2}|ep[[:space:]_-]?[0-9]{1,3})[^a-z0-9] ]]; then
      destination='/volume1/video/TV Series'

    elif [[ ${TR_TORRENT_NAME,,} =~ (^|[^a-z0-9])(acrobat|adobe|animate|audition|dreamweaver|illustrator|incopy|indesign|lightroom|photoshop|prelude|premiere)([^a-z0-9]|$) ]]; then
      destination='/volume1/homes/admin/Download/Adobe'

    elif [[ ${TR_TORRENT_NAME,,} =~ (^|[^a-z0-9])(windows|mac(os)?|x(86|64)|(32|64)bit|v[0-9]+\.[0-9]+)([^a-z0-9]|$)|\.(zip|rar|exe|7z|dmg|pkg)$ ]]; then
      destination='/volume1/homes/admin/Download'

    else
      destination='/volume1/video/Films'
    fi

    dest_display="${destination}"
    ((is_directory)) || destination="${destination}/${TR_TORRENT_NAME%.*}"
    [[ -d ${destination} ]] || mkdir -p "${destination}"

    if cp -rf "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" "${destination}/"; then
      append_log "Finish" "${dest_display}" "${TR_TORRENT_NAME}"
    else
      append_log "Error" "${dest_display}" "${TR_TORRENT_NAME}"
    fi

  else

    if cp -rf "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" "${seed_dir}/"; then
      append_log "Finish" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
      query_tr_api "
        {
          \"arguments\": {
              \"ids\": [ ${TR_TORRENT_ID} ],
              \"location\": \"${seed_dir}/\",
              \"move\": \"false\"
          },
          \"method\": \"torrent-set-location\"
        }
      "
    else
      append_log "Error" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    fi

  fi
}

clean_local_disk() {
  local obsolete name pwd_bak="$PWD"
  shopt -s nullglob dotglob globstar

  if cd "${seed_dir}"; then
    declare -A dict
    while IFS= read -r -d '' name; do
      [[ -n ${name} ]] && dict["${name}"]=1
    done < <(jq -j '.arguments.torrents[]|"\(.name)\u0000"' <<<"${tr_info}")

    for name in [^.\#@]*; do
      [[ -n ${dict["${name}"]} ]] || {
        append_log 'Cleanup' "${seed_dir}" "${name}"
        obsolete+=("${seed_dir}/${name}")
      }
    done
  fi

  if cd "${watch_dir}"; then
    for name in **; do
      [[ -s ${name} ]] || obsolete+=("${watch_dir}/${name}")
    done
  fi

  if ((${#obsolete[@]} > 0)); then
    rm -rf -- "${obsolete[@]}"
  fi

  shopt -u nullglob dotglob globstar
  cd "${pwd_bak}"
}

clean_inactive_feed() {
  local ids names space_to_free free_space

  # Size unit from df: 1024 bytes
  for i in _ free_space; do
    read -r "$i"
  done < <(df --output=avail "${seed_dir}")

  [[ -n ${free_space} ]] && (((space_to_free = 50 * (1024 ** 3) - free_space * 1024) > 0)) || return

  while IFS='/' read -r -d '' id size name; do
    [[ -z ${name} ]] && continue
    ids+=("${id}")
    names+=("${name}")

    if (((space_to_free -= size) < 0)); then
      printf -v ids '%s,' "${ids[@]}"
      query_tr_api "
        {
          \"arguments\": {
              \"ids\": [ ${ids%,} ],
              \"delete-local-data\": \"true\"
          },
          \"method\": \"torrent-remove\"
        }
      " &&
        for name in "${names[@]}"; do
          append_log "Remove" "${seed_dir}" "${name}"
        done
      break
    fi
  done < <(
    jq -j '
      .arguments.torrents |
      sort_by(.activityDate)[] |
      select(.percentDone == 1 and .activityDate > 0) |
      "\(.id)/\(.sizeWhenDone)/\(.name)\u0000"
    ' <<<"${tr_info}"
  )
}

# Main
prepare
get_tr_api_header

handle_torrent_done

get_tr_info
clean_local_disk
clean_inactive_feed

resume_tr_torrent
