#!/usr/bin/awk -f

BEGIN {
  re_template = "(^|[^a-z0-9])(_%AV_KEYWORD%_|(_%AV_ID_PREFIX%_)[[:space:]_-]?[0-9]{2,6})([^a-z0-9]|$)"

  result_file = "./av_regex.txt"
  av_keyword_file = "./av_keyword.txt"
  av_id_prefix_file = "./av_id_prefix.txt"

  PROCINFO["sorted_in"] = "@ind_str_asc"

  while ((getline < av_keyword_file) > 0) {
    if ($0 ~ /\S/) av_keyword[tolower($0)] = $0
  }

  while ((getline < av_id_prefix_file) > 0) {
    if ($0 ~ /\S/) av_id_prefix[tolower($0)] = $0
  }

  for (i in av_keyword) {
    re_av_keyword = (re_av_keyword == "" ? "" : re_av_keyword "|") i
    print av_keyword[i] > av_keyword_file
  }

  for (i in av_id_prefix) {
    re_av_id_prefix = (re_av_id_prefix == "" ? "" : re_av_id_prefix "|") i
    print av_id_prefix[i] > av_id_prefix_file
  }

  close(av_keyword_file)
  close(av_id_prefix_file)

  sub("_%AV_KEYWORD%_", re_av_keyword, re_template)
  sub("_%AV_ID_PREFIX%_", re_av_id_prefix, re_template)

  print(re_template) > result_file

  printf "Done. %s regex combined.\n", (length(av_keyword) + length(av_id_prefix))
}
