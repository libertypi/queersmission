import json
import os.path as op
import re
from collections import defaultdict
from enum import Enum
from functools import cached_property, lru_cache
from posixpath import sep, splitext
from typing import Dict, List, Optional, Tuple


class Cat(Enum):
    """Enumeration for torrent categories."""

    DEFAULT = "dest-dir-default"
    MOVIES = "dest-dir-movies"
    TV_SHOWS = "dest-dir-tv-shows"
    MUSIC = "dest-dir-music"
    AV = "dest-dir-av"


def cached_re_test(key: str, *, flags: int = re.ASCII, maxsize: int = 512):
    """
    Decorator to create a cached regex test method for the given pattern key.
    The pattern is looked up from self._patterns.
    """

    def _factory(self):
        search = re.compile(self._patterns[key], flags).search

        @lru_cache(maxsize=maxsize)
        def cached_test(s: str) -> bool:
            return search(s) is not None

        return cached_test

    return cached_property(_factory)


class Categorizer:
    """Categorize a torrent based on its file list."""

    def __init__(self, patternfile: Optional[str] = None) -> None:

        if patternfile is None:
            patternfile = op.join(op.dirname(__file__), "patterns.json")
        with open(patternfile, "r", encoding="utf-8") as f:
            self._patterns: dict = json.load(f)

        self.video_exts = frozenset(self._patterns.pop("video_exts"))
        self.audio_exts = frozenset(self._patterns.pop("audio_exts"))
        self.container_exts = frozenset(self._patterns.pop("container_exts"))

    av_test = cached_re_test("av_regex", maxsize=1024)
    tv_test = cached_re_test("tv_regex")
    vd_test = cached_re_test("video_regex")

    def categorize(self, files: List[dict]) -> Cat:
        """
        Categorize the torrent based on the `files` list returned by the
        Transmission "torrent-get" API.
        """
        if not files:
            raise ValueError("Empty file list.")

        # Process files and categorize by types
        type_bytes, videos, containers = self._process_files(files)

        # Classify and score by types
        scores = {c: 0 for c in Cat}

        scores[self._classify_videos(videos)] += type_bytes["video"]
        scores[self._classify_containers(containers)] += type_bytes["container"]
        scores[Cat.MUSIC] += type_bytes["audio"]
        scores[Cat.DEFAULT] += type_bytes["other"]

        # torrent name bonus
        c = self._classify_torrent_name(files)
        if c is not None:
            if scores[c]:
                scores[c] *= 1.3  # boost by 30%
            else:
                scores[c] = sum(type_bytes.values()) * 0.3

        # Return the category with the highest score
        return max(scores, key=scores.get)

    def _process_files(self, files: List[dict]):

        type_bytes = {"video": 0, "container": 0, "audio": 0, "other": 0}
        video_bytes = defaultdict(int)  # {(root, ext): size}
        containers = []  # [(root, ext)]

        for file in files:
            # All paths are normalized from this point on. Same as normstr().
            # File paths in torrents are always POSIX paths.
            root, ext = splitext(file["name"].replace("_", "-").lower())
            ext = ext[1:]  # strip leading dot
            size = file["length"]

            if ext in self.video_exts:
                # collapse BDMV/DVD trees into their parent directory
                if ext == "m2ts":
                    root = re.sub(r"/bdmv/stream/[^/]+$", "", root, 1, re.A)
                elif ext == "vob":
                    root = re.sub(r"/([^/]*vts[\d-]+|video_ts)$", "", root, 1, re.A)

                type_bytes["video"] += size
                video_bytes[root, ext] += size

            elif ext in self.container_exts:
                type_bytes["container"] += size
                containers.append((root, ext))

            elif ext in self.audio_exts:
                type_bytes["audio"] += size

            else:
                type_bytes["other"] += size

        return (type_bytes, self._drop_video_noise(video_bytes), containers)

    @staticmethod
    def _drop_video_noise(video_bytes: Dict[Tuple[str, str], int]):
        """
        Drop small video files that are likely to be noise, e.g. samples,
        trailers, ads, etc.
        """
        if len(video_bytes) < 2:
            return list(video_bytes)

        # 5% of the largest video file, but no more than 50 MiB
        threshold = min(max(video_bytes.values()) * 0.05, 52428800)
        return [k for k, v in video_bytes.items() if v >= threshold]

    def _classify_torrent_name(self, files: List[dict]):
        """
        Classify the torrent based on its name.
        """
        # Torrent name is the file name of a single file torrent, or the
        # top-level directory name otherwise.
        name = files[0]["name"].lstrip(sep).partition(sep)
        name = name[0] if name[1] else splitext(name[0])[0]  # test the stem
        name = normstr(name)
        if self.av_test(name):
            return Cat.AV
        if self.tv_test(name):
            return Cat.TV_SHOWS
        if self.vd_test(name):
            return Cat.MOVIES

    def _classify_videos(self, videos: List[Tuple[str, str]]):
        """
        Classify video files into AV, TV_SHOWS, or MOVIES. Winner takes all.
        """
        tv_found = self._has_sequence(videos)
        for root, _ in videos:
            for s in root.split(sep):
                if self.av_test(s):
                    return Cat.AV
                if not tv_found and self.tv_test(s):
                    tv_found = True
        return Cat.TV_SHOWS if tv_found else Cat.MOVIES

    def _classify_containers(self, containers: List[Tuple[str, str]]):
        """
        Classify container files into AV, MOVIES, or DEFAULT.
        """
        vd_found = False
        for root, _ in containers:
            for s in root.split(sep):
                if self.av_test(s):
                    return Cat.AV
                if not vd_found and self.vd_test(s):
                    vd_found = True
        return Cat.MOVIES if vd_found else Cat.DEFAULT

    @staticmethod
    def _has_sequence(paths: List[Tuple[str, str]]):
        """
        Given a list of (root, ext) file paths, check if there are files under
        the same directory with sequential numbering in their names.
        """
        if len(paths) < 2:
            return False

        # 1 - 999
        seq_finder = re.compile(
            r"(?<![0-9])(?:[1-9][0-9]{0,2}|0[1-9][0-9]?|00[1-9])(?![0-9])"
        ).finditer

        # Organize files by their directories
        dir_files = defaultdict(list)
        for root, ext in paths:
            dirname, _, stem = root.rpartition(sep)
            dir_files[dirname].append((stem, ext))

        # Iterate each directory
        groups = defaultdict(set)
        for files in dir_files.values():
            if len(files) < 2:
                continue
            groups.clear()
            for stem, ext in files:
                for m in seq_finder(stem):  # Check the stem
                    # Key: the parts before and after the digit, and the ext
                    g = groups[stem[: m.start()], stem[m.end() :], ext]
                    g.add(int(m[0]))
                    # Check if sequence numbers are consecutive
                    if 1 < len(g) == max(g) - min(g) + 1:
                        return True
        return False


def normstr(s: str) -> str:
    """
    Normalize a string for regex testing by replacing "_" with "-" and
    converting to lowercase.
    """
    return s.replace("_", "-").lower()
