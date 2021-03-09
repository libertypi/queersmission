# GNU Awk program for torrents categorization.
# Author: David Pi
#
# Input stream:
#   size\0path\0, ...
# Input variables (passed via "-v"):
#   regexfile
# Output is one of:
#   default, av, film, tv, music, adobe

BEGIN {
    RS = "^$"
    if (regexfile != "" && (getline av_regex < regexfile) > 0 && av_regex ~ /\S/) {
        gsub(/^\s+|\s+$/, "", av_regex)
    } else {
        raise("Reading regexfile '" regexfile "' failed.")
    }
    close(regexfile)
    RS = "\000"
    errno = size_reached = 0
    size_thresh = (80 * 1024 ^ 2)
    split("", sizedict)
    split("", filelist)
    split("", videoset)
}

NR % 2 {
    if ($0 !~ /^[0-9]+$/)
        raise("Invalid size, expect integer: '" $0 "'")
    size = $0
    next
}

{
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
    if (errno)
        exit errno
    if (NR % 2)
        raise("Invalid input. Expect null-terminated (size, path) pairs.")
    # sizedict[path]: size
    # filelist[1]: path (sorted by filesize, largest first)
    if (asorti(sizedict, filelist, "@val_num_desc") <= 0)
        raise("Empty input.")

    pattern_match(filelist, videoset)
    if (length(videoset) >= 3)
        series_match(videoset)
    ext_match(sizedict, filelist, videoset)
}


function raise(msg)
{
    printf("[AWK] Fatal: %s\n", msg) > "/dev/stderr"
    errno = 1
    exit 1
}

function pattern_match(filelist, videoset,  n, i, s)
{
    # videoset[path]
    n = length(filelist)
    for (i = 1; i <= n; i++) {
        s = filelist[i]
        if (s ~ /\.(3gp|asf|avi|bdmv|flv|iso|m(2?ts|4p|[24kop]v|p2|p4|pe?g|xf)|rm|rmvb|ts|vob|webm|wmv)$/) {
            if (s ~ av_regex)
                output("av")
            if (s ~ /\y([es]|ep[ _-]?|s([1-9][0-9]|0?[1-9])e)([1-9][0-9]|0?[1-9])\y/)
                output("tv")
            videoset[s]
        }
        if (i == 1 && s ~ /\.(7z|[di]mg|[rt]ar|exe|gz|iso|zip)$/) {
            if (s ~ /(^|[^a-z])(acrobat|adobe|animate|audition|dreamweaver|illustrator|incopy|indesign|lightroom|photoshop|prelude|premiere)($|[^a-z])/)
                output("adobe")
            if (s ~ /(^|[^a-z0-9])((32|64)bit|mac(os)?|windows|microsoft|x64|x86)($|[^a-z0-9])/)
                output("default")
        }
    }
}

function series_match(videoset,  m, n, i, j, words, nums, groups)
{
    # Scan multiple videoset to identify consecutive digits:
    # input:
    #   videoset[parent/string_05.mp4]
    #   videoset[parent/string_06.mp4]
    #   videoset[parent/string_04string_05.mp4]
    # After split, grouped as:
    #   groups[1, "string"][5] (parent/string_05.mp4)
    #   groups[1, "string"][6] (parent/string_06.mp4)
    #   groups[1, "string"][4] (parent/string_04string_05.mp4)
    #   groups[2, "string"][5] (parent/string_04string_05.mp4)
    #   (file would never appear in one group twice)
    # For each group, sort its subgroup by the digits:
    #   nums[1] = 4
    #   nums[2] = 5
    #   nums[3] = 6
    # If we found three consecutive digits in one group,
    # identify as TV Series.
    for (m in videoset) {
        n = split(m, words, /[0-9]+/, nums)
        for (i = 1; i < n; i++) {
            gsub(/.*\/|\s+/, "", words[i])
            groups[i, words[i]][int(nums[i])]
        }
    }
    for (m in groups) {
        if (length(groups[m]) < 3) continue
        n = asorti(groups[m], nums, "@ind_num_asc")
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

function ext_match(sizedict, filelist, videoset,  i, j, groups)
{
    for (i = 1; i in filelist && i <= 3; i++) {
        if (filelist[i] in videoset) {
            j = "film"
        } else if (filelist[i] ~ /\.((al?|fl)ac|ape|m4a|mp3|ogg|wav|wma)$/) {
            j = "music"
        } else {
            j = "default"
        }
        groups[j] += sizedict[filelist[i]]
    }
    asorti(groups, groups, "@val_num_desc")
    output(groups[1])
}

function output(type)
{
    if (type ~ /^(default|av|film|tv|music|adobe)$/) {
        print type
        exit 0
    } else {
        raise("Invalid type: " type)
    }
}
