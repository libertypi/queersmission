import json
import os.path as op
import re
from collections import defaultdict
from enum import Enum
from functools import cached_property, lru_cache
from posixpath import sep, splitext
from typing import Collection, Dict, Iterable, List, Optional, Tuple

DISC_EXTS = frozenset(("bdmv", "m2ts", "ifo", "vob", "evo"))


class Cat(Enum):
    """Enumeration for torrent categories."""

    DEFAULT = "dest-dir-default"
    MOVIES = "dest-dir-movies"
    TV_SHOWS = "dest-dir-tv-shows"
    MUSIC = "dest-dir-music"
    AV = "dest-dir-av"


def normstr(s: str) -> str:
    """Normalize a string for regex testing."""
    return s.replace("_", "-").lower()


def cached_re_test(key: str, *, flags: int = re.ASCII, maxsize: int = 512):
    """
    Decorator to create a cached regex test method for the given pattern key.
    Strings should be normalized with normstr() before testing.
    """

    def _factory(self):
        search = re.compile(self._patterns[key], flags).search

        @lru_cache(maxsize=maxsize)
        def re_test(s: str) -> bool:
            return search(s) is not None

        return re_test

    return cached_property(_factory)


class Categorizer:
    """Categorize torrents based on their file lists."""

    NAME_BONUS = 0.3

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
    mv_test = cached_re_test("movie_regex")

    @cached_property
    def disc_match(self):
        """Regex match to extract the top-level directory of a BD/DVD tree."""
        return re.compile(
            r"(.+?/)(?:bdmv/(?:index\.bdmv|stream/[^/]+\.m2ts)|(?:video-ts/)?(?:vts(?:-\d+)+|video-ts)\.(?:ifo|vob)|hvdvd-ts/[^/]+\.evo)",
            re.ASCII,
        ).fullmatch

    def infer(self, files: List[dict]) -> Cat:
        """
        Categorize the torrent based on the `files` list returned by the
        Transmission "torrent-get" API.
        """
        if not files:
            raise ValueError("Empty file list.")

        # Step 1: Classify by torrent name
        name_cat = self._classify_torrent_name(files)
        if name_cat == Cat.AV:
            return Cat.AV

        # Step 2: Process files and categorize by types
        type_bytes, videos, containers = self._process_files(files)

        # Step 3: Check if any video or container file matches AV
        if _test_paths(self.av_test, videos) or _test_paths(self.av_test, containers):
            return Cat.AV

        # Step 4: Now we rule out AV, score remaining categories
        scores = {
            Cat.TV_SHOWS: 0,
            Cat.MOVIES: 0,
            Cat.MUSIC: type_bytes["audio"],
            Cat.DEFAULT: type_bytes["other"],
        }

        # Classify videos into TV_SHOWS or MOVIES. Winner takes all: If any
        # video file is classified as TV_SHOWS, all videos are TV_SHOWS.
        if _test_paths(self.tv_test, videos) or _has_sequence(videos):
            scores[Cat.TV_SHOWS] += type_bytes["video"]
        else:
            scores[Cat.MOVIES] += type_bytes["video"]

        # Sub-classify containers into TV_SHOWS, MOVIES, or DEFAULT
        for path, size in containers.items():
            path = path[0].split(sep)
            if any(map(self.tv_test, path)):
                scores[Cat.TV_SHOWS] += size
            elif any(map(self.mv_test, path)):
                scores[Cat.MOVIES] += size
            else:
                scores[Cat.DEFAULT] += size

        # Step 5: Torrent name bonus (experimental)
        if name_cat is not None:
            scores[name_cat] += sum(type_bytes.values()) * self.NAME_BONUS

        # Step 6: Return the category with the highest score
        return max(scores, key=scores.get)

    def _process_files(self, files):
        """
        Process the file list and return type byte counts, video files, and
        container files.
        """
        type_bytes = {"video": 0, "container": 0, "audio": 0, "other": 0}
        videos = defaultdict(int)  # {(root, ext): size}
        containers = defaultdict(int)

        files, discs = self._prepare_filelist(files)

        for root, ext, size in files:

            if discs:
                # Collapse the whole BD/DVD tree into a single video entry.
                disc_root = next(filter(root.startswith, discs), None)
                if disc_root is not None:
                    type_bytes["video"] += size
                    videos[disc_root[:-1], ""] += size  # remove trailing slash
                    continue

            if ext in self.video_exts:
                type_bytes["video"] += size
                videos[root, ext] += size

            elif ext in self.container_exts:
                type_bytes["container"] += size
                containers[root, ext] += size

            elif ext in self.audio_exts:
                type_bytes["audio"] += size

            else:
                type_bytes["other"] += size

        return (type_bytes, self._drop_noise(videos), containers)

    def _prepare_filelist(self, files) -> Tuple[List[Tuple[str, str, int]], List[str]]:
        """
        Prepare the file list by normalizing paths and detecting video disc
        trees. Return a list of (root, ext, size) and a list of disc image
        directories (with trailing slash).
        """
        filelist = []
        discs = set()
        d_exts = DISC_EXTS

        for file in files:
            # All paths are normalized from this point on (same as normstr()).
            # Paths in torrents are always POSIX paths.
            path = file["name"].replace("_", "-").lower()
            root, ext = splitext(path)
            ext = ext[1:]  # strip leading dot
            filelist.append((root, ext, file["length"]))

            if ext in d_exts:
                m = self.disc_match(path)
                if m:
                    discs.add(m[1])  # directory with trailing slash

        return filelist, sorted(discs, key=len, reverse=True)

    @staticmethod
    def _drop_noise(path_bytes: Dict[Tuple[str, str], int]):
        """
        Drop small files that are likely to be noise, e.g. samples, trailers,
        ads, etc.
        """
        if len(path_bytes) < 2:
            return path_bytes

        # 5% of the largest video file, but no more than 50 MiB
        threshold = min(max(path_bytes.values()) * 0.05, 52428800)
        return {k: v for k, v in path_bytes.items() if v >= threshold}

    def _classify_torrent_name(self, files: List[dict]):
        """
        Classify the torrent by its name. Return None if no match.
        """
        # Torrent name is the first path segment of any file: the top-level
        # directory of a multi-file torrent, or the single file name otherwise.
        name = files[0]["name"].lstrip(sep).partition(sep)
        name = name[0] if name[1] else splitext(name[0])[0]  # test the stem
        name = normstr(name)
        if self.av_test(name):
            return Cat.AV
        if self.tv_test(name):
            return Cat.TV_SHOWS
        if self.mv_test(name):
            return Cat.MOVIES


def _test_paths(method, paths: Iterable[Tuple[str, str]]) -> bool:
    """
    Test if any of the given (root, ext) paths matches the given regex test
    method.
    """
    return any(method(s) for p in paths for s in p[0].split(sep))


def _has_sequence(paths: Collection[Tuple[str, str]]) -> bool:
    """
    Given a list of (root, ext) paths, check if there are three or more files
    under the same directory with consecutive numbers (1-99) in their names.
    """
    if len(paths) < 3:
        return False

    # 1 - 99
    seq_finder = re.compile(r"(?<![0-9])(?:0?[1-9]|[1-9][0-9])(?![0-9])").finditer

    # Organize files by their directories
    dir_files = defaultdict(list)
    for root, ext in paths:
        if ext not in DISC_EXTS:  # skip stray disc files
            dirname, _, stem = root.rpartition(sep)
            dir_files[dirname].append((stem, ext))

    # Check each directory for sequences
    groups = {}
    for files in dir_files.values():
        if len(files) < 3:
            continue
        groups.clear()
        for stem, ext in files:
            for m in seq_finder(stem):
                # Key: the parts before and after the digit, and the ext
                k = (stem[: m.start()], stem[m.end() :], ext)
                # bits      = ...00111000
                # bits >> 1 = ...00011100
                # bits >> 2 = ...00001110
                # AND       = ...00001000
                bits = groups.get(k, 0) | (1 << int(m[0]))
                if bits & (bits >> 1) & (bits >> 2):
                    return True
                groups[k] = bits
    return False
