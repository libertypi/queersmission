import json
import os.path as op
import re
from collections import defaultdict
from enum import Enum
from posixpath import splitext as posix_splitext
from typing import List, Optional, Tuple

from .utils import re_compile

VIDEO_THRESH = 52428800  # 50 MiB
_VIDEO, _AUDIO, _DEFAULT = range(3)
_REFLAGS = re.ASCII | re.IGNORECASE


class Cat(Enum):
    """Enumeration for categorizing torrent files."""

    DEFAULT = "default"
    MOVIES = "movies"
    TV_SHOWS = "tv-shows"
    MUSIC = "music"
    AV = "av"


class Categorizer:
    __slots__ = ("video_exts", "audio_exts", "sw_re", "tv_re", "av_re")

    def __init__(self, patternfile: Optional[str] = None) -> None:
        """Initialize the Categorizer with data from the pattern file."""
        if patternfile is None:
            patternfile = op.join(op.dirname(__file__), "patterns.json")

        with open(patternfile, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not all(data.values()):
            raise ValueError(f"Empty entry in pattern file: {patternfile}")

        self.video_exts = frozenset(data["video_exts"])
        self.audio_exts = frozenset(data["audio_exts"])
        self.sw_re = data["software_regex"]
        self.tv_re = data["tv_regex"]
        self.av_re = data["av_regex"]

    def categorize(self, files: List[dict]):
        """
        Categorize the torrent based on the `files` list returned by the
        Transmission "torrent-get" API.
        """
        # Does the torrent name pass the AV test? Torrent name is the file name
        # if there is only one file, or the root directory name otherwise. File
        # paths are always POSIX paths.
        name = files[0]["name"].lstrip("/").partition("/")
        name = name[0] if name[1] else posix_splitext(name[0])[0]
        if re_test(self.av_re, name):
            return Cat.AV

        # The most common file type, and a list of videos (root, ext)
        main_type, videos = self._analyze_file_types(files)

        # Does any of the videos pass the AV test?
        segments = {name}
        for path in videos:
            for s in path[0].split("/"):
                if s not in segments:
                    if re_test(self.av_re, s):
                        return Cat.AV
                    segments.add(s)

        # Categorize by the main file type
        if main_type == _VIDEO:
            # Are they TV_SHOWS or MOVIES?
            if any(re_test(self.tv_re, s) for s in segments):
                return Cat.TV_SHOWS
            if self._find_file_groups(videos):
                return Cat.TV_SHOWS
            return Cat.MOVIES

        if main_type == _AUDIO:
            return Cat.MUSIC

        if main_type == _DEFAULT:
            return Cat.DEFAULT

        raise ValueError(f'Unexpected "main_type": {main_type}')

    def _analyze_file_types(self, files: List[dict]) -> Tuple[int, list]:
        """Analyze and categorize files by type, finding the most common
        type."""
        type_size = defaultdict(int)
        video_size = defaultdict(int)

        for file in files:
            root, ext = posix_splitext(file["name"])
            ext = ext[1:].lower()  # Strip leading dot

            if ext in self.video_exts:
                if ext == "m2ts":
                    root = re_sub(r"/bdmv/stream/[^/]+$", "", root)
                elif ext == "vob":
                    root = re_sub(r"/([^/]*vts[0-9_]+|video_ts)$", "", root)
                file_type = _VIDEO
            elif ext in self.audio_exts:
                file_type = _AUDIO
            elif ext == "iso" and not re_test(self.sw_re, root):
                # ISO could be software or video image
                file_type = _VIDEO
            else:
                file_type = _DEFAULT

            size = file["length"]
            type_size[file_type] += size
            if file_type == _VIDEO:
                video_size[root, ext] += size

        # Apply a conditional threshold for videos
        if any(f["length"] >= VIDEO_THRESH for f in files):
            videos = (k for k, v in video_size.items() if v >= VIDEO_THRESH)
        else:
            videos = video_size

        return (
            max(type_size, key=type_size.get),
            sorted(videos, key=video_size.get, reverse=True),
        )

    @staticmethod
    def _find_file_groups(file_list: List[Tuple[str, str]], group_size: int = 3):
        """Identify groups of files in the same directory that appear to be part
        of a sequence. `group_size` defines the minimum size of a group.
        """
        if len(file_list) < group_size:
            return False

        seq_finder = re.compile(r"(?<![0-9])(?:0?[1-9]|[1-9][0-9])(?![0-9])").finditer
        dir_files = defaultdict(list)
        groups = defaultdict(set)

        # Organize files by their directories
        for root, ext in file_list:
            dirname, _, stem = root.rpartition("/")
            dir_files[dirname].append((stem, ext))

        for files in dir_files.values():
            if len(files) < group_size:
                continue
            groups.clear()
            for stem, ext in files:
                for m in seq_finder(stem):
                    # Key: the part before, and after the digit, and the ext
                    g = groups[stem[: m.start()], stem[m.end() :], ext]
                    g.add(int(m[0]))
                    if len(g) >= group_size:
                        return True
        return False


def re_test(pattern: str, string: str) -> bool:
    """Replace all '_' with '-', then perform an ASCII-only and case-insensitive
    test."""
    return re_compile(pattern, _REFLAGS).search(string.replace("_", "-")) is not None


def re_sub(pattern: str, repl, string: str) -> str:
    """Perform an ASCII-only and case-insensitive substitution."""
    return re_compile(pattern, _REFLAGS).sub(repl, string)
