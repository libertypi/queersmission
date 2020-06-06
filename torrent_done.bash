#!/usr/bin/env bash

export LC_ALL=C LANG=C

seed_dir='/volume2/@transmission'
watch_dir='/volume1/video/Torrents'
script_dir="$(cd "${BASH_SOURCE[0]%/*}" && pwd -P)"
log_file="${script_dir}/log.log"
av_regex="${script_dir}/component/av_regex.txt"
tr_api='http://localhost:9091/transmission/rpc'

append_log() {
  printf -v "log_date[${#log_date[@]}]" '%(%D %T)T' '-1'
  log_status+=("$1")
  log_dest+=("$2")
  log_name+=("$3")
}

write_log() {
  if ((${#log_date[@]} > 0)); then
    [[ -s ${log_file} ]] && bak="$(tail -n +3 "${log_file}")"
    {
      printf '%-20s%-10s%-35s%s\n%s\n' \
        'Date' 'Status' 'Destination' 'Name' \
        '-------------------------------------------------------------------------------'
      for ((i = ${#log_date[@]} - 1; i >= 0; i--)); do
        printf '%-20s%-10s%-35s%s\n' "${log_date[i]}" "${log_status[i]}" "${log_dest[i]:0:33}" "${log_name[i]}"
      done
      [[ -n ${bak} ]] && printf '%s\n' "${bak}"
    } >"${log_file}"
  fi
}

query_tr_api() {
  curl -s --header "${tr_session_header}" "${tr_api}" -d "$@"
}

exec {lock_fd}<"${BASH_SOURCE[0]}"
flock -x "${lock_fd}"
trap 'write_log' EXIT
tr_session_header="$(curl -sI "${tr_api}" | grep -Eo -m1 'X-Transmission-Session-Id: [A-Za-z0-9]+')"

if [[ -n ${TR_TORRENT_DIR} && -n ${TR_TORRENT_NAME} ]]; then
  if [[ ! -e "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" ]]; then
    append_log "Missing" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    exit
  fi

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
fi

tr_result="$(
  query_tr_api '
    {
      "arguments": {
          "fields": [ "activityDate", "percentDone", "id", "sizeWhenDone", "name" ]
      },
      "method": "torrent-get"
    }
  '
)" && hash jq || exit

(
  shopt -s nullglob dotglob globstar

  if cd "${seed_dir}"; then
    declare -A dict
    while IFS= read -r name; do
      [[ -n ${name} ]] && dict["${name}"]=1
    done < <(jq -r '.arguments.torrents|.[]|.name' <<<"${tr_result}")

    for file in [^.\#@]*; do
      [[ ${dict["${file}"]} ]] || {
        append_log 'Cleanup' "${seed_dir}" "${file}"
        obsolete+=("${seed_dir}/${file}")
      }
    done
  fi

  if cd "${watch_dir}"; then
    for file in **; do
      [[ -s ${file} ]] || obsolete+=("${watch_dir}/${file}")
    done
  fi

  if ((${#obsolete[@]} > 0)); then
    rm -rf -- "${obsolete[@]}"
  fi
)

for i in _ free_space; do
  read -r "$i"
done < <(df --output=avail "${seed_dir}")

# Size unit from df: 1024 bytes
((space_threshold = 50 * (1024 ** 3)))
if [[ -n ${free_space} ]] && (((total_size = space_threshold - free_space * 1024) > 0)); then
  while IFS='/' read -r id size name; do
    [[ -z ${id} ]] && continue
    ids+=("${id}")
    names+=("${name}")

    if (((total_size -= size) < 0)); then
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
    jq -r '
      .arguments.torrents |
      sort_by(.activityDate) |
      .[] |
      select(.percentDone == 1 and .activityDate > 0) |
      [.id, .sizeWhenDone, .name] |
      "\(.[0])/\(.[1])/\(.[2])"
    ' <<<"${tr_result}"
  )
fi

query_tr_api '{"method": "torrent-start"}'
