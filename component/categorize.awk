# AWK program for torrent categorization.
# Author: David Pi
#
# Input variables (passed via "-v" arguments):
#   TR_TORRENT_DIR, TR_TORRENT_NAME, regexfile, dir_default,
#   dir_av, dir_film, dir_tv, dir_music, dir_adobe
#
# Output (null-terminated):
#   (root, path)

@load "readdir"
@load "filefuncs"

BEGIN {
    if (TR_TORRENT_DIR == "" || TR_TORRENT_NAME == "" || regexfile == "" || dir_default == "") {
        printf("[AWK]: Invalid inputs (TR_TORRENT_DIR: '%s', TR_TORRENT_NAME: '%s', regexfile: '%s', dir_default: '%s')\n",
            TR_TORRENT_DIR, TR_TORRENT_NAME, regexfile, dir_default) > "/dev/stderr"
        exit 1
    }
    split("", sizedict)
    split("", filelist)
    split("", videoset)
    FS = "/"

    av_regex = read_regex(regexfile)
    tr_path = (TR_TORRENT_DIR "/" TR_TORRENT_NAME)
    stat(tr_path, tr_stat)
    tr_isdir = (tr_stat["type"] == "directory")

    if (tr_isdir) {
        path_offset = (length(TR_TORRENT_DIR) + 2)
        size_reached = 0
        size_thresh = (80 * 1024 ^ 2)
        walkdir(tr_path, sizedict)
    } else {
        sizedict[tolower(TR_TORRENT_NAME)] = tr_stat["size"]
    }

    pattern_match(sizedict, filelist, videoset)

    if (length(videoset) >= 3)
        series_match(videoset)

    ext_match(sizedict, filelist, videoset)
}


function read_regex(fpath,  s)
{
    while ((getline s < fpath) > 0) {
        if (s ~ /\S/) {
            close(fpath)
            gsub(/^\s+|\s+$/, "", s)
            return s
        }
    }
    close(fpath)
    printf("[AWK]: Reading regex from '%s' failed.\n", fpath) > "/dev/stderr"
    return "^$"
}

function walkdir(dir, sizedict,  fpath, fstat)
{
    # array sizedict:
    # sizedict[path] = size
    while ((getline < dir) > 0) {
        if ($2 ~ /^[.#@]/) continue
        fpath = (dir "/" $2)
        switch ($3) {
        case "f":
            stat(fpath, fstat)
            if (fstat["size"] >= size_thresh) {
                if (! size_reached) {
                    delete sizedict
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
            sizedict[fpath] += fstat["size"]
            break
        case "d":
            walkdir(fpath, sizedict)
        }
    }
    close(dir)
}

function pattern_match(sizedict, filelist, videoset,  i, j, s)
{
    # set 2 arrays: filelist, videoset
    # filelist[1]: path
    # (sorted by filesize (largest first))
    # videoset[path]
    j = asorti(sizedict, filelist, "@val_num_desc")
    for (i = 1; i <= j; i++) {
        s = filelist[i]
        if (s ~ /\.(3gp|asf|avi|bdmv|flv|iso|m(2?ts|4p|[24kop]v|p2|p4|pe?g|xf)|rm|rmvb|ts|vob|webm|wmv)$/) {
            if (s ~ av_regex) {
                output("av")
            } else if (s ~ /\y([es]|ep[ _-]?|s([1-9][0-9]|0?[1-9])e)([1-9][0-9]|0?[1-9])\y/) {
                output("tv")
            }
            videoset[s]
        }
    }
    s = filelist[1]
    if (s ~ /\.(7z|[di]mg|[rt]ar|exe|gz|iso|zip)$/) {
        if (s ~ /(^|[^a-z])(acrobat|adobe|animate|audition|dreamweaver|illustrator|incopy|indesign|lightroom|photoshop|prelude|premiere)($|[^a-z])/) {
            output("adobe")
        } else if (s ~ /(^|[^a-z0-9])((32|64)bit|mac(os)?|windows|microsoft|x64|x86)($|[^a-z0-9])/) {
            output()
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

function output(type,  root, path, groups)
{
    switch (type) {
    case "av":
        root = dir_av
        break
    case "film":
        root = dir_film
        break
    case "tv":
        root = dir_tv
        break
    case "music":
        root = dir_music
        break
    case "adobe":
        root = dir_adobe
        break
    default:
        root = dir_default
    }
    if (root == "")
        root = dir_default
    if (tr_isdir) {
        path = root
    } else {
        path = (root "/" gensub(/^(.+)\.[^./]+$/, "\\1", 1, TR_TORRENT_NAME))
    }
    printf "%s\000%s\000", root, path
    exit 0
}
