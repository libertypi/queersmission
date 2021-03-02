#!/usr/bin/env bash

test_regex() {
  printf 'Testing "%s" on "%s"...\nUmatched items:\n' "${regexfile}" "${dir_driver}" 1>&2
  grep -Eivf "${regexfile}" <(
    find "${dir_driver}" -type f -not -path '*/[.@#]*' -regextype 'posix-extended' \
      -iregex '.+\.((bd|w)mv|3gp|asf|avi|flv|iso|m(2?ts|4p|[24kop]v|p([24]|e?g)|xf)|rm(vb)?|ts|vob|webm)' \
      -printf '%P\n'
  )

  printf '\nTesting "%s" on "%s"...' "${regexfile}" "${dir_video}" 1>&2
  local result="$(
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
dir_video="${dir_film%/*}"
dir_driver="${dir_av%/*}"
categorize='component/categorize.awk'
regexfile='component/regex.txt'

check=0
TR_TORRENT_DIR="${seed_dir}"

while getopts 'htfd:r' a; do
  case "$a" in
    t)
      TR_TORRENT_DIR="${dir_tv}"
      check=1
      ;;
    f)
      TR_TORRENT_DIR="${dir_film}"
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

  {
    IFS= read -r -d '' root
    IFS= read -r -d '' path
  } < <(
    awk -f "${categorize}" \
      -v TR_TORRENT_DIR="${TR_TORRENT_DIR}" \
      -v TR_TORRENT_NAME="${TR_TORRENT_NAME}" \
      -v regexfile="${regexfile}" \
      -v dir_default="${dir_default}" -v dir_av="${dir_av}" -v dir_film="${dir_film}" \
      -v dir_tv="${dir_tv}" -v dir_music="${dir_music}" -v dir_adobe="${dir_adobe}"
  )

  if [[ $? -ne 0 || (${check} == 1 && ${root} != "${TR_TORRENT_DIR}") ]]; then
    error+=("${TR_TORRENT_NAME} -> ${root}")
    color=31
  else
    case "${root}" in
      "${dir_av}") color=32 ;;
      "${dir_film}") color=33 ;;
      "${dir_tv}") color=34 ;;
      "${dir_music}") color=35 ;;
      "${dir_adobe}") color=36 ;;
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
