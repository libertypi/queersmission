# GNU Awk program for torrents categorization.
# Author: David Pi
#
# input stream:
#   size \0 path \0 ...
# variable assignment (passed via "-v"):
#   regexfile="/path/to/regexfile"
# output is one of:
#   default, av, film, tv, music

BEGIN {
    if (PROCINFO["version"] < 4)
        raise("GNU Awk >= 4 required.")

    RS = "\000"
    raise_exit = size_reached = 0
    size_thresh = (80 * 1024 ^ 2)
    delete sizedict

    if (regexfile != "" && (getline av_regex < regexfile) > 0 && av_regex ~ /[^[:space:]]/) {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", av_regex)
    } else {
        raise("Reading regexfile '" regexfile "' failed.")
    }
    close(regexfile)
}

NR % 2 {
    size = $0
    next
}

# sizedict[path]: size
size ~ /^[0-9]*$/ {
    if (size >= size_thresh) {
        if (! size_reached) {
            delete sizedict
            size_reached = 1
        }
    } else if (size_reached) {
        next
    }
    path = tolower($0)
    sub(/\/bdmv\/stream\/[^/]+\.m2ts$/, "/bdmv/index.bdmv", path) ||
    sub(/\/video_ts\/[^/]+\.vob$/, "/video_ts/video_ts.vob", path)
    sizedict[path] += size
}

END {
    if (raise_exit)
        exit 1
    if (NR % 2 || ! length(sizedict))
        raise("Invalid input. Expect null-terminated (size, path) pairs.")

    most_common = pattern_match(sizedict, videoset)
    if (most_common == "film" && length(videoset) >= 3)
        series_match(videoset)
    output(most_common)
}


function raise(msg)
{
    printf("[AWK] Error: %s\n", msg) > "/dev/stderr"
    raise_exit = 1
    exit 1
}

function max_value(arr,  i, j, m)
{
    i = -1
    for (m in arr) {
        if (arr[m] > i) {
            i = arr[m]
            j = m
        }
    }
    return j
}

# match files against patterns
# save video files to: videoset[path]
# return the most common file type
function pattern_match(sizedict, videoset,  i, type, arr)
{
    delete videoset
    PROCINFO["sorted_in"] = "@val_num_desc"
    for (i in sizedict) {
        if (i ~ /\.((a|bd|w)mv|(fl|og|vi|yu)v|3g[2p]|[as]vi|asf|f4[abpv]|iso|m(2?ts|4p|[24kop]v|p[24g]|peg?|xf)|qt|rm|rmvb|ts|vob|webm)$/) {
            if (i ~ av_regex)
                output("av")
            if (i ~ /\y([es]|ep[ _-]?|s([1-9][0-9]|0?[1-9])e)([1-9][0-9]|0?[1-9])\y/)
                output("tv")
            videoset[i]
            type = "film"
        } else if (i ~ /\.((al?|fl)ac|(m4|og|r|wm)a|aiff|ape|m?ogg|mp[3c]|opus|wa?v)$/) {
            type = "music"
        } else {
            type = "default"
        }
        arr[type] += sizedict[i]
    }
    delete PROCINFO["sorted_in"]
    return max_value(arr)
}

# Scan videoset to identify consecutive digits:
# input:
#   videoset[parent/string_05.mp4]
#   videoset[parent/string_06.mp4]
#   videoset[parent/string_04string_05.mp4]
# After split, grouped as:
#   arr[1, "string"][5] (parent/string_05.mp4)
#   arr[1, "string"][6] (parent/string_06.mp4)
#   arr[1, "string"][4] (parent/string_04string_05.mp4)
#   arr[2, "string"][5] (parent/string_04string_05.mp4)
#   (one file would never appear in the same group twice)
# For each group, sort its subgroups by keys:
#   nums[1] = 4
#   nums[2] = 5
#   nums[3] = 6
# If we found three consecutive digits in one group,
# identify as TV Series.
function series_match(videoset,  m, n, i, j, words, nums, arr)
{
    for (m in videoset) {
        n = split(m, words, /[0-9]+/, nums)
        for (i = 1; i < n; i++) {
            gsub(/.*\/|[[:space:][:punct:]]+/, "", words[i])
            arr[i, words[i]][nums[i] + 0]
        }
    }
    for (m in arr) {
        if (length(arr[m]) < 3) continue
        n = asorti(arr[m], nums, "@ind_num_asc")
        i = 1
        for (j = 2; j <= n; j++) {
            if (nums[j - 1] == nums[j] - 1) {
                if (++i == 3) output("tv")
            } else {
                i = 1
            }
        }
    }
}

function output(type)
{
    if (type ~ /^(default|av|film|tv|music)$/) {
        print type
        exit 0
    } else {
        raise("Invalid type: " type)
    }
}
