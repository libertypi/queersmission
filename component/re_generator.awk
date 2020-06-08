#!/usr/bin/awk -f

BEGIN {
    if (ENVIRON["PWD"] !~ /\/component$/) {
        print "Please cd component directory first."
        exit 1
    }

    re_template = "(^|[^a-z0-9])(_%AV_KEYWORD%_|(_%AV_ID_PREFIX%_)[[:space:]_-]?[0-9]{2,6})([^a-z0-9]|$)"
    result_file = "./av_regex.txt"
    av_keyword_file = "./av_keyword.txt"
    av_id_prefix_file = "./av_id_prefix.txt"

    PROCINFO["sorted_in"] = "@ind_str_asc"
    av_keyword_regex = read_keyword_file(av_keyword_file)
    av_id_prefix_regex = read_keyword_file(av_id_prefix_file)

    sub("_%AV_KEYWORD%_", av_keyword_regex, re_template)
    sub("_%AV_ID_PREFIX%_", av_id_prefix_regex, re_template)

    print(re_template) > result_file
}


function read_keyword_file(file, string, arr, i)
{
    while ((getline < file) > 0) {
        if ($0 ~ /\S/) {
            arr[tolower($0)] = $0
        }
    }
    for (i in arr) {
        print(arr[i]) > file
        string = (string == "" ? "" : string "|") i
    }
    close(file)
    return string
}
