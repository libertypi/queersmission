#!/usr/bin/env bash

export LC_ALL=C LANG=C

categorize="${BASH_SOURCE[0]%/*}/categorize.awk"
regex_file="${BASH_SOURCE[0]%/*}/regex.txt"
video_dir='/volume1/video'
tv_dir="${video_dir}/TV Series"
film_dir="${video_dir}/Films"
driver_dir='/volume1/driver'
av_dir="${driver_dir}/Temp"
seed_dir='/volume2/@transmission'

test_regex() {
  printf 'Testing "%s" on "%s"...\nUmatched items:\n' "${regex_file}" "${driver_dir}" 1>&2
  grep -Eivf "${regex_file}" <(
    find "${driver_dir}" -type f -not -path '*/[.@#]*' -regextype 'posix-extended' \
      -iregex '.+\.((bd|w)mv|3gp|asf|avi|flv|iso|m(2?ts|4p|[24kop]v|p([24]|e?g)|xf)|rm(vb)?|ts|vob|webm)' \
      -printf '%P\n'
  )

  printf '\nTesting "%s" on "%s"...' "${regex_file}" "${video_dir}" 1>&2
  local result="$(
    grep -Eif "${regex_file}" <(
      find "${video_dir}" -type f -not -path '*/[.@#]*' -printf '%P\n'
    )
  )"
  if [[ ${result} ]]; then
    printf '%s\n' "failed. Matched items:" "${result}" 1>&2
  else
    printf '%s\n' "passed." 1>&2
  fi
}

print_help() {
  cat <<EOF 1>&2
usage: ${BASH_SOURCE[0]} [-h] [-t] [-f] [-d DIR] [-r]

Test ${categorize}.
If no argument was passed, scan '${seed_dir}'.

optional arguments:
  -h            display this help text and exit
  -t            scan '${tv_dir}'
  -f            scan '${film_dir}'
  -d DIR        scan DIR
  -r            test '${regex_file}' with '${driver_dir}'
EOF
  exit 1
}

unset IFS names error
check=0
TR_TORRENT_DIR="${seed_dir}"

while getopts 'htfd:r' a; do
  case "$a" in
    t)
      TR_TORRENT_DIR="${tv_dir}"
      check=1
      ;;
    f)
      TR_TORRENT_DIR="${film_dir}"
      check=1
      ;;
    d)
      OPTARG="${OPTARG%/}"
      names=("${OPTARG##*/}")
      if [[ ${names[0]} == "${OPTARG}" ]]; then
        TR_TORRENT_DIR="${PWD}"
      else
        TR_TORRENT_DIR="${OPTARG%/*}"
      fi
      [[ -e "${OPTARG}" ]] && check=1
      ;;
    r)
      test_regex
      exit 0
      ;;
    h) print_help ;;
    *) exit 1 ;;
  esac
done

((${#names[@]})) || {
  pushd "${TR_TORRENT_DIR}" >/dev/null && names=([^@\#.]*) || exit 1
  popd >/dev/null
}

printf '%s\n\n' "Testing: ${TR_TORRENT_DIR}" 1>&2

for TR_TORRENT_NAME in "${names[@]}"; do

  printf '%s\n' "${TR_TORRENT_NAME}"

  {
    IFS= read -r -d '' root
    IFS= read -r -d '' path
  } < <(
    awk -v REGEX_FILE="${regex_file}" \
      -v TR_TORRENT_DIR="${TR_TORRENT_DIR}" \
      -v TR_TORRENT_NAME="${TR_TORRENT_NAME}" \
      -f "${categorize}"
  )

  if [[ $? != 0 ]] || [[ ${check} == 1 && ${root} != "${TR_TORRENT_DIR}" ]]; then
    error+=("${TR_TORRENT_NAME} -> ${root}")
    color=31
  else
    case "${root}" in
      "${tv_dir}") color=32 ;;
      "${film_dir}") color=33 ;;
      "${av_dir}") color=34 ;;
      *) color=0 ;;
    esac
  fi
  printf "\033[${color}m%s\n%s\033[0m\n\n" "Root: ${root}" "Path: ${path}"

done

if ((${#error})); then
  printf '%s\n' 'Errors:' "${error[@]}" 1>&2
else
  printf '%s\n' 'Passed.' 1>&2
fi
