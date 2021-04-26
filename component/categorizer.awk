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

path == "" || $0 != $0 + 0 {
    printf("[AWK] Record ignored: ('%s', '%s')\n", path, $0) > "/dev/stderr"
    next
}

{
    splitext(tolower(path), a)
    switch (a[2]) {
    case "iso":
        if (a[1] ~ /(\y|_)(adobe|microsoft|windows|x(64|86)|v[0-9]+(\.[0-9]+)+)(\y|_)/) {
            # software
            type = "default"
            break
        }
        # fall-through
    case /^((og|r[ap]?|sk|w|web)m|3gp?[2p]|[aw]mv|asf|avi|divx|dpg|evo|f[4l]v|ifo|k3g|m(([14ko]|p?2)v|2?ts|2t|4b|4p|p4|peg?|pg|pv2|xf)|ns[rv]|ogv|qt|rmvb|swf|tpr?|ts|vob|wmp|wtv)$/:
        # video file.
        switch (a[2]) {
        case "m2ts":
            sub(/\/bdmv\/stream\/[^/]+$/, "", a[1])
            break
        case "vob":
            sub(/\/[^/]*vts[0-9_]+$/, "/video_ts", a[1])
        }
        videolist[a[1]] += $0
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
        count = process_videos(videolist, 52428800)  # 50 MiB threshold
        match_videos(videolist, count)
        if (count >= 3)
            match_series(videolist, count)
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
function splitext(p, a,  s, i, isext)
{
    delete a
    s = p
    while (i = index(s, "/"))
        s = substr(s, i + 1)
    while (i = index(s, ".")) {
        s = substr(s, i + 1)
        if (i > 1) isext = 1
    }
    if (isext) {
        a[1] = substr(p, 1, length(p) - length(s) - 1)
        a[2] = s
    } else {
        a[1] = p
        a[2] = ""
    }
}

# Return the key of the item with the max value in array. Note that to do
# numeric comparison, array values must be numbers, not strings.
function imax(a,  f, k, km, vm)
{
    f = 1
    for (k in a) {
        if (f) {
            f = 0
            km = k
            vm = a[k]
        } else if (a[k] > vm) {
            km = k
            vm = a[k]
        }
    }
    return km
}

# Find the index dividing common path prefix in array.
function index_commonprefix(a,  l, i, n, a1, a2)
{
    l = 0
    i = asort(a, a2, "@val_str_asc")
    n = split(a2[1], a1, "/")
    split(a2[i], a2, "/")
    for (i = 1; i <= n; i++) {
        if (a1[i] != a2[i]) break
        l += length(a1[i]) + 1
    }
    return l
}

# Inplace modify array `a` to a sorted list of its keys. The list is sorted by
# its origional values reversely. And if any of such values is less than `x`,
# the list is truncated from the point. In the result array, `a[0]` is the
# common prefix of all paths so that `a[0] + "/" + a[n] == path[n]`. If there
# was no common parent, `a[0]` is a null string. Return the number of video
# files.
# Example:
# input:  a = {"path/a": 1, "path/b": 5, "path/c": 3}, x = 1
# result: [0: "path", 1: "b", 2: "c"], return: 2
function process_videos(a, x,  d, m, n, i, j)
{
    n = asorti(a, d, "@val_num_desc")
    if (n > 1) {
        i = 1; j = n + 1
        while (i < j) {
            m = int((i + j) / 2)
            if (x > a[d[m]]) j = m
            else i = m + 1
        }
        if (i > 1) for (; n >= i; n--) delete d[n]
    }
    delete a
    if (n > 1 && (m = index_commonprefix(d))) {
        a[0] = substr(d[1], 1, m++ - 1)
        for (i in d) a[i] = substr(d[i], m)
    } else {
        a[0] = ""
        for (i in d) a[i] = d[i]
    }
    return n
}

# Match videos against patterns.
function match_videos(a, c,  i)
{
    for (i = (a[0] == "" ? 1 : 0); i <= c; i++) {
        if (a[i] ~ av_regex)
            output("av")
        if (a[i] ~ /(\y|_)([es]|ep[ _-]?|s([1-9][0-9]|0?[1-9])e)([1-9][0-9]|0?[1-9])(\y|_)/)
            output("tv")
    }
}

# Scan videolist to identify consecutive digits.
# input:
# a = ["path", "a01", "a03", "a05a06"], c = 3
# grouped:
# {"1, a": {1, 3, 5}, "2, a": {6}}
# If we found three digits in one group, identify as TV Series.
function match_series(a, c,  i, j, m, n, strs, nums, arr)
{
    for (i = 1; i <= c; i++) {  # skip a[0]
        m = split(a[i], strs, /[0-9]+/, nums)
        for (j = 1; j < m; j++) {
            while (n = index(strs[j], "/"))
                strs[j] = substr(strs[j], n + 1)
            gsub(/[[:space:][:cntrl:]._-]/, "", strs[j])
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
