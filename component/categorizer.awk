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
    video_thresh = 52428800 # 50 MiB
    raise_exit = thresh_reached = 0
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

path == "" || (size = $0 + 0) != $0 {
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
        video_add(arr, size)
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
    typedict[type] += size
}

END {
    if (raise_exit)
        exit 1
    if (! length(typedict))
        raise("Invalid input. Expect null-terminated (path, size) pairs.")

    type = imax(typedict)
    if (type == "film") {
        match_videos(videodict)
        if (length(videodict) >= 3)
            match_series(videodict)
    }
    output(type)
}


function raise(msg)
{
    printf("[AWK] Error: %s\n", msg) > "/dev/stderr"
    raise_exit = 1
    exit 1
}

function output(type)
{
    # if (type !~ /^(default|av|film|tv|music)$/)
    #     raise("Invalid type: " type)
    print type
    exit 0
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

# Return the key of the item with the max numeric value in array.
function imax(arr,  f, km, vm, k, v)
{
    f = 1
    for (k in arr) {
        v = arr[k] + 0
        if (f) {
            f = 0
            km = k
            vm = v
        } else if (v > vm) {
            km = k
            vm = v
        }
    }
    return km
}

# Add {path: size} to `videodict`. If any video meets `video_thresh`, we only
# keep files larger than that.
function video_add(arr, size)
{
    if (size >= video_thresh) {
        if (! thresh_reached) {
            delete videodict
            thresh_reached = 1
        }
    } else if (thresh_reached) {
        return
    }
    switch (arr[2]) {
    case "m2ts":
        sub(/\/bdmv\/stream\/[^/]+$/, "", arr[1])
        break
    case "vob":
        sub(/\/[^/]*vts[0-9_]+$/, "/video_ts", arr[1])
    }
    videodict[arr[1]] += size
}

# Match videos against patterns.
function match_videos(videodict,  i)
{
    PROCINFO["sorted_in"] = "@val_num_desc"
    for (i in videodict) {
        if (i ~ av_regex)
            output("av")
        if (i ~ /(\y|_)([es]|ep[ _-]?|s([1-9][0-9]|0?[1-9])e)([1-9][0-9]|0?[1-9])(\y|_)/)
            output("tv")
    }
    delete PROCINFO["sorted_in"]
}

# Scan videodict to identify consecutive digits.
# input:
# {"path/a01", "path/a03", "path/a05a06"}
# grouped:
# {"1, a": {1, 3, 5}, "2, a": {6}}
# If we found three digits in one group, identify as TV Series.
function match_series(videodict,  i, j, m, n, strs, nums, arr)
{
    for (i in videodict) {
        m = split(i, strs, /[0-9]+/, nums)
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
