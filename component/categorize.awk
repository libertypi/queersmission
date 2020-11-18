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

    av_regex = read_regex(REGEX_FILE)
    root_path = (TR_TORRENT_DIR "/" TR_TORRENT_NAME)
    stat(root_path, root_stat)

    if (root_stat["type"] == "directory") {
        path_offset = (length(TR_TORRENT_DIR) + 2)
        size_reached = 0
        size_thresh = (80 * 1024 ^ 2)
        walkdir(root_path, file_to_size)
    } else {
        file_to_size[tolower(TR_TORRENT_NAME)] = root_stat["size"]
    }

    pattern_match(file_to_size, files, videos)

    if (length(videos) >= 3)
        series_match(videos)

    ext_match(file_to_size, files, videos)
}


function read_regex(file,  line)
{
    while ((getline line < file) > 0) {
        if (line ~ /\S/) {
            close(file)
            return line
        }
    }
    close(file)
    printf("[DEBUG] Awk: Reading regex failed: %s\n", file) > "/dev/stderr"
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
            if (fstat["size"] >= size_thresh) {
                if (! size_reached) {
                    delete file_to_size
                    size_reached = 1
                }
            } else if (size_reached) {
                continue
            }

            fpath = tolower(substr(fpath, path_offset))
            if (match(fpath, /\/bdmv\/stream\/[^/]+\.m2ts$/)) {
                fpath = (substr(fpath, 1, RSTART) "bdmv/index.bdmv")
            } else if (match(fpath, /\/video_ts\/[^/]+\.vob$/)) {
                fpath = (substr(fpath, 1, RSTART) "video_ts/video_ts.vob")
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
            if (p ~ av_regex) {
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

function series_match(videos,  p, n, i, j, words, nums, groups)
{
    # Scan multiple videos to identify consecutive digits:
    # input:
    #   videos[parent/string_05.mp4]
    #   videos[parent/string_06.mp4]
    #   videos[parent/string_04string_05.mp4]
    #   ....
    # After split, grouped as:
    #   groups[1, "string"][5] (parent/string_05.mp4)
    #   groups[1, "string"][6] (parent/string_06.mp4)
    #   groups[1, "string"][4] (parent/string_04string_05.mp4)
    #   groups[2, "string"][5] (parent/string_04string_05.mp4)
    #   ....
    #   (same file would never appear in the same group)
    # For each group, sort its subgroup by the digits:
    #   nums[1] = 4
    #   nums[2] = 5
    #   nums[3] = 6
    #   ....
    # If we found three consecutive digits in one group,
    # identify as TV Series.

    for (p in videos) {
        n = split(p, words, /[0-9]+/, nums)
        for (i = 1; i < n; i++) {
            gsub(/.*\/|\s+/, "", words[i])
            groups[i, words[i]][int(nums[i])]
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
                if (++i == 3) {
                    output("tv")              
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

    if (root_stat["type"] == "file") {
        dest = (display "/" (gensub(/\.[^./]*$/, "", 1, TR_TORRENT_NAME)))
    } else {
        dest = display
    }

    printf "%s\000%s\000", dest, display
    exit 0
}
