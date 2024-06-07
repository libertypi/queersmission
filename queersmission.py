#!/usr/bin/env python3

"""
Queersmission - Smart Categorization for Transmission
=====================================================

Description:
------------
Queersmission is a post-download script for the Transmission client. It allows
users to dedicate storage for torrent uploading and to copy the finished
downloads to user destinations.

Features:
---------
- Smart torrent categorization.
- Automatic storage management based on quota settings.

Author:
-------
- David Pi
- GitHub: https://github.com/libertypi/queersmission
"""

import base64
import enum
import json
import logging
import os
import os.path as op
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from functools import lru_cache
from posixpath import splitext as posix_splitext
from typing import List, Optional, Set, Tuple

import requests

logger = logging.getLogger(__name__)
script_root = op.abspath(op.dirname(__file__))

try:
    import fcntl

    class FileLocker:
        __slots__ = ("lockfile", "fd")

        def __init__(self, lockfile: str) -> None:
            self.lockfile = lockfile
            self.fd = None

        def acquire(self) -> None:
            try:
                self.fd = open(self.lockfile, "r")
            except FileNotFoundError:
                self.fd = open(self.lockfile, "w")
            fcntl.flock(self.fd, fcntl.LOCK_EX)
            logger.debug("Lock acquired.")

        def release(self) -> None:
            if self.fd is not None:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                self.fd.close()
                self.fd = None
                logger.debug("Lock released.")

except ImportError:

    class FileLocker:
        def __init__(self, *args, **kwargs):
            self._noop = lambda *args, **kwargs: None

        def __getattr__(self, _):
            return self._noop


class TRStatus(enum.IntEnum):
    STOPPED = 0
    CHECK_WAIT = 1
    CHECK = 2
    DOWNLOAD_WAIT = 3
    DOWNLOAD = 4
    SEED_WAIT = 5
    SEED = 6


class TRClient:
    """A client for interacting with the Transmission RPC interface."""

    _SSID = "X-Transmission-Session-Id"
    _RETRIES = 3
    _session_data: dict = None
    _seed_dir: str = None

    def __init__(
        self,
        *,
        protocol: str = "http",
        host: str = "127.0.0.1",
        port: int = 9091,
        path: str = "/transmission/rpc",
        username: Optional[str] = None,
        password: Optional[str] = None,
        seed_dir: Optional[str] = None,
    ) -> None:

        self.url = f"{protocol}://{host}:{port}{path}"
        self.session = requests.Session()
        if username and password:
            self.session.auth = (username, password)
        self.session.headers.update({self._SSID: ""})

        if host.lower() in ("127.0.0.1", "localhost", "::1"):
            self.is_localhost = True
            self._path_module = op
            self.normpath = op.realpath
        else:
            self.is_localhost = False
            self._path_module = None
            self.normpath = self._set_normpath
        self._user_seed_dir = seed_dir

    def _call(self, method: str, arguments: Optional[dict] = None) -> dict:
        """Make a call to the Transmission RPC."""
        query = {"method": method}
        if arguments is not None:
            query["arguments"] = arguments

        for retry in range(1, self._RETRIES + 1):
            logger.debug("Requesting: %s, Attempt: %s", query, retry)
            try:
                r = self.session.post(self.url, json=query)

                if r.status_code not in {401, 403, 409}:
                    data = r.json()
                    logger.debug("Response: %s", data)
                    if data["result"] == "success":
                        return data["arguments"]
                elif r.status_code == 409:
                    self.session.headers[self._SSID] = r.headers[self._SSID]
            except Exception:
                if retry == self._RETRIES:
                    raise
            else:
                if retry == self._RETRIES:
                    raise Exception(f"API Error ({r.status_code}): {r.text}")

        assert False, "Unexpected error in the retry logic."

    def _torrent_action(self, method: str, ids=None, arguments: Optional[dict] = None):
        """A handler for torrent-related actions. If `ids` is omitted, all
        torrents are used. If `ids` is an empty list, no torrent is returned."""
        if ids is not None:
            if arguments is None:
                arguments = {"ids": ids}
            else:
                arguments["ids"] = ids
        return self._call(method, arguments)

    def torrent_start(self, ids=None):
        self._torrent_action("torrent-start", ids)

    def torrent_start_now(self, ids=None):
        self._torrent_action("torrent-start-now", ids)

    def torrent_stop(self, ids=None):
        self._torrent_action("torrent-stop", ids)

    def torrent_verify(self, ids=None):
        self._torrent_action("torrent-verify", ids)

    def torrent_reannounce(self, ids=None):
        self._torrent_action("torrent-reannounce", ids)

    def torrent_get(self, fields: List[str], ids=None) -> dict:
        return self._torrent_action(
            "torrent-get",
            ids=ids,
            arguments={"fields": fields},
        )

    def torrent_remove(self, ids, delete_local_data: bool):
        self._torrent_action(
            "torrent-remove",
            ids=ids,
            arguments={"delete-local-data": delete_local_data},
        )

    def torrent_set_location(self, ids, location: str, move: bool):
        self._torrent_action(
            "torrent-set-location",
            ids=ids,
            arguments={"location": location, "move": move},
        )

    def session_get(self) -> dict:
        """Get the session details, cached."""
        if self._session_data is None:
            self._session_data = self._call("session-get")
        return self._session_data

    def get_freespace(self, path: Optional[str] = None) -> int:
        """Tests how much free space is available in a client-specified folder.
        If `path` is None, test seed_dir."""
        if path is None:
            path = self.seed_dir
        if self.is_localhost:
            try:
                return shutil.disk_usage(path).free
            except OSError as e:
                logger.warning(str(e))
        return int(self._call("free-space", {"path": path})["size-bytes"])

    @property
    def seed_dir(self) -> str:
        if self._seed_dir is None:
            s = self._user_seed_dir or self.session_get()["download-dir"]
            if not s:
                raise ValueError("Unable to get seed_dir.")
            self._seed_dir = self.normpath(s)
        return self._seed_dir

    def _set_normpath(self, path: str) -> str:
        """Dynamically update `normpath` for the remote host."""
        self.normpath = self.get_path_module().normpath
        return self.normpath(path)

    def get_path_module(self):
        """Determine the appropriate path module for the remote host."""
        if self._path_module is not None:
            return self._path_module
        session_data = self.session_get()
        for k in ("config-dir", "download-dir", "incomplete-dir"):
            p = session_data.get(k)
            if not p:
                continue
            if p[0] in ("/", "~") or ":" not in p:
                import posixpath as path
            else:
                import ntpath as path
            self._path_module = path
            return path
        raise ValueError("Unable to determine path type for the remote host.")


class StorageManager:

    _maindata = None

    def __init__(
        self,
        client: TRClient,
        seed_dir_cleanup: bool = False,
        size_limit_gb: Optional[int] = None,
        space_floor_gb: Optional[int] = None,
        watch_dir: Optional[str] = None,
        watch_dir_cleanup: bool = False,
    ) -> None:

        if not client.is_localhost:
            raise ValueError("Cannot manage storage on a remote host.")

        self.client = client
        self.size_limit = self._gb_to_bytes(size_limit_gb)
        self.space_floor = self._gb_to_bytes(space_floor_gb)
        self.seed_dir_cleanup = seed_dir_cleanup
        self.watch_dir = watch_dir if watch_dir_cleanup else None

    def _get_maindata(self):
        """Retrieve a list of torrents located in `seed_dir`, and a set of their
        first path segment after `seed_dir`."""
        if self._maindata is None:
            torrents = []
            allowed = set()
            seed_dir = self.client.seed_dir
            sep = self.client.get_path_module().sep
            data = self.client.torrent_get(
                fields=("downloadDir", "id", "name", "sizeWhenDone")
            )["torrents"]
            for t in data:
                if seed_dir == t["downloadDir"]:
                    allowed.add(t["name"])
                else:
                    path = self.client.normpath(t["downloadDir"])
                    if not is_subpath(path, seed_dir, sep):
                        # torrent is outside of seed_dir
                        continue
                    # find the first segment after seed_dir
                    path = path[len(seed_dir) :].lstrip(sep).partition(sep)[0]
                    allowed.add(path or t["name"])
                torrents.append(t)
            self._maindata = torrents, allowed
        return self._maindata

    @property
    def torrents(self) -> List[dict]:
        return self._get_maindata()[0]

    @property
    def allowed(self) -> Set[str]:
        return self._get_maindata()[1]

    def cleanup(self) -> None:
        """Perform the enabled cleanup tasks."""
        if self.seed_dir_cleanup:
            self._clean_seed_dir()
        if self.watch_dir:
            self._clean_watch_dir()

    def _clean_seed_dir(self) -> None:
        """Remove files from seed_dir if they do not exist in Transmission."""
        if not self.seed_dir_cleanup:
            raise ValueError("Flag 'seed_dir_cleanup' should be True.")
        allowed = self.allowed
        try:
            with os.scandir(self.client.seed_dir) as it:
                entries = tuple(e for e in it if e.name not in allowed)
        except OSError as e:
            logger.error(str(e))
            return
        for e in entries:
            try:
                if e.is_file() and removesuffix(e.name, ".part") in allowed:
                    continue
                logger.info("Cleanup download-dir: %s", e.path)
                if e.is_dir():
                    shutil.rmtree(e.path, ignore_errors=True)
                else:
                    os.unlink(e.path)
            except OSError as e:
                logger.error(str(e))

    def _clean_watch_dir(self) -> None:
        """Remove old or zero-length '.torrent' files from the watch-dir."""
        if not self.watch_dir:
            raise ValueError("'watch_dir' should not be null or empty.")
        try:
            with os.scandir(self.watch_dir) as it:
                entries = tuple(e for e in it if e.name.lower().endswith(".torrent"))
        except OSError as e:
            logger.error(str(e))
            return
        for e in entries:
            try:
                s = e.stat()
                if e.is_file() and (not s.st_size or s.st_mtime < time.time() - 3600):
                    logger.debug("Cleanup watch-dir: %s", e.path)
                    os.unlink(e.path)
            except OSError as e:
                logger.error(str(e))

    def apply_quotas(self) -> None:
        """Enforce size limits and free space requirements in seed_dir."""
        size_to_free = excess = 0
        if self.space_floor:
            size_to_free = self.space_floor - self.client.get_freespace()
        if self.size_limit:
            excess = sum(t["sizeWhenDone"] for t in self.torrents) - self.size_limit
            if excess > size_to_free:
                size_to_free = excess

        if size_to_free <= 0:
            logger.debug("No need to free up space.")
            return
        if size_to_free == excess:
            logger.info("Total size limit exceeded by %s.", humansize(size_to_free))
        else:
            logger.info("Free space below threshold by %s.", humansize(size_to_free))

        results = self._find_inactive_torrents(size_to_free)
        if results:
            logger.info(
                "Remove %d torrent%s to free %s: %s",
                len(results),
                "" if len(results) == 1 else "s",
                humansize(sum(t["sizeWhenDone"] for t in results)),
                ", ".join(t["name"] for t in results),
            )
            self.client.torrent_remove(
                ids=tuple(t["id"] for t in results),
                delete_local_data=True,
            )
        else:
            logger.warning("No suitable torrents found for removal.")

    def _get_removables(self):
        """Retrieves a list of torrents that are candidates for removal."""
        torrents = self.client.torrent_get(
            fields=(
                "activityDate",
                "doneDate",
                "id",
                "name",
                "percentDone",
                "sizeWhenDone",
                "status",
                "trackerStats",
            ),
            ids=tuple(t["id"] for t in self.torrents),
        )["torrents"]
        # Torrents are only removed if they have been completed for more than 12
        # hours to avoid race conditions.
        threshold = time.time() - 43200
        rm_status = {TRStatus.STOPPED, TRStatus.SEED_WAIT, TRStatus.SEED}
        return (
            t
            for t in torrents
            if t["status"] in rm_status
            and t["percentDone"] == 1
            and 0 < t["doneDate"] < threshold
        )

    def _find_inactive_torrents(self, size_to_free: int) -> List[dict]:
        """Find the least active torrents to delete to free up `size_to_free`
        bytes of space.
        """
        results = []
        if size_to_free <= 0:
            return results

        # Categorize torrents based on leecher count.
        with_leechers = []
        leechers = []
        for t in self._get_removables():
            leecher = 0
            for tracker in t["trackerStats"]:
                i = tracker["leecherCount"]
                if i > 0:  # skip "unknown" (-1)
                    leecher += i
            if leecher:
                with_leechers.append(t)
                leechers.append(leecher)
            else:
                # Add zero-leecher torrents to the results.
                results.append(t)

        # Select zero-leecher torrents from the least active ones until the
        # required size is reached.
        results.sort(key=lambda t: t["activityDate"])
        for i, t in enumerate(results):
            size_to_free -= t["sizeWhenDone"]
            if size_to_free <= 0:
                return results[: i + 1]

        # Select torrents with leechers. The question is inverted to fit into
        # the classical knapsack problem: How to select torrents to keep in
        # order to maximize the total number of leechers?
        sizes = tuple(t["sizeWhenDone"] for t in with_leechers)
        survived = KnapsackSolver(max_cells=1024**2).solve(
            weights=sizes,
            values=leechers,
            capacity=sum(sizes) - size_to_free,
        )
        results.extend(t for i, t in enumerate(with_leechers) if i not in survived)
        return results

    @staticmethod
    def _gb_to_bytes(gb):
        # Ensure output is int as `gb` is from user input which can be float
        return int(gb * 1073741824) if gb and gb > 0 else None


class KnapsackSolver:

    def __init__(self, max_cells: Optional[int] = None) -> None:
        """Initialize the KnapsackSolver.

        Args:
            max_cells (int, optional): Maximum number of cells for scaling. If
            None, no scaling is applied.
        """
        if max_cells is not None and max_cells <= 0:
            raise ValueError("max_cells must be None or a positive integer.")
        self.max_cells = max_cells

    def solve(self, weights: List[int], values: List[int], capacity: int) -> Set[int]:
        """Solve the 0-1 knapsack problem using dynamic programming.

        Args:
            weights (List[int]): The weights of the items.
            values (List[int]): The values of the items.
            capacity (int): The maximum capacity of the knapsack.

        Returns:
            Set[int]: A set of indices of the items to include to maximize value.
        """
        if capacity <= 0:
            return set()

        n = len(weights)
        if capacity >= sum(weights):
            return set(range(n))

        # Scale down
        if self.max_cells is not None:
            i = self.ceil(capacity * n / self.max_cells)
            if i > 1:
                weights = tuple(self.ceil(w / i) for w in weights)
                capacity //= i  # round up weights, round down capacity

        # Fill dynamic programming table
        dp = [[0] * (capacity + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            weight = weights[i - 1]
            value = values[i - 1]
            for w in range(1, capacity + 1):
                if weight <= w:
                    dp[i][w] = max(dp[i - 1][w], dp[i - 1][w - weight] + value)
                else:
                    dp[i][w] = dp[i - 1][w]

        # Backtrack to find which items are included
        res = set()
        w = capacity
        for i in range(n, 0, -1):
            if dp[i][w] != dp[i - 1][w]:
                res.add(i - 1)
                w -= weights[i - 1]
        return res

    @staticmethod
    def ceil(n: float) -> int:
        """Computes the ceiling of a number."""
        i = int(n)
        return i + 1 if n != i and n > 0 else i


class Cat(enum.Enum):
    """Enumeration for categorizing torrent files."""

    DEFAULT = "default"
    MOVIES = "movies"
    TV_SHOWS = "tv-shows"
    MUSIC = "music"
    AV = "av"


class Categorizer:

    _VIDEO_THRESH = 52428800  # 50 MiB
    VIDEO, AUDIO, DEFAULT = range(3)

    def __init__(self, patternfile: Optional[str] = None) -> None:
        """Initialize the Categorizer with data from the pattern file."""

        if patternfile is None:
            patternfile = op.join(script_root, "patterns.json")
        with open(patternfile, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not all(data.values()):
            raise ValueError(f"Empty entry in pattern file: {patternfile}")

        self.video_ext = frozenset(data["video_exts"])
        self.audio_ext = frozenset(data["audio_exts"])
        self.software_re = data["software_regex"]
        self.tv_re = data["tv_regex"]
        self.av_re = data["av_regex"]

    def categorize(self, files: List[dict]):
        """
        Categorize the torrent based on the `files` list returned by the
        Transmission "torrent-get" API.
        """
        # Does the torrent name pass the AV test? Torrent name is the file name
        # if there is only one file, or the root directory name otherwise. File
        # names are always POSIX paths.
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
        if main_type == self.VIDEO:
            # Are they TV_SHOWS or MOVIES?
            if any(re_test(self.tv_re, s) for s in segments):
                return Cat.TV_SHOWS
            if self._find_file_groups(videos):
                return Cat.TV_SHOWS
            return Cat.MOVIES

        if main_type == self.AUDIO:
            return Cat.MUSIC

        if main_type == self.DEFAULT:
            return Cat.DEFAULT

        assert False, f"Unexpected main_type: '{main_type}'"

    def _analyze_file_types(self, files: List[dict]) -> Tuple[int, list]:
        """Analyze and categorize files by type, finding the most common
        type."""
        type_size = defaultdict(int)
        video_size = defaultdict(int)

        for file in files:
            root, ext = posix_splitext(file["name"])
            ext = ext[1:].lower()  # Strip leading dot

            if ext in self.video_ext:
                if ext == "m2ts":
                    root = re_sub(r"/bdmv/stream/[^/]+$", "", root)
                elif ext == "vob":
                    root = re_sub(r"/([^/]*vts[0-9_]+|video_ts)$", "", root)
                file_type = self.VIDEO
            elif ext in self.audio_ext:
                file_type = self.AUDIO
            elif ext == "iso" and not re_test(self.software_re, root):
                # ISO could be software or video image
                file_type = self.VIDEO
            else:
                file_type = self.DEFAULT

            size = file["length"]
            type_size[file_type] += size
            if file_type == self.VIDEO:
                video_size[root, ext] += size

        # Filter the videos by size
        size = self._VIDEO_THRESH
        if any(f["length"] >= size for f in files):
            videos = (k for k, v in video_size.items() if v >= size)
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


re_compile = lru_cache(maxsize=None)(re.compile)


def re_test(pattern: str, string: str, _flags=re.A | re.I):
    """Replace all '_' with '-', then perform an ASCII-only and case-insensitive
    test."""
    return re_compile(pattern, _flags).search(string.replace("_", "-"))


def re_sub(pattern: str, repl, string: str, _flags=re.A | re.I):
    """Perform an ASCII-only and case-insensitive substitution."""
    return re_compile(pattern, _flags).sub(repl, string)


def process_torrent_done(
    tid: int,
    client: TRClient,
    dsts: dict,
    private_only: bool,
):
    """Process the completion of a torrent download."""
    # +-----------------+-------------------+---------------------------+
    # | src_in_seed_dir | remove_after_copy | Action                    |
    # +-----------------+-------------------+---------------------------+
    # | Yes             | Yes               | Copy src to dst.          |
    # |                 |                   | Delete files and remove.  |
    # +-----------------+-------------------+---------------------------+
    # | Yes             | No                | Copy src to dst.          |
    # +-----------------+-------------------+---------------------------+
    # | No              | Yes               | Keep files and remove.    |
    # +-----------------+-------------------+---------------------------+
    # | No              | No                | Copy src to seed_dir,     |
    # |                 |                   | set new location.         |
    # +-----------------+-------------------+---------------------------+
    # *remove_after_copy: True if user only seed private and torrent is public

    if not isinstance(tid, int):
        raise ValueError("Torrent ID must be an integer.")
    if not client.is_localhost:
        raise ValueError("Cannot manage download completion on a remote host.")

    data = client.torrent_get(
        fields=("downloadDir", "files", "isPrivate", "name"), ids=tid
    )["torrents"][0]

    src_dir = op.realpath(data["downloadDir"])
    name = data["name"]
    src = op.join(src_dir, name)
    seed_dir = client.seed_dir

    src_in_seed_dir = is_subpath(src_dir, seed_dir)
    remove_after_copy = private_only and not data["isPrivate"]

    # Determine the destination
    if src_in_seed_dir:
        cat = Categorizer().categorize(data["files"])
        logger.info("Categorize '%s' as: %s", name, cat.name)
        dst_dir = op.normpath(dsts.get(cat.value) or dsts[Cat.DEFAULT.value])
        # Create a directory for a single file torrent
        if not op.isdir(src):
            dst_dir = op.join(dst_dir, op.splitext(name)[0])
    else:
        dst_dir = seed_dir

    # File operations
    if src_in_seed_dir or not remove_after_copy:
        dst = op.join(dst_dir, name)
        logger.info("Copy: '%s' -> '%s'", src, dst)
        os.makedirs(dst_dir, exist_ok=True)
        copy_file(src, dst)

    # Remove or redirect the torrent
    if remove_after_copy:
        logger.info("Remove public torrent: %s", name)
        client.torrent_remove(tid, delete_local_data=src_in_seed_dir)
    elif not src_in_seed_dir:
        client.torrent_set_location(tid, seed_dir, move=False)


def is_subpath(child: str, parent: str, sep: str = os.sep) -> bool:
    """Check if `child` is within `parent`. Both paths must be absolute and
    normalized."""
    if not child.endswith(sep):
        child += sep
    if not parent.endswith(sep):
        parent += sep
    return child.startswith(parent)


def _copy_file_fallback(src: str, dst: str) -> None:
    """Copy src to dst using shutil."""
    if op.isdir(src):
        shutil.copytree(
            src, dst, symlinks=True, copy_function=shutil.copy, dirs_exist_ok=True
        )
    else:
        # Avoid shutil.copy() because if dst is a dir, we want to throw an error
        # instead of copying src into it.
        shutil.copyfile(src, dst, follow_symlinks=False)
        shutil.copymode(src, dst, follow_symlinks=False)


if os.name == "nt":
    copy_file = _copy_file_fallback
else:

    def copy_file(src: str, dst: str) -> None:
        """
        Copy src to dst, trying to use reflink. If dst exists, it will be
        overwritten. If src is a file and dst is a directory or vice versa, an
        error will occur.

        Example:
            `copy_file("/src_dir/name", "/dst_dir/name")` -> "/dst_dir/name"
        """
        try:
            subprocess.run(
                ("cp", "-d", "-f", "-R", "--reflink=auto", "-T", "--", src, dst),
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(e.stderr.strip().decode())
        except FileNotFoundError as e:
            logger.warning(str(e))
        else:
            return
        _copy_file_fallback(src, dst)


try:
    removesuffix = str.removesuffix  # Python 3.9+
except AttributeError:
    removesuffix = lambda s, f: s[: -len(f)] if f and s.endswith(f) else s


def humansize(size: int) -> str:
    """Convert bytes to human readable sizes."""
    for suffix in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
        if -1024 < size < 1024:
            return f"{size:.2f} {suffix}B"
        size /= 1024
    return f"{size:.2f} YiB"


def parse_config(configfile: str) -> dict:
    """Parse and validate the configuration file."""
    config = {
        "rpc-port": 9091,
        "rpc-url": "/transmission/rpc",
        "rpc-username": "",
        "rpc-password": "",
        "download-dir": "",
        "download-dir-cleanup-enable": False,
        "download-dir-size-limit-gb": None,
        "download-dir-space-floor-gb": None,
        "watch-dir": "",
        "watch-dir-cleanup-enable": False,
        "only-seed-private": False,
        "log-level": "INFO",
        "destinations": {c.value: "" for c in Cat},
    }

    def _dump_config(data):
        with open(configfile, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    try:
        with open(configfile, "r", encoding="utf-8") as f:
            config.update(json.load(f))

        # Validation
        v = config["download-dir"]
        if v and not op.isdir(v):
            raise ValueError("The 'download-dir' is not a valid directory.")
        if not op.isdir(config["destinations"][Cat.DEFAULT.value]):
            raise ValueError("The 'destinations.default' is not a valid directory.")

        # Password
        v = config["rpc-password"]
        if v:
            if v[0] == "{" and v[-1] == "}":
                config["rpc-password"] = base64.b64decode(v[-2:0:-1]).decode()
            else:
                config["rpc-password"] = (
                    f"{{{base64.b64encode(v.encode()).decode()[::-1]}}}"
                )
                _dump_config(config)
                config["rpc-password"] = v

    except FileNotFoundError:
        _dump_config(config)
        sys.exit(
            f"A blank configuration file has been created at '{configfile}'. "
            "Edit the settings before running this script again."
        )
    except Exception as e:
        sys.exit(f"Configuration error: {e}")
    else:
        return config


def config_logger(logger: logging.Logger, logfile: str, level: str = "INFO"):
    """Configure the logging system with both console and file handlers."""
    logger.handlers.clear()
    level = level.upper()
    if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = getattr(logging, level)
    else:
        level = logging.INFO
    logger.setLevel(level)

    # Console handler
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)

    # File handler
    handler = logging.FileHandler(logfile)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)


def main():

    conf = parse_config(op.join(script_root, "config.json"))
    config_logger(logger, op.join(script_root, "logfile.log"), conf["log-level"])

    flock = FileLocker(__file__)
    try:
        flock.acquire()
        start = time.time()

        client = TRClient(
            port=conf["rpc-port"],
            path=conf["rpc-url"],
            username=conf["rpc-username"],
            password=conf["rpc-password"],
            seed_dir=conf["download-dir"],
        )

        tid = os.environ.get("TR_TORRENT_ID")
        if tid:
            # Invoked by Transmission
            logger.info("Triggered with torrent ID: %s", tid)
            tid = int(tid)
            try:
                process_torrent_done(
                    tid=tid,
                    client=client,
                    dsts=conf["destinations"],
                    private_only=conf["only-seed-private"],
                )
            except Exception as e:
                logger.error(
                    "Error processing torrent '%s': %s",
                    os.environ.get("TR_TORRENT_NAME", tid),
                    str(e),
                )

        storage = StorageManager(
            client=client,
            seed_dir_cleanup=conf["download-dir-cleanup-enable"],
            size_limit_gb=conf["download-dir-size-limit-gb"],
            space_floor_gb=conf["download-dir-space-floor-gb"],
            watch_dir=conf["watch-dir"],
            watch_dir_cleanup=conf["watch-dir-cleanup-enable"],
        )
        storage.cleanup()
        storage.apply_quotas()

    except Exception as e:
        logger.critical(str(e))

    else:
        logger.info("Execution completed in %.2f seconds.", time.time() - start)

    finally:
        flock.release()


if __name__ == "__main__":
    main()
