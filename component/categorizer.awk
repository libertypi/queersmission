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
    size_thresh = 52428800  # 50 MiB

    if (regexfile == "") raise("Require argument: '-v regexfile=...'")
    if ((getline av_regex < regexfile) > 0 && av_regex ~ /[^[:space:]]/) {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", av_regex)
    } else {
        raise("Reading regexfile failed: " regexfile)
    }
    close(regexfile)
}

NR % 2 {
    path = tolower($0)
    next
}

path == "" || $0 != $0 + 0 {
    raise("Invalid record: ('" path "', '" $0 "')")
}

{
    # split extension
    if (n = indexext(path)) {
        type = substr(path, n + 1)  # ext
        path = substr(path, 1, n - 1)
    } else {
        type = ""
    }

    # categorize file type
    switch (type) {
    case "iso":
        # iso file could be software or video image
        if (path ~ /(\y|_)(adobe|microsoft|windows|x(64|86)|v[0-9]+(\.[0-9]+)+)(\y|_)/) {
            type = "default"
        } else {
            type = "film"
            videolist[path] += $0
        }
        break
    case "m2ts":
        type = "film"
        sub(/\/bdmv\/stream\/[^/]+$/, "", path)
        videolist[path] += $0
        break
    case "vob":
        sub(/\/[^/]*vts[0-9_]+$/, "/video_ts", path)
        # fall-through
    case /^((og|r[ap]?|sk|w|web)m|3gp?[2p]|[aw]mv|asf|avi|divx|dpg|evo|f[4l]v|ifo|k3g|m(([14ko]|p?2)v|2t|4b|4p|p4|peg?|pg|pv2|ts|xf)|ns[rv]|ogv|qt|rmvb|swf|tpr?|ts|wmp|wtv)$/:
        # video file
        type = "film"
        videolist[path] += $0
        break
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

    # min and max strings
    if (NR == 2) path_min = path_max = path
    else if (path > path_max) path_max = path
    else if (path < path_min) path_min = path
}

END {
    if (raise_exit) exit 1
    if (! length(typedict))
        raise("Invalid input. Expect null-terminated (path, size) pairs.")

    n = index_commonprefix(path_min, path_max)
    if (n) match_video(substr(path_min, 1, n - 1))

    type = imax(typedict)
    if (type == "film") {
        n = process_list(videolist, size_thresh, n)
        match_videos(videolist, n)
        if (n >= 3) match_series(videolist)
    }
    output(type)
}


function raise(msg)
{
    printf("[AWK] Error: %s\n", msg) > "/dev/stderr"
    raise_exit = 1
    exit 1
}

# Return the index of the dot which split the path into root and extension uses
# the same logic as Python's `os.path.splitext`. If there was no ext, return 0.
function indexext(p,  i, j, c)
{
    for (i = length(p); i > 0; i--) {
        c = substr(p, i, 1)
        if (c == "/") break
        if (c == ".") { if (! j) j = i }
        else if (j) return j
    }
    return 0
}

# Find the common prefix of two paths, return the length of it.
function index_commonprefix(lo, hi,  f, i, n, a1, a2)
{
    f = 0
    n = split(lo, a1, "/")
    split(hi, a2, "/")
    for (i = 1; i <= n; i++) {
        if (a1[i] != a2[i]) break
        f += length(a1[i]) + 1
    }
    return f
}

# Return the key with the max numeric value in array.
function imax(a,  f, k, v, km, vm)
{
    f = 1
    for (k in a) {
        v = a[k] + 0  # force numeric comparison
        if (f) { km = k; vm = v; f = 0 }
        else if (v > vm) { km = k; vm = v }
    }
    return km
}

# Inplace modify array `a` to a sorted list of its keys. The list is reversely
# sorted by its origional values. And if any of such values meets `x`, all the
# keys with value less than `x` are deleted. `n` is the length of prefix to be
# stripped from all paths. Return the length of result.
function process_list(a, x, n,  c, i, j, m, d)
{
    c = asorti(a, d, "@val_num_desc")
    if (c > 1) {
        i = 1; j = c + 1
        while (i < j) {
            m = int((i + j) / 2)
            if (x > a[d[m]]) j = m
            else i = m + 1
        }
        if (i > 1) c = i - 1
    }
    delete a
    if (n++) {
        for (i = 1; i <= c; i++) a[i] = substr(d[i], n)
    } else {
        for (i = 1; i <= c; i++) a[i] = d[i]
    }
    return c
}

# Test a single string.
function match_video(p,  a)
{
    a[1] = p
    match_videos(a, 1)
}

# Test (video) strings with patterns.
function match_videos(a, c,  i)
{
    for (i = 1; i <= c; i++) {
        if (a[i] ~ av_regex)
            output("av")
        if (a[i] ~ /(\y|_)([es]|ep[ _-]?|s([1-9][0-9]|0?[1-9])e)([1-9][0-9]|0?[1-9])(\y|_)/)
            output("tv")
    }
}

# Scan strings to identify consecutive digits.
# input:
# ["a01", "a03", "a05a06"]
# grouped:
# {"1, a": {1, 3, 5}, "2, a": {6}}
# If three digits was in one group, identify as TV Series.
function match_series(a,  i, j, m, n, strs, nums, arr)
{
    for (i in a) {
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
