#!/usr/bin/env bash

export LC_ALL=C LANG=C

cd "${BASH_SOURCE[0]%/*}/.."
categorize="component/categorize.awk"
regex_file="component/regex.txt"

case $1 in
  1)
    TR_TORRENT_DIR='/volume1/video/TV Series'
    ;;
  2)
    TR_TORRENT_DIR='/volume1/video/Films'
    ;;
  r)
    printf '%s\n' "Testing Regex against driver directory..."
    grep -Eivf "${avRegexFile}" <(find '/volume1/driver' -type f -not -path '*/[.@#]*' -regextype 'posix-extended' -iregex '.*\.((bd|w)mv|3gp|asf|avi|flv|iso|m(2?ts|4p|[24kop]v|p([24]|e?g)|xf)|rm(vb)?|ts|vob|webm)' -printf '%P\n')
    printf '%s\n' "Done. These are the unmatched items in driver directory."

    printf '%s\n' "Testing Regex against video directory..."
    grep -Eif "${avRegexFile}" <(find '/volume1/video' -type f -not -path '*/[.@#]*' -printf '%P\n')
    printf '%s\n' "Done. This should show no match."
    exit
    ;;
  *)
    if [[ -e $1 ]]; then
      TR_TORRENT_DIR="${1%/*}"
      files=("${1##*/}")
    else
      TR_TORRENT_DIR='/volume2/@transmission'
    fi
    ;;
esac
if ((${#files[@]} == 0)); then
  pushd "${TR_TORRENT_DIR}" >/dev/null
  files=([^@\#.]*)
  popd >/dev/null
fi

# mkdir "component/profile"

for TR_TORRENT_NAME in "${files[@]}"; do

  printf '%s\n' "${TR_TORRENT_NAME}"

  for i in dest dest_display; do
    IFS= read -r -d '' "$i"
  done < <(
    awk -v REGEX_FILE="${regex_file}" -v TR_TORRENT_DIR="${TR_TORRENT_DIR}" -v TR_TORRENT_NAME="${TR_TORRENT_NAME}" -f "${categorize}"
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
