#!/usr/bin/env bash

export LC_ALL=C LANG=C

seed_dir='/volume2/@transmission'
watch_dir='/volume1/video/Torrents'
script_dir="$(cd "${BASH_SOURCE[0]%/*}" && pwd -P)"
log_file="${script_dir}/log.log"
av_regex="${script_dir}/component/av_regex.txt"

tr_binary() {
  '/var/packages/transmission/target/bin/transmission-remote' "$@"
}

write_log() {
  local bak
  [[ -s ${log_file} ]] && bak="$(tail -n +3 "${log_file}")"
  {
    printf '%-20s%-10s%-35s%s\n%s\n%-20(%D %T)T%-10s%-35s%s\n' \
      'Date' 'Status' 'Destination' 'Name' \
      '-------------------------------------------------------------------------------' \
      '-1' "${1}" "${2:0:33}" "$3"
    [[ -n ${bak} ]] && printf '%s\n' "${bak}"
  } >"${log_file}"
}

exec {lock_fd}<"${BASH_SOURCE[0]}"
flock -x "${lock_fd}"

if [[ -n ${TR_TORRENT_DIR} && -n ${TR_TORRENT_NAME} ]]; then
  if [[ ! -e "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" ]]; then
    write_log "Missing" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
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
      write_log "Finish" "${dest_display}" "${TR_TORRENT_NAME}"
    else
      write_log "Error" "${dest_display}" "${TR_TORRENT_NAME}"
    fi

  else

    if cp -rf "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" "${seed_dir}/"; then
      write_log "Finish" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
      tr_binary -t "$TR_TORRENT_ID" --find "${seed_dir}/"
    else
      write_log "Error" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
    fi

  fi
fi

tr_info="$(tr_binary -t all -i)" && [[ -n ${tr_info} ]] || exit 1

(
  shopt -s nullglob dotglob globstar

  if cd "${seed_dir}"; then
    declare -A dict
    while IFS= read -r name; do
      [[ -n ${name} ]] && dict["${name}"]=1
    done < <(sed -En 's/^[[:space:]]+Name: (.+)/\1/p' <<<"${tr_info}")

    for file in [^.\#@]*; do
      [[ ${dict["${file}"]} ]] || {
        write_log 'Cleanup' "${seed_dir}" "${file}"
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

((space_threshold = 80 * 1024 * 1024))
short_of_space() {
  local space
  for i in _ space; do
    read -r "$i"
  done < <(df --output=avail "${seed_dir}")
  if [[ -n $space && $space -lt $space_threshold ]]; then
    return 0
  else
    return 1
  fi
}

if short_of_space; then
  while IFS='/' read -r -d '' id name; do
    [[ -z $id ]] && continue
    write_log "Remove" "${seed_dir}" "${name}"
    tr_binary -t "${id}" --remove-and-delete
    short_of_space || break
  done < <(
    awk '
    BEGIN {
      FS = ": "
      seed_threshold = (systime() - 86400)
      split("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec", months, " ")
      for (i = 1; i <= 12; i++) {
        mon[months[i]] = i
      }
    }

    /^[[:space:]]+Id: / && $2 ~ /^[0-9]+$/ {
      id = $2
      name = ""
      next
    }

    id != "" && name == "" && match($0, /^[[:space:]]+Name: (.+)$/, n) {
      name = n[1]
      next
    }

    id != "" && /^[[:space:]]+Percent Done: / {
      if ($2 != "100%") id = ""
      next
    }

    id != "" && name != "" && match($0, /^[[:space:]]+Latest activity:[[:space:]]+(.+)$/, n) {
      if (n[1] != "") {
        # Mon May 25 20:04:31 2020
        split(n[1], date, " ")
        gsub(":", " ", date[4])
        last_activate = mktime(date[5] " " mon[date[2]] " " date[3] " " date[4])
        if (last_activate > 0 && last_activate < seed_threshold) {
          array[last_activate "." NR] = (id "/" name)
        }
      }
      id = name = ""
    }

    END {
      PROCINFO["sorted_in"] = "@ind_num_asc"
      for (i in array) {
        printf "%s\000", array[i]
      }
    }
    ' <<<"$tr_info"
  )
fi

tr_binary -t all -s
