@load "readdir"
@load "filefuncs"

# Usage: awk -v av_regex="${av_regex}" -v torrentDir="${TR_TORRENT_DIR}" -v torrentName="${TR_TORRENT_NAME}" -f "${categorize}"

BEGIN {
    if (av_regex == "" || torrentDir == "" || torrentName == "") {
        print("[DEBUG] Awk: Invalid parameter.") > "/dev/stderr"
        output()
    }

    FS = "/"
    read_av_regex(av_regex)
    rootPath = (torrentDir "/" torrentName)
    stat(rootPath, rootStat)

    files[1] = tolower(torrentName)
    pattern_match(files)

    if (rootStat["type"] == "directory") {
        prefix = (length(rootPath) + 2)
        minSize = (80 * 1024 ^ 2)
        sizeReached = 0
        walkdir(rootPath, fsize)
        asorti(fsize, files, "@val_num_desc")
        pattern_match(files)
    } else {
        fsize[files[1]] = rootStat["size"]
    }

    ext_match(files)
}


function ext_match(files, i, j, sum)
{
    for (i = 1; i in files && i <= 3; i++) {
        switch (gensub(/^.*\./, "", 1, files[i])) {
        case /^((bd|w)mv|3gp|asf|avi|flv|iso|m(2?ts|4p|[24kop]v|p([24]|e?g)|xf)|rm(vb)?|ts|vob|webm)$/:
            j = "film"
            break
        case /^((al?|fl)ac|ape|m4a|mp3|ogg|wav|wma)$/:
            j = "music"
            break
        default:
            j = "default"
        }
        sum[j] += fsize[files[i]]
    }
    asorti(sum, sum, "@val_num_desc")
    output(sum[1])
}

function output(type, dest, destDisply)
{
    switch (type) {
    case "av":
        dest = "/volume1/driver/Temp"
        break
    case "film":
        dest = "/volume1/video/Films"
        break
    case "tv":
        dest = "/volume1/video/TV Series"
        break
    case "music":
        dest = "/volume1/music/Download"
        break
    case "adobe":
        dest = "/volume1/homes/admin/Download/Adobe"
        break
    default:
        dest = "/volume1/homes/admin/Download"
    }
    destDisply = dest
    if (rootStat["type"] == "file") {
        dest = (dest "/" (gensub(/\.[^.\/]*$/, "", 1, torrentName)))
    }
    printf "%s\000%s\000", dest, destDisply
    exit 0
}

function pattern_match(files, videos, n, i, j)
{
    n = length(files)
    i = 0
    for (j = 1; j <= n; j++) {
        if (files[j] ~ avRegex) {
            output("av")
        }
        switch (files[j]) {
        case /\y([se][0-9]{1,2}|s[0-9]{1,2}e[0-9]{1,2}|ep[[:space:]_-]?[0-9]{1,3})\y/:
            output("tv")
        case /\.(avi|iso|m(4p|[24kop]v|p([24]|e?g))|rm(vb)?|wmv)$|bdmv\/index\.bdmv$/:
            videos[++i] = files[j]
        }
    }
    if (n == 1) {
        switch (files[1]) {
        case /\y(acrobat|adobe|animate|audition|dreamweaver|illustrator|incopy|indesign|lightroom|photoshop|prelude|premiere)\y/:
            output("adobe")
        case /\y(windows|mac(os)?|x(86|64)|(32|64)bit|v[0-9]+\.[0-9]+)\y/:
            output()
        }
    } else if (i >= 3) {
        series_match(videos)
    }
}

function read_av_regex(av_regex)
{
    while ((getline avRegex < av_regex) > 0) {
        if (avRegex ~ /\S/) {
            close(av_regex)
            return
        }
    }
    close(av_regex)
    printf("[DEBUG] Reading regex from file failed: %s\n", av_regex) > "/dev/stderr"
    avRegex = "^$"
}

function series_match(videos, f, n, i, j, words, nums, groups, connected)
{
    # Scan multiple videos to identify consecutive digits:
    # Files will be stored as:
    #   videos[1] = parent/string_03.mp4
    #   videos[2] = parent/string_04.mp4
    # After split, grouped as:
    #   groups["string"][3] = 1
    #   groups["string"][4] = 2
    #   where 3, 4 are the matched numbers as integers, and 1, 2 are the indices of array videos.
    # After comparison, videos connected with at least 2 of others will be saved as:
    #   connected[1]
    #   connected[2]
    #   where 1, 2 are the indices of array videos.
    # The length of "connected" will be the number of connected vertices.
    for (i in videos) {
        n = split(videos[i], words, /[0-9]+/, nums)
        for (j = 1; j < n; j++) {
            gsub(/.*\/|\s+/, "", words[j])
            groups[words[j] == "" ? j : words[j]][int(nums[j])] = i
        }
    }
    for (f in groups) {
        if (length(groups[f]) < 3) {
            continue
        }
        n = asorti(groups[f], nums, "@ind_num_asc")
        i = 1
        for (j = 2; j <= n; j++) {
            if (nums[j - 1] == nums[j] - 1) {
                i++
                if (i >= 3) {
                    if (i == 3) {
                        connected[groups[f][nums[j - 2]]]
                        connected[groups[f][nums[j - 1]]]
                    }
                    connected[groups[f][nums[j]]]
                    if (length(connected) >= 3) {
                        output("tv")
                    }
                }
            } else {
                i = 1
            }
        }
    }
}

function walkdir(dir, fsize, fpath, fstat)
{
    while ((getline < dir) > 0) {
        if ($2 ~ /^[.#@]/) {
            continue
        }
        fpath = (dir "/" $2)
        switch ($3) {
        case "f":
            stat(fpath, fstat)
            if (fstat["size"] >= minSize) {
                if (! sizeReached) {
                    delete fsize
                    sizeReached = 1
                }
            } else if (sizeReached) {
                continue
            }
            fpath = tolower(substr(fpath, prefix))
            if (match(fpath, /\ybdmv\/stream\/[^.\/]+\.m2ts$/)) {
                fpath = (substr(fpath, 1, RSTART + 4) "index.bdmv")
            }
            fsize[fpath] += fstat["size"]
            break
        case "d":
            walkdir(fpath, fsize)
        }
    }
    close(dir)
}
