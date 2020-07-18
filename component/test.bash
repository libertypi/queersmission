#!/usr/bin/env bash

export LC_ALL=C LANG=C

script_dir="$(cd "${BASH_SOURCE[0]%/*}" && pwd -P)"
av_regex="${script_dir}/av_regex.txt"
categorize="${script_dir}/categorize.awk"

TR_TORRENT_DIR='/volume2/@transmission'
cd "${TR_TORRENT_DIR}"
testf=(*)

# TR_TORRENT_DIR='/volume1/video/Films'
# cd "${TR_TORRENT_DIR}"
# testf=(*)

# TR_TORRENT_DIR='/volume1/video/TV Series'
# cd "${TR_TORRENT_DIR}"
# testf=(*)

for TR_TORRENT_NAME in "${testf[@]}"; do
  echo "${TR_TORRENT_NAME}"

  for i in dest dest_display; do
    IFS= read -r -d '' "$i"
  done < <(
    awk -v av_regex="${av_regex}" -v torrentDir="${TR_TORRENT_DIR}" -v torrentName="${TR_TORRENT_NAME}" -f "${categorize}"
  )

  printf "%s\n" "$dest" "$dest_display" ""

done
