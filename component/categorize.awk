#!/usr/bin/awk -f
# Usage:
# awk -v av_regex="${av_regex}" -v torrentDir="${TR_TORRENT_DIR}" -v torrentName="${TR_TORRENT_NAME}" -f "${categorize}"

@load "readdir"
@load "filefuncs"

BEGIN {
	if (av_regex == "" || torrentDir == "" || torrentName == "") {
		print("[DEBUG] Awk: Invalid parameter.") > "/dev/stderr"
		exit 1
	}
	FS = "/"
	read_av_regex(av_regex, avRegex)
	rootPath = (torrentDir "/" torrentName)
	stat(rootPath, fstat)
	is_dir = (fstat["type"] == "directory" ? 1 : 0)
	match_name(tolower(torrentName))
	if (is_dir) {
		prefix = (length(rootPath) + 2)
		walkdir(rootPath, files)
		sanitize_files(files)
		classify_files(files)
	}
	output_exit()
}


function classify_files(files, videos, f, n, i, j, words, nums, groups, connected)
{
	# To identify TV Series:
	# Files will be stored as such:
	#   videos[1] = parent/string_03.mp4
	#   videos[2] = parent/string_04.mp4
	# After split, grouped as such:
	#   groups["string"][3] = 1
	#   groups["string"][4] = 2
	#   where 3, 4 are the matched numbers as integers,
	#   and 1, 2 are the indices of array videos.
	# After comparison, videos connected with
	# at least 2 of others will be saved as:
	#   connected[1]
	#   connected[2]
	#   where 1, 2 are the indices of array videos.
	# Then the length of "connected" will be the number of connected 
	# vertices. Because we only want to count isolated vertices,
	# there is no need to record actuarial connections.
	i = 0
	for (f in files) {
		match_file(f)
		if (f ~ /\.(avi|iso|m2v|m4p|m4v|mkv|mov|mp2|mp4|mpeg|mpg|mpv|rm|rmvb|wmv)$/) {
			videos[++i] = f
		}
	}
	if (i < 3) {
		return
	}
	for (i in videos) {
		n = split(videos[i], words, /[0-9]+/, nums)
		for (j = 1; j < n; j++) {
			f = words[j]
			if (match(f, /\/[^/]+$/)) {
				f = substr(f, RSTART + 1)
			}
			groups[f][int(nums[j])] = i
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
				}
			} else {
				i = 1
			}
		}
	}
	i = length(connected)
	j = length(videos)
	if (i / j >= 0.75) {
		printf("[DEBUG] Consecutive videos: %d / %d, categorized as TV Series.\n", i, j) > "/dev/stderr"
		output_exit("tv")
	} else {
		printf("[DEBUG] Consecutive videos: %d / %d, categorized as Films.\n", i, j) > "/dev/stderr"
	}
}

function match_file(string, i)
{
	# String: lower case.
	for (i in avRegex) {
		if (string ~ avRegex[i]) {
			output_exit("av")
		}
	}
	if (string ~ /[^a-z0-9]([se][0-9]{1,2}|s[0-9]{1,2}e[0-9]{1,2}|ep[[:space:]_-]?[0-9]{1,3})[^a-z0-9]/) {
		output_exit("tv")
	}
}

function match_name(torrent_name)
{
	# String: lower case.
	match_file(torrent_name)
	switch (torrent_name) {
	case /(^|[^a-z0-9])(acrobat|adobe|animate|audition|dreamweaver|illustrator|incopy|indesign|lightroom|photoshop|prelude|premiere)([^a-z0-9]|$)/:
		output_exit("adobe")
	case /(^|[^a-z0-9])(windows|mac(os)?|x(86|64)|(32|64)bit|v[0-9]+\.[0-9]+)([^a-z0-9]|$)|\.(7z|dmg|exe|gz|pkg|rar|tar|zip)$/:
		output_exit("software")
	}
}

function output_exit(type, dest, destDisply)
{
	switch (type) {
	case "av":
		dest = "/volume1/driver/Temp"
		break
	case "tv":
		dest = "/volume1/video/TV Series"
		break
	case "adobe":
		dest = "/volume1/homes/admin/Download/Adobe"
		break
	case "software":
		dest = "/volume1/homes/admin/Download"
		break
	default:
		dest = "/volume1/video/Films"
	}
	destDisply = dest
	if (! is_dir) {
		dest = (dest "/" (gensub(/\.[^.]*$/, "", "1", torrentName)))
	}
	printf "%s\000%s\000", dest, destDisply
	exit 0
}

function read_av_regex(av_regex, avRegex, n)
{
	n = 1
	while ((getline < av_regex) > 0) {
		avRegex[n++] = $0
	}
	close(av_regex)
}

function sanitize_files(files, f, t)
{
	t = (100 * 1024 ^ 2)
	for (f in files) {
		if (files[f] >= t) {
			for (f in files) {
				if (files[f] < t) {
					delete files[f]
				}
			}
			return
		}
	}
}

function walkdir(dir, files, fpath, fstat)
{
	while ((getline < dir) > 0) {
		if ($2 !~ /^[.#@]/) {
			fpath = (dir "/" $2)
			switch ($3) {
			case "f":
				stat(fpath, fstat)
				files[tolower(substr(fpath, prefix))] = fstat["size"]
				break
			case "d":
				walkdir(fpath, files)
			}
		}
	}
}
