# GNU Awk program for torrents categorization.
# Author: David Pi
# Requires: gawk 4+
#
# variable assignment (-v var=val):
#   regexfile
# standard input:
#   path \0 size \0 ...
# standard output:
#   {"default", "av", "film", "tv", "music"}

BEGIN {
    RS = "\000"
    raise_exit = 0
    delete typedict

    if (regexfile == "") raise("Require argument: '-v regexfile=...'")
    if ((getline av_regex < regexfile) > 0 && av_regex ~ /[^[:space:]]/) {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", av_regex)
    } else {
        raise("Reading regexfile '" regexfile "' failed.")
    }
    close(regexfile)
}

FNR % 2 {
    path = $0
    next
}

path == "" || $0 + 0 != $0 {
    printf("[AWK] Record ignored: ('%s', '%s')\n", path, $0) > "/dev/stderr"
    next
}

{
    splitext(tolower(path), arr)
    switch (arr[2]) {
    case "iso":
        if (arr[1] ~ /(\y|_)(adobe|microsoft|windows|x(64|86)|v[0-9]+(\.[0-9]+)+)(\y|_)/) {
            # software
            type = "default"
            break
        }
        # fall-through
    case /^((og|r[ap]?|sk|w|web)m|3gp?[2p]|[aw]mv|asf|avi|divx|dpg|evo|f[4l]v|ifo|k3g|m(([14ko]|p?2)v|2?ts|2t|4b|4p|p4|peg?|pg|pv2|xf)|ns[rv]|ogv|qt|rmvb|swf|tpr?|ts|vob|wmp|wtv)$/:
        # video file.
        switch (arr[2]) {
        case "m2ts":
            sub(/\/bdmv\/stream\/[^/]+$/, "", arr[1])
            break
        case "vob":
            sub(/\/[^/]*vts[0-9_]+$/, "/video_ts", arr[1])
        }
        videolist[arr[1]] += $0
        # fall-through
    case /^([ax]ss|asx|bdjo|bdmv|clpi|idx|mpls?|psb|rt|s(bv|mi|rr|rt|sa|sf|ub|up)|ttml|usf|vtt|w[mv]x)$/:
        # video subtitle, playlist
        type = "film"
        break
    case /^((al?|fl)ac|(cd|r|tt|wm)a|aiff|amr|ape|cue|dsf|dts(hd)?|e?ac3|m(3u8?|[124kp]a|od|p[23c])|ogg|opus|pls|tak|wa?v|wax|xspf)$/:
        # audio file, playlist
        type = "music"
        break
    default:
        type = "default"
    }
    typedict[type] += $0
}

END {
    if (raise_exit)
        exit 1
    if (! length(typedict))
        raise("Invalid input. Expect null-terminated (path, size) pairs.")

    type = imax(typedict)
    if (type == "film") {
        sort_videos(videolist, 52428800)  # threshold: 50 MiB
        match_videos(videolist)
        if (length(videolist) >= 3)
            match_series(videolist)
    }
    output(type)
}


function raise(msg)
{
    printf("[AWK] Error: %s\n", msg) > "/dev/stderr"
    raise_exit = 1
    exit 1
}

# Split the path into a pair (root, ext). This behaves the same way as Python's
# os.path.splitext, except that the period between root and ext is omitted.
function splitext(p, arr,  s, i, isext)
{
    delete arr
    s = p
    while (i = index(s, "/"))
        s = substr(s, i + 1)
    while (i = index(s, ".")) {
        s = substr(s, i + 1)
        if (i > 1) isext = 1
    }
    if (isext) {
        arr[1] = substr(p, 1, length(p) - length(s) - 1)
        arr[2] = s
    } else {
        arr[1] = p
        arr[2] = ""
    }
}

# Return the key of the item with the max value in array. Note that to do
# numeric comparison, array values must be numbers, not strings.
function imax(arr,  f, k, km, vm)
{
    f = 1
    for (k in arr) {
        if (f) {
            f = 0
            km = k
            vm = arr[k]
        } else if (arr[k] > vm) {
            km = k
            vm = arr[k]
        }
    }
    return km
}

# Reversely sort the keys of `a` by its values, then use bisect right algorism
# to slice the list to value `x`. If no value meets `x`, the list is not sliced.
function sort_videos(a, x,  d, i, lo, hi, mid)
{
    i = asorti(a, d, "@val_num_desc") + 1
    lo = 1
    hi = i
    while (lo < hi) {
        mid = int((lo + hi) / 2)
        if (x > a[d[mid]]) hi = mid
        else lo = mid + 1
    }
    if (lo == 1) lo = i
    delete a
    for (i = 1; i < lo; i++) a[i] = d[i]
}

# Match videos against patterns.
function match_videos(videolist,  i, n)
{
    n = length(videolist)
    for (i = 1; i <= n; i++) {
        if (videolist[i] ~ av_regex)
            output("av")
        if (videolist[i] ~ /(\y|_)([es]|ep[ _-]?|s([1-9][0-9]|0?[1-9])e)([1-9][0-9]|0?[1-9])(\y|_)/)
            output("tv")
    }
}

# Scan videolist to identify consecutive digits.
# input:
# ["path/a01", "path/a03", "path/a05a06"]
# grouped:
# {"1, a": {1, 3, 5}, "2, a": {6}}
# If we found three digits in one group, identify as TV Series.
function match_series(videolist,  i, j, m, n, strs, nums, arr)
{
    for (i in videolist) {
        m = split(videolist[i], strs, /[0-9]+/, nums)
        for (j = 1; j < m; j++) {
            while (n = index(strs[j], "/"))
                strs[j] = substr(strs[j], n + 1)
            gsub(/[[:space:]._-]+/, "", strs[j])
            n = (j SUBSEP strs[j])
            arr[n][nums[j] + 0]
            if (length(arr[n]) == 3) output("tv")
        }
    }
}

function output(type)
{
    # if (type !~ /^(default|av|film|tv|music)$/)
    #     raise("Invalid type: " type)
    print type
    exit 0
}
