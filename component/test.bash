#!/usr/bin/env bash

export LC_ALL=C LANG=C

script_dir="$(cd "${BASH_SOURCE[0]%/*}" && pwd -P)"
av_regex="${script_dir}/av_regex.txt"
categorize="${script_dir}/categorize.awk"

TR_TORRENT_DIR='/volume2/@transmission'

cd "${TR_TORRENT_DIR}"

names=('天龙八部(黄日华版ISO收藏)' '[VCB-Studio] Yuru Camp [Ma10p_1080p]' '[VCB-Studio] Sora yori mo Tooi Basho [Ma10p_1080p]' '[MH&Airota&FZSD&VCB-Studio] Shuumatsu Nani Shitemasuka？ Isogashii Desuka？ Sukutte Moratte Ii Desuka？ [Ma10p_1080p]')

for TR_TORRENT_NAME in *; do
  # for TR_TORRENT_NAME in "${names[@]}"; do
  echo "${TR_TORRENT_NAME}"

  for i in dest dest_display; do
    IFS= read -r -d '' "$i"
  done < <(
    awk -v av_regex="${av_regex}" -v torrentDir="${TR_TORRENT_DIR}" -v torrentName="${TR_TORRENT_NAME}" -f "${categorize}"
  )

  printf "%s\n" "$dest" "$dest_display" ""

done
