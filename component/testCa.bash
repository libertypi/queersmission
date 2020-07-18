#!/usr/bin/env bash

export LC_ALL=C LANG=C

script_dir="$(cd "${BASH_SOURCE[0]%/*}" && pwd -P)"
av_regex="${script_dir}/av_regex.txt"
categorize="${script_dir}/categorize.awk"

case $1 in
  1)
    TR_TORRENT_DIR='/volume1/video/TV Series'
    ;;
  2)
    TR_TORRENT_DIR='/volume1/video/Films'
    ;;
  *)
    TR_TORRENT_DIR='/volume2/@transmission'
    ;;
esac

# mkdir -p "${script_dir}/profile"

cd "${TR_TORRENT_DIR}"
for TR_TORRENT_NAME in [^@\#.]*; do

  printf '%s\n' "${TR_TORRENT_NAME}"

  for i in dest dest_display; do
    IFS= read -r -d '' "$i"
  done < <(
    awk -v av_regex="${av_regex}" -v torrentDir="${TR_TORRENT_DIR}" -v torrentName="${TR_TORRENT_NAME}" -f "${categorize}"
    # awk -v av_regex="${av_regex}" -v torrentDir="${TR_TORRENT_DIR}" -v torrentName="${TR_TORRENT_NAME}" --profile="${script_dir}/profile/${TR_TORRENT_NAME}.awk" -f "${categorize}"
  )

  if [[ ${TR_TORRENT_DIR} != '/volume2/@transmission' && ${dest_display} != "${TR_TORRENT_DIR}" ]]; then
    error+=("${TR_TORRENT_NAME}: ${dest_display}")
    format='\033[31mDest: %s\nDisp: %s\033[0m\n\n'
  else
    format='Dest: %s\nDisp: %s\n\n'
  fi
  printf "${format}" "${dest}" "${dest_display}"

done

if ((${#error} > 0)); then
  printf '%s\n' 'Errors:'
  for e in "${error[@]}"; do
    printf '%s\n' "${e}"
  done
else
  printf '%s\n' 'Passed.'
fi
