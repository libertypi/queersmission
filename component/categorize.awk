#!/usr/bin/awk -f

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
	matchRegex(tolower(torrentName))

	if (is_dir) {
		prefix = (length(rootPath) + 2)
		walkdir(rootPath, files)
		sanitize_files(files)
		classify_files(files)
	}
	output_exit()
}


function classify_files(files, videos, f, n, i, j, words, nums, pats, connected)
{
	for (f in files) {
		matchRegex(f)
		if (f ~ /\.(avi|m2v|m4p|m4v|mkv|mov|mp2|mp4|mpeg|mpg|mpv|rm|rmvb|wmv|iso)$/) {
			videos[f]
		}
	}
	if (length(videos) >= 3) {
		for (f in videos) {
			i = split(f, words, /[0-9]+/, nums)
			for (j = 1; j < i; j++) {
				n = words[j]
				if (match(n, /\/[^/]+$/)) {
					n = substr(n, RSTART + 1)
				}
				pats[n][int(nums[j])] = f
			}
		}
		for (i in pats) {
			n = asorti(pats[i], nums, "@ind_num_asc")
			for (j = 2; j < n; j++) {
				if (nums[j - 1] == nums[j] - 1 && nums[j + 1] == nums[j] + 1) {
					connected[pats[i][nums[j]]]
					connected[pats[i][nums[j-1]]]
					connected[pats[i][nums[j+1]]]
				}
			}
		}
		if (length(connected) / length(videos) > 0.8) {
			output_exit("tv")
		}
	}
}

function matchRegex(string, i)
{
	for (i in avRegex) {
		if (string ~ avRegex[i]) {
			output_exit("av")
		}
	}
	if (string ~ /[^a-z0-9]([se][0-9]{1,2}|s[0-9]{1,2}e[0-9]{1,2}|ep[[:space:]_-]?[0-9]{1,3})[^a-z0-9]/) {
		output_exit("tv")
	} else if (string ~ /(^|[^a-z0-9])(acrobat|adobe|animate|audition|dreamweaver|illustrator|incopy|indesign|lightroom|photoshop|prelude|premiere)([^a-z0-9]|$)/) {
		output_exit("adobe")
	} else if (string ~ /(^|[^a-z0-9])(windows|mac(os)?|x(86|64)|(32|64)bit|v[0-9]+\.[0-9]+)([^a-z0-9]|$)|\.(zip|rar|exe|7z|dmg|pkg)$/) {
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
		break
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
			if ($3 == "d") {
				walkdir(fpath, files)
			} else {
				stat(fpath, fstat)
				files[tolower(substr(fpath, prefix))] = fstat["size"]
			}
		}
	}
}
