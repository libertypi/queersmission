#!/usr/bin/env bash

test_regex() {
  local result dir_video="${locations[film]%/*}" dir_driver="${locations[av]%/*}"

  printf 'Testing "%s" on "%s"...\nUmatched items:\n' "${regexfile}" "${dir_driver}" 1>&2
  grep -Eivf "${regexfile}" <(
    find "${dir_driver}" -type f -not -path '*/[.@#]*' -regextype 'posix-extended' \
      -iregex '.+\.((bd|w)mv|3gp|asf|avi|flv|iso|m(2?ts|4p|[24kop]v|p([24]|e?g)|xf)|rm(vb)?|ts|vob|webm)' \
      -printf '%P\n'
  )

  printf '\nTesting "%s" on "%s"...' "${regexfile}" "${dir_video}" 1>&2
  result="$(
    grep -Eif "${regexfile}" <(
      find "${dir_video}" -type f -not -path '*/[.@#]*' -printf '%P\n'
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
  -t            scan '${dir_tv}'
  -f            scan '${dir_film}'
  -d DIR        scan DIR
  -r            test '${regexfile}' with '${dir_driver}'
EOF
  exit 1
}

unset IFS names error
export LC_ALL=C LANG=C

cd "${BASH_SOURCE[0]%/*}/.." || exit 1
source ./config

categorize='component/categorize.awk'
regexfile='component/regex.txt'
TR_TORRENT_DIR="${seed_dir}"
check=0

while getopts 'htfd:r' a; do
  case "$a" in
    t)
      TR_TORRENT_DIR="${locations[tv]}"
      check=1
      ;;
    f)
      TR_TORRENT_DIR="${locations[film]}"
      check=1
      ;;
    d)
      while [[ ${OPTARG} == */ ]]; do OPTARG="${OPTARG%/}"; done
      names=("${OPTARG##*/}")
      if [[ -z ${names[0]} ]]; then
        print_help
      elif [[ ${names[0]} == "${OPTARG}" ]]; then
        TR_TORRENT_DIR="${PWD}"
      else
        TR_TORRENT_DIR="${OPTARG%/*}"
      fi
      [[ -e ${OPTARG} ]] && check=1
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
  pushd "${TR_TORRENT_DIR}" >/dev/null && names=([^.\#@]*) || exit 1
  popd >/dev/null
}

printf '%s\n\n' "Testing: ${TR_TORRENT_DIR}" 1>&2

for TR_TORRENT_NAME in "${names[@]}"; do

  printf '%s\n' "${TR_TORRENT_NAME}"

  key="$(
    awk -v TR_TORRENT_DIR="${TR_TORRENT_DIR}" \
      -v TR_TORRENT_NAME="${TR_TORRENT_NAME}" \
      -v regexfile="${regexfile}" \
      -f "${categorize}"
  )"
  path="${locations[${key}]}"

  if [[ $? -ne 0 || (${check} == 1 && ${path} != "${TR_TORRENT_DIR}") ]]; then
    error+=("${TR_TORRENT_NAME} -> ${path} (${key})")
    color=31
  else
    case "${key}" in
      av) color=32 ;;
      film) color=33 ;;
      tv) color=34 ;;
      music) color=35 ;;
      adobe) color=36 ;;
      default) color=0 ;;
      *)
        printf 'Error: Invalid type: "%s"' "${key}" 1>&2
        exit 1
        ;;
    esac
  fi
  printf "\033[${color}m%s\n%s\033[0m\n\n" "Type: ${key}" "Path: ${path}"

done

if ((!check)); then
  printf '%s\n' 'Done.' 1>&2
elif ((${#error})); then
  printf '%s\n' 'Errors:' "${error[@]}" 1>&2
else
  printf '%s\n' 'Passed.' 1>&2
fi
