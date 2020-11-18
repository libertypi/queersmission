@load "readdir"
@load "filefuncs"

BEGIN {
    if (REGEX_FILE == "" || TR_TORRENT_DIR == "" || TR_TORRENT_NAME == "") {
        print("[DEBUG] Awk: Invalid parameter.") > "/dev/stderr"
        output()
    }

    FS = "/"
    split("", file_to_size)
    split("", files)
    split("", videos)

    avRegex = read_av_regex(REGEX_FILE)
    rootPath = (TR_TORRENT_DIR "/" TR_TORRENT_NAME)
    stat(rootPath, rootStat)

    if (rootStat["type"] == "directory") {
        pathOffset = (length(TR_TORRENT_DIR) + 2)
        sizeReached = 0
        sizeThresh = (80 * 1024 ^ 2)
        walkdir(rootPath, file_to_size)
    } else {
        file_to_size[tolower(TR_TORRENT_NAME)] = rootStat["size"]
    }

    pattern_match(file_to_size, files, videos)

    if (length(videos) >= 3)
        series_match(videos)

    ext_match(file_to_size, files, videos)
}


function read_av_regex(file,  line)
{
    while ((getline line < file) > 0) {
        if (line ~ /\S/) {
            close(file)
            return line
        }
    }
    close(file)
    printf("[DEBUG] Reading regex from file failed: %s\n", file) > "/dev/stderr"
    return "^$"
}

function walkdir(dir, file_to_size,  fpath, fstat)
{
    while ((getline < dir) > 0) {
        if ($2 ~ /^[.#@]/) {
            continue
        }
        fpath = (dir "/" $2)
        switch ($3) {
        case "f":
            stat(fpath, fstat)
            if (fstat["size"] >= sizeThresh) {
                if (! sizeReached) {
                    delete file_to_size
                    sizeReached = 1
                }
            } else if (sizeReached) {
                continue
            }

            fpath = tolower(substr(fpath, pathOffset))
            if (match(fpath, /\/bdmv\/stream\/[^/]+\.m2ts$/)) {
                fpath = (substr(fpath, 1, RSTART) "bdmv/index.bdmv")
            }
            file_to_size[fpath] += fstat["size"]
            break
        case "d":
            walkdir(fpath, file_to_size)
        }
    }
    close(dir)
}

function pattern_match(file_to_size, files, videos,  i, n, p)
{
    # set 2 arrays: files, videos
    # files[1]: path
    # ...
    # (sorted by filesize (largest first))
    # videos[path]
    # ...
    n = asorti(file_to_size, files, "@val_num_desc")
    for (i = 1; i <= n; i++) {
        p = files[i]
        switch (p) {
        case /\.(3gp|asf|avi|bdmv|flv|iso|m(2?ts|4p|[24kop]v|p2|p4|pe?g|xf)|rm|rmvb|ts|vob|webm|wmv)$/:
            if (p ~ avRegex) {
                output("av")
            } else if (p ~ /\y([es]|ep[ _-]?|s[0-9]{2}e)[0-9]{2}\y/) {
                output("tv")
            }
            videos[p]
            break
        case /\y(acrobat|adobe|animate|audition|dreamweaver|illustrator|incopy|indesign|lightroom|photoshop|prelude|premiere)\y/:
            output("adobe")
        case /\y((32|64)bit|mac(os)?|windows|x64|x86)\y/:
            output()
        }
    }
}

function series_match(videos,  p, n, i, j, words, nums, groups, connected)
{
    # Scan multiple videos to identify consecutive digits:
    # input:
    #   videos[parent/string_03.mp4]
    #   videos[parent/string_04.mp4]
    #   ....
    # After split, grouped as:
    #   groups["string"][3] = parent/string_03.mp4
    #   groups["string"][4] = parent/string_04.mp4
    #   ....
    # Sort each subgroup by the digits:
    #   nums[1] = 3
    #   nums[2] = 4
    #   ....
    # If we found three consecutive digits, save the path to:
    #   connected[parent/string_03.mp4]
    #   connected[parent/string_04.mp4]
    #   ....
    #   The length of "connected" will be the number of connected vertices.

    for (p in videos) {
        n = split(p, words, /[0-9]+/, nums)
        for (i = 1; i < n; i++) {
            gsub(/.*\/|\s+/, "", words[i])
            groups[words[i] == "" ? i : words[i]][int(nums[i])] = p
        }
    }
    for (p in groups) {
        if (length(groups[p]) < 3) {
            continue
        }
        n = asorti(groups[p], nums, "@ind_num_asc")
        i = 1
        for (j = 2; j <= n; j++) {
            if (nums[j - 1] == nums[j] - 1) {
                i++
                if (i >= 3) {
                    if (i == 3) {
                        connected[groups[p][nums[j - 2]]]
                        connected[groups[p][nums[j - 1]]]
                    }
                    connected[groups[p][nums[j]]]
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

function ext_match(file_to_size, files, videos,  i, j, sum)
{
    for (i = 1; i in files && i <= 3; i++) {
        if (files[i] in videos) {
            j = "film"
        } else if (files[i] ~ /\.((al?|fl)ac|ape|m4a|mp3|ogg|wav|wma)$/) {
            j = "music"
        } else {
            j = "default"
        }
        sum[j] += file_to_size[files[i]]
    }
    asorti(sum, sum, "@val_num_desc")
    output(sum[1])
}

function output(type,  dest, display)
{
    switch (type) {
    case "av":
        display = "/volume1/driver/Temp"
        break
    case "film":
        display = "/volume1/video/Films"
        break
    case "tv":
        display = "/volume1/video/TV Series"
        break
    case "music":
        display = "/volume1/music/Download"
        break
    case "adobe":
        display = "/volume1/homes/admin/Download/Adobe"
        break
    default:
        display = "/volume1/homes/admin/Download"
    }

    if (rootStat["type"] == "file") {
        dest = (display "/" (gensub(/\.[^./]*$/, "", 1, TR_TORRENT_NAME)))
    } else {
        dest = display
    }

    printf "%s\000%s\000", dest, display
    exit 0
}
