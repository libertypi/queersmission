#!/usr/bin/env bash

export LC_ALL=C LANG=C

test_regex() {
  printf '%s\n' "Testing '${regex_file}' on '${driver_dir}'..." "Unmatched items:"
  grep -Eivf "${regex_file}" <(find "${driver_dir}" -type f -not -path '*/[.@#]*' -regextype 'posix-extended' -iregex '.*\.((bd|w)mv|3gp|asf|avi|flv|iso|m(2?ts|4p|[24kop]v|p([24]|e?g)|xf)|rm(vb)?|ts|vob|webm)' -printf '%P\n')

  printf '%s' "Testing '${regex_file}' on '${video_dir}'..."
  local result="$(grep -Eif "${regex_file}" <(find "${video_dir}" -type f -not -path '*/[.@#]*' -printf '%P\n'))"
  if [[ -n "${result}" ]]; then
    printf '%s\n' "Failed. Match:" "${result}"
  else
    printf '%s\n' "Passed."
  fi
}

print_help() {
  cat <<EOF 1>&2
usage: ${BASH_SOURCE[0]} [OPTION]... [DIR]

Test ${categorize}.

optional arguments:
  -h            display this help text and exit
  -t            test '${tv_dir}'
  -f            test '${film_dir}'
  -r            test '${regex_file}' on '${driver_dir}'
  DIR           test DIR (default: '${seed_dir}')
EOF
}

cd "${BASH_SOURCE[0]%/*}" || exit 1
categorize="categorize.awk"
regex_file="regex.txt"

video_dir='/volume1/video'
tv_dir="${video_dir}/TV Series"
film_dir="${video_dir}/Films"
driver_dir='/volume1/driver'
av_dir="${driver_dir}/Temp"
seed_dir='/volume2/@transmission'
unset 'TR_TORRENT_DIR' 'names'

while getopts 'tfrh' a; do
  case "$a" in
    t) TR_TORRENT_DIR="${tv_dir}" ;;
    f) TR_TORRENT_DIR="${film_dir}" ;;
    r)
      test_regex
      exit 0
      ;;
    h)
      print_help
      exit 1
      ;;
    *) exit 1 ;;
  esac
done

if [[ -z "${TR_TORRENT_DIR+x}" ]]; then
  shift "$((OPTIND - 1))"
  if (($#)); then
    TR_TORRENT_DIR="${1%/*}"
    names=("${1##*/}")
  else
    TR_TORRENT_DIR="${seed_dir}"
  fi
fi
if [[ -z "${names+x}" ]]; then
  pushd "${TR_TORRENT_DIR}" >/dev/null && names=([^@\#.]*) || exit 1
  popd >'/dev/null'
fi

printf '%s\n\n' "Testing: ${TR_TORRENT_DIR}"

for TR_TORRENT_NAME in "${names[@]}"; do

  printf '%s\n' "${TR_TORRENT_NAME}"

  for i in dest root; do
    IFS= read -r -d '' "$i"
  done < <(
    awk -v REGEX_FILE="${regex_file}" -v TR_TORRENT_DIR="${TR_TORRENT_DIR}" -v TR_TORRENT_NAME="${TR_TORRENT_NAME}" -f "${categorize}"
  )

  if [[ ${TR_TORRENT_DIR} != "${seed_dir}" && ${root} != "${TR_TORRENT_DIR}" ]]; then
    error+=("${TR_TORRENT_NAME}: ${root}")
    format='\033[31m%s\n%s\033[0m\n\n'
  else
    case "${root}" in
      "${tv_dir}") format='\033[32m%s\n%s\033[0m\n\n' ;;
      "${film_dir}") format='\033[33m%s\n%s\033[0m\n\n' ;;
      "${av_dir}") format='\033[34m%s\n%s\033[0m\n\n' ;;
      *) format='%s\n%s\n\n' ;;
    esac
  fi
  printf "${format}" "Root: ${root}" "Dest: ${dest}"

done

if ((${#error} > 0)); then
  printf '%s\n' 'Errors:' "${error[@]}"
else
  printf '%s\n' 'Passed.'
fi
