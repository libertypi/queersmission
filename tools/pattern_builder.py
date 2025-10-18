#!/usr/bin/env python3

"""
Pattern Builder - Generate patterns.json for Queersmission
==========================================================

Regex Requirements:
-------------------
- All regular expressions must be lowercased.
- All "_" characters should be replaced with "-".
- Matching will be using ASCII-only mode so CJK characters construct boundaries.

Data Files:
-----------
- footprints-statistics.json: Statistical data from the footprints project for
  building regex patterns.
- google-10000-english-usa-no-swears.txt, common-female-names.txt,
  common-male-names.txt: Common English words to be excluded from the keywords.
- prefixes-include.txt: Prefixes to include in the regex.
- prefixes-exclude.txt: Prefixes to exclude from the regex.
- keywords-include.txt: Keywords to include in the regex.
- keywords-exclude.txt: Keywords to exclude from the regex.

Author:
-------
- David P.
"""

import argparse
import json
import re
import shutil
from itertools import chain, filterfalse, islice
from pathlib import Path

from regen import Regen

script_dir = Path(__file__).resolve().parent
entry_dir = script_dir.parent

# fmt: off
VIDEO_EXTS = {
    "3g2", "3gp", "3gp2", "3gpp", "amv", "asf", "avi", "divx", "dpg", "drc",
    "evo", "f4a", "f4b", "f4p", "f4v", "flv", "ifo", "k3g", "m1v", "m2t",
    "m2ts", "m2v", "m4p", "m4v", "mkv", "mov", "mp2v", "mp4", "mpe", "mpeg",
    "mpeg2", "mpg", "mpv", "mpv2", "mts", "mxf", "nsr", "nsv", "ogm", "ogv",
    "ogx", "qt", "ram", "rm", "rmvb", "rpm", "skm", "svi", "swf", "tp", "tpr",
    "ts", "vid", "viv", "vob", "webm", "wm", "wmp", "wmv", "wtv"
}
AUDIO_EXTS = {
    "aac", "ac3", "aif", "aifc", "aiff", "alac", "amr", "ape", "caf", "cda",
    "cue", "dsf", "dts", "dtshd", "eac3", "flac", "m1a", "m2a", "m3u", "m3u8",
    "m4a", "m4b", "mka", "mod", "mp2", "mp3", "mpa", "mpc", "oga", "ogg",
    "opus", "pls", "ra", "tak", "tta", "wav", "wax", "wma", "wv", "xspf"
}
CONTAINER_EXTS = {"7z", "bin", "img", "iso", "mdf", "mds", "nrg", "rar", "zip"}
MOVIE_REGEX = r"\b((10|12|8)bit|(10|4)80[ip]|(21|3)60p|(43|7)20p|1440p|4k|576p|8k|[hx]26[45]|atmos|av[1c]|b([dr]rip|lu[\s-]?ray)|dovi|dts|dvd(5|9|rip|scr)?|hd(r|r10|tv)|hevc|mpeg2?|ntsc|remux|truehd|uhd|web[\s-]?(dl|rip)|xvid)\b"
TV_REGEX = r"\b(s(0[1-9]|[1-3]\d)|ep(0[1-9]|[1-9]\d|1\d\d)|s(0?[1-9]|[1-3]\d)[\s.-]?e(0?[1-9]|[1-9]\d|1\d\d))\b"
AV_TEMPLATE = r"\b({keywords}|[0-9]{{,5}}({prefixes})-?[0-9]{{2,8}}([a-z]|f?hd)?)\b"
# SOFTWARE_REGEX = r"\b(apk|deb|dmg|exe|msi|pkg|rpm|adobe|microsoft|windows|x(64|86)|(32|64)bit|v\d+(\.\d+)+)\b"
# fmt: on


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-n",
        dest="max_keywords",
        type=int,
        default=150,
        help="Maximum number of keywords to draw from data (default: %(default)s).",
    )
    parser.add_argument(
        "-m",
        dest="max_prefixes",
        type=int,
        default=4000,
        help="Maximum number of prefixes to draw from data (default: %(default)s).",
    )
    return parser.parse_args()


def get_common_words():
    # https://github.com/first20hours/google-10000-english
    # https://www.cs.cmu.edu/Groups/AI/areas/nlp/corpora/names/
    files = (
        "google-10000-english-usa-no-swears.txt",
        "common-female-names.txt",
        "common-male-names.txt",
    )
    result = set()
    for file in files:
        with open(script_dir.joinpath(file), "r", encoding="utf-8") as f:
            result.update(map(str.lower, filter(str.isalpha, map(str.strip, f))))
    return result


def read_pattern_file(filename: str):
    path = script_dir.joinpath(filename)
    try:
        with open(path, "r+", encoding="utf-8") as f:
            old_data = f.read().splitlines()
            new_data = map(str.lower, filter(None, map(str.strip, old_data)))
            new_data = sorted(set(new_data))
            if new_data != old_data:
                f.seek(0)
                f.writelines(l + "\n" for l in new_data)
                f.truncate()
                print(f"Updated: {filename}")
    except FileNotFoundError:
        open(path, "w").close()
        return []
    else:
        return new_data


def build_regex(
    name: str,
    source: dict,
    max_items: int,
    ex_set: set = None,
    ex_lst: tuple = (),
) -> str:
    # ex_set: a set of strings to be excluded (literal match)
    # ex_lst: a list of regex to filter the source (regex match)

    assert name in ("keywords", "prefixes")

    # Data from footprints, sorted by frequency
    source: dict = source[name]
    data: list = sorted(
        (source.keys() - ex_set) if ex_set else source,
        key=source.get,
        reverse=True,
    )

    # Inclusion and exclusion pattern files
    include = read_pattern_file(f"{name}-include.txt")
    exclude = read_pattern_file(f"{name}-exclude.txt")

    # Remove anything that overlaps the pattern files or 'ex_lst', then slice
    # the list to `max_items`
    regex = "|".join(chain(include, exclude, ex_lst))
    if regex:
        data = filterfalse(re.compile(regex).fullmatch, data)
        data = list(islice(data, max_items))
    else:
        data = data[:max_items]

    print(
        "Selected {:,} of {:,} {} from source. Frequency: [{}, {}], coverage: {:.1%} ".format(
            len(data),
            len(source),
            name,
            source[data[-1]],
            source[data[0]],
            sum(map(source.get, data)) / sum(source.values()),
        )
    )

    # Add include list back and sort
    data.extend(include)
    data.sort()
    print(f"{len(data):,} {name} are included to build the regex.")

    # Generate and verify the regex
    regen = Regen(data)
    regex = regen.to_regex(omitOuterParen=True)

    concat = "|".join(data)
    diff = len(regex) - len(concat)
    if diff > 0:
        print(
            f"Optimized regex is {diff} characters longer "
            "than simple concatenation; using the latter."
        )
        regex = concat
    else:
        regen._verify()
        print(f"Final regex length for {name}: {len(regex)} ({diff})")

    if not regex:
        raise ValueError(f"Generated regex for {name} is empty.")
    return regex


def validation(av_regex: str):

    for r in (MOVIE_REGEX, TV_REGEX, av_regex):
        if not r:
            raise ValueError("One of the regex is empty.")
        if r.lower() != r or "_" in r:
            raise ValueError("Regex must be lowercased and contain no '_' character.")
        try:
            re.compile(r, flags=re.ASCII)
        except re.error as e:
            raise ValueError(f"Invalid regex: {r}\n{e}")

    all_exts = (VIDEO_EXTS, AUDIO_EXTS, CONTAINER_EXTS)
    if not all(all_exts):
        raise ValueError("One of the extension sets is empty.")
    if not all(s.lower() == s and s.isalnum() for s in chain.from_iterable(all_exts)):
        raise ValueError("Invalid entry found in extension sets.")
    if len(set.union(*all_exts)) != sum(map(len, all_exts)):
        raise ValueError("Intersection found between extension sets.")


def main():

    args = parse_args()

    src = script_dir.joinpath("footprints-statistics.json")
    dst = entry_dir.joinpath("queersmission/patterns.json")
    print(f"Source: {src}\nOutput: {dst}")

    # Update data from footprints
    try:
        shutil.copy(entry_dir.parent.joinpath("footprints/data", src.name), src)
    except FileNotFoundError:
        print("Warning: Unable to update data file from footprints.")

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Build regex for keywords
    keywords = build_regex(
        name="keywords",
        source=data,
        max_items=args.max_keywords,
        ex_set=get_common_words(),
    )
    # Build regex for prefixes, excluded keywords
    prefixes = build_regex(
        name="prefixes",
        source=data,
        max_items=args.max_prefixes,
        ex_lst=(keywords,),
    )
    # Construct
    av_regex = AV_TEMPLATE.format(keywords=keywords, prefixes=prefixes)

    # Validation
    validation(av_regex)

    # Save to JSON
    result = {
        "video_exts": sorted(VIDEO_EXTS),
        "audio_exts": sorted(AUDIO_EXTS),
        "container_exts": sorted(CONTAINER_EXTS),
        "movie_regex": MOVIE_REGEX,
        "tv_regex": TV_REGEX,
        "av_regex": av_regex,
    }
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(result, f, separators=(",", ":"))


if __name__ == "__main__":
    main()
