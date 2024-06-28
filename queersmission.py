"""
Queersmission - Smart Categorization for Transmission
=====================================================

Description:
------------
Queersmission is a custom script for the Transmission client. It manages a
dedicated seeding space and copies completed downloads to user-specified
locations.

Features:
---------
- Storage management based on quota settings.
- Copy finished downloads to user destinations.
- Smart torrent categorization.

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
from functools import cached_property, lru_cache
from logging.handlers import RotatingFileHandler
from posixpath import splitext as posix_splitext
from typing import Dict, List, Optional, Set, Tuple

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
        self._seed_dir = seed_dir

        if host.lower() in ("127.0.0.1", "localhost", "::1"):
            self.is_localhost = True
            self.path_module = op
            self.normpath = op.realpath
        else:
            self.is_localhost = False

        self.session = requests.Session()
        if username and password:
            self.session.auth = (username, password)
        self.session.headers.update({self._SSID: ""})

    def _call(self, method: str, arguments: Optional[dict] = None, *, ids=None) -> dict:
        """Make a call to the Transmission RPC."""

        # If `ids` is omitted, all torrents are used.
        if ids is not None:
            self._check_ids(ids)
            if arguments is None:
                arguments = {"ids": ids}
            else:
                arguments["ids"] = ids

        query = {"method": method}
        if arguments is not None:
            query["arguments"] = arguments

        res = None
        for retry in range(1, self._RETRIES + 1):
            logger.debug("Requesting: %s, Attempt: %s", query, retry)
            try:
                res = self.session.post(self.url, json=query)
                if res.status_code not in {401, 403, 409}:
                    data = res.json()
                    logger.debug("Response: %s", data)
                    if data["result"] == "success":
                        return data["arguments"]
                elif res.status_code == 409:
                    self.session.headers[self._SSID] = res.headers[self._SSID]
            except Exception:
                if retry == self._RETRIES:
                    raise

        assert res is not None, 'Response "res" should never be None at this point.'
        raise Exception(f"API Error ({res.status_code}): {res.text}")

    def torrent_start(self, ids=None):
        self._call("torrent-start", ids=ids)

    def torrent_start_now(self, ids=None):
        self._call("torrent-start-now", ids=ids)

    def torrent_stop(self, ids=None):
        self._call("torrent-stop", ids=ids)

    def torrent_verify(self, ids=None):
        self._call("torrent-verify", ids=ids)

    def torrent_reannounce(self, ids=None):
        self._call("torrent-reannounce", ids=ids)

    def torrent_get(self, fields: List[str], ids=None) -> dict:
        return self._call("torrent-get", {"fields": fields}, ids=ids)

    def torrent_remove(self, ids, delete_local_data: bool):
        self._call(
            "torrent-remove",
            {"delete-local-data": delete_local_data},
            ids=ids,
        )

    def torrent_set_location(self, ids, location: str, move: bool):
        self._call(
            "torrent-set-location",
            {"location": location, "move": move},
            ids=ids,
        )

    def wait_status(self, ids, status: Set[TRStatus], timeout: int = None):
        """Waits until all specified torrents reach given status or timeout."""
        interval = 0.5
        if isinstance(status, TRStatus):
            status = (status,)
        if timeout is not None:
            timeout += time.perf_counter()
        while True:
            torrents = self.torrent_get(("status",), ids)["torrents"]
            if all(t["status"] in status for t in torrents):
                return
            if timeout is not None:
                remain = timeout - time.perf_counter()
                if remain <= 0:
                    raise TimeoutError("Timeout while waiting for desired status.")
                if remain < interval:
                    interval = remain
            time.sleep(interval)

    def get_freespace(self, path: Optional[str] = None) -> Tuple[int, int]:
        """Tests how much space is available in a client-specified folder.
        If `path` is None, test seed_dir."""
        if path is None:
            path = self.seed_dir
        if self.is_localhost:
            try:
                res = shutil.disk_usage(path)
                return res.total, res.free
            except OSError as e:
                logger.warning(str(e))
        res = self._call("free-space", {"path": path})
        return res["total_size"], res["size-bytes"]

    @cached_property
    def session_settings(self):
        """The complete setting list returned by the "session-get" API."""
        return self._call("session-get")

    @cached_property
    def path_module(self):
        """The appropriate path module for the remote host."""
        # Only called when is_localhost is False.
        for k in ("config-dir", "download-dir", "incomplete-dir"):
            p = self.session_settings.get(k)
            if not p:
                continue
            if p[0] in ("/", "~") or ":" not in p:
                import posixpath as path
            else:
                import ntpath as path
            return path
        raise ValueError("Unable to determine path type for the remote host.")

    @cached_property
    def normpath(self):
        """The appropriate normpath function for the remote host."""
        # Only called when is_localhost is False.
        return self.path_module.normpath

    @cached_property
    def seed_dir(self) -> str:
        """The seeding directory of the host."""
        s = self._seed_dir or self.session_settings["download-dir"]
        if not s:
            raise ValueError("Unable to get seed_dir.")
        return self.normpath(s)

    @staticmethod
    def _check_ids(ids):
        """Validate the IDs passed to the Transmission RPC.

        ids should be one of the following:
        - an integer referring to a torrent id
        - a list of torrent id numbers, SHA1 hash strings, or both
        - a string, 'recently-active', for recently-active torrents
        """
        for i in ids if isinstance(ids, (tuple, list)) else (ids,):
            if isinstance(i, int):
                if i > 0:
                    continue
            elif isinstance(i, str):
                if re_compile(r"[A-Fa-f0-9]{40}").fullmatch(i):
                    continue
                if ids == "recently-active":
                    return
            raise ValueError(f"Invalid torrent ID '{i}' in IDs: {ids}")


class StorageManager:

    def __init__(
        self,
        client: TRClient,
        seed_dir_cleanup: bool = False,
        size_limit_gb: Optional[int] = None,
        space_floor_gb: Optional[int] = None,
        watch_dir: Optional[str] = None,
    ) -> None:

        if not client.is_localhost:
            raise ValueError("Cannot manage storage on a remote host.")

        self.client = client
        self.seed_dir_cleanup = seed_dir_cleanup
        self.size_limit = self._gb_to_bytes(size_limit_gb)
        self.space_floor = self._gb_to_bytes(space_floor_gb)
        self.watch_dir = watch_dir

    @cached_property
    def _maindata(self):
        torrents = {}
        allowed = set()
        seed_dir = self.client.seed_dir
        data = self.client.torrent_get(
            fields=("downloadDir", "id", "name", "sizeWhenDone")
        )["torrents"]

        for t in data:
            if seed_dir == t["downloadDir"]:
                allowed.add(t["name"])
            else:
                path = op.realpath(t["downloadDir"])
                if not is_subpath(path, seed_dir):
                    # Torrent is outside of seed_dir.
                    continue
                # Find the first segment after seed_dir.
                allowed.add(
                    path[len(seed_dir) :].lstrip(os.sep).partition(os.sep)[0]
                    or t["name"]
                )
            torrents[t["id"]] = t["sizeWhenDone"]
        return torrents, allowed

    @property
    def torrents(self) -> Dict[int, int]:
        """(id: sizeWhenDone) pairs of torrents located in seed_dir."""
        return self._maindata[0]

    @property
    def allowed(self) -> Set[str]:
        """First path segments after seed_dir of current torrents."""
        return self._maindata[1]

    def cleanup(self) -> None:
        """Perform the enabled cleanup tasks."""
        if self.watch_dir:
            self._clean_watch_dir()
        if self.seed_dir_cleanup:
            self._clean_seed_dir()

    def _clean_watch_dir(self) -> None:
        """Remove old or zero-length '.torrent' files from the watch-dir."""
        if not self.watch_dir:
            raise ValueError('Value "watch_dir" should not be null.')
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

    def _clean_seed_dir(self) -> None:
        """Remove files from seed_dir if they do not exist in Transmission."""
        if not self.seed_dir_cleanup:
            raise ValueError('Flag "seed_dir_cleanup" should be True.')
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

    def apply_quotas(self, add_size: Optional[int] = None, in_seed_dir: bool = True):
        """Enforce size limits and free space requirements in seed_dir. If
        `add_size` is set, ensure additional free space."""
        # +---+---------------+-------------+------------------------------------------+
        # |   | Mode          | In Seed Dir | Action                                   |
        # +---+---------------+-------------+------------------------------------------+
        # | 1 | torrent-added | True        | free -= add_size                         |
        # | 2 | torrent-added | False       | No-op                                    |
        # | 3 | torrent-done  | True        | No-op                                    |
        # | 4 | torrent-done  | False       | free -= add_size; total_size += add_size |
        # +---+---------------+-------------+------------------------------------------+
        # NOTE: add_size should only be set in condition 1, 4

        total, free = self.client.get_freespace()
        total_size = sum(self.torrents.values())

        if add_size is not None:  # condition 1, 4
            free -= add_size
            if not in_seed_dir:  # condition 4
                total_size += add_size

        size_limit = total - self.space_floor  # disk capacity
        if 0 < self.size_limit < size_limit:
            size_limit = self.size_limit  # user limit

        size_to_free = max(
            total_size - size_limit,  # size limit
            self.space_floor - free,  # free space
        )

        if size_to_free <= 0:
            logger.debug("No need to free up space.")
            return

        logger.info("Storage limits exceeded by %s.", humansize(size_to_free))
        results = self._find_optimal_removals(size_to_free)
        if results:
            logger.info(
                "Remove %d torrent%s (%s): %s",
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
        data = self.client.torrent_get(
            fields=(
                "activityDate",
                "doneDate",
                "id",
                "name",
                "peers",
                "percentDone",
                "sizeWhenDone",
                "status",
                "trackerStats",
            ),
            ids=tuple(self.torrents),
        )["torrents"]
        # Torrents are only removed if they have been completed for more than 12
        # hours to avoid race conditions.
        threshold = time.time() - 43200
        rm_status = {TRStatus.STOPPED, TRStatus.SEED_WAIT, TRStatus.SEED}
        return (
            t
            for t in data
            if t["status"] in rm_status
            and t["percentDone"] == 1
            and 0 < t["doneDate"] < threshold
        )

    def _find_optimal_removals(self, size_to_free: int) -> List[dict]:
        """Find an optimal set of torrents to remove to free up `size_to_free`
        bytes of space.
        """
        if size_to_free <= 0:
            raise ValueError('Expect "size_to_free" to be a positive integer.')
        # Categorize torrents based on leecher count.
        results = []
        with_leechers = []
        leechers = []
        for t in self._get_removables():
            leecher = 0
            for tracker in t["trackerStats"]:
                i = tracker["leecherCount"]  # int
                if i > 0:  # skip "unknown" (-1)
                    leecher += i
            leecher = max(leecher, sum(p["progress"] < 1 for p in t["peers"]))
            if leecher:
                with_leechers.append(t)
                leechers.append(leecher)
            else:
                # Add zero-leecher torrents to the results.
                results.append(t)

        # First: Select zero-leecher torrents from the least active ones until
        # the required size is reached.
        results.sort(key=lambda t: t["activityDate"])
        for i, t in enumerate(results):
            size_to_free -= t["sizeWhenDone"]  # uint64_t
            if size_to_free <= 0:
                return results[: i + 1]

        # Second: Pick torrents with leechers. The question is inverted to fit
        # into the classical knapsack problem: How to select torrents to keep in
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
    def _gb_to_bytes(size):
        """Converts GiB to bytes. Returns 0 if the input is invalid or
        negative."""
        try:
            return int(size * 1073741824) if size and size > 0 else 0
        except (TypeError, ValueError) as e:
            logger.error('Invalid value "%s": %s', size, str(e))
            return 0


class KnapsackSolver:

    def __init__(self, max_cells: Optional[int] = None) -> None:
        """Initialize the KnapsackSolver.

        Args:
            max_cells (int, optional): Maximum number of cells for scaling. If
            None, no scaling is applied.
        """
        if max_cells is not None:
            if not isinstance(max_cells, int):
                raise TypeError('Expect "max_cells" to be of type "int".')
            if max_cells < 1:
                raise ValueError('Expect "max_cells" to be a positive integer.')
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
        if not isinstance(capacity, int):
            raise TypeError('Expect "capacity" to be of type "int".')

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
            wt = weights[i - 1]
            vl = values[i - 1]
            for w in range(1, capacity + 1):
                if wt <= w:
                    dp[i][w] = max(dp[i - 1][w], dp[i - 1][w - wt] + vl)
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

    __slots__ = ("video_exts", "audio_exts", "sw_re", "tv_re", "av_re")
    VIDEO_THRESH = 52428800  # 50 MiB
    VIDEO, AUDIO, DEFAULT = range(3)

    def __init__(self, patternfile: Optional[str] = None) -> None:
        """Initialize the Categorizer with data from the pattern file."""

        if patternfile is None:
            patternfile = op.join(script_root, "patterns.json")
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
                file_type = self.VIDEO
            elif ext in self.audio_exts:
                file_type = self.AUDIO
            elif ext == "iso" and not re_test(self.sw_re, root):
                # ISO could be software or video image
                file_type = self.VIDEO
            else:
                file_type = self.DEFAULT

            size = file["length"]
            type_size[file_type] += size
            if file_type == self.VIDEO:
                video_size[root, ext] += size

        # Apply a conditional threshold for videos
        size = self.VIDEO_THRESH
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


def re_test(pattern: str, string: str, _flags=re.A | re.I) -> bool:
    """Replace all '_' with '-', then perform an ASCII-only and case-insensitive
    test."""
    return re_compile(pattern, _flags).search(string.replace("_", "-")) is not None


def re_sub(pattern: str, repl, string: str, _flags=re.A | re.I) -> str:
    """Perform an ASCII-only and case-insensitive substitution."""
    return re_compile(pattern, _flags).sub(repl, string)


def process_torrent_done(
    tid: int,
    client: TRClient,
    storage: StorageManager,
    dsts: dict,
    private_only: bool,
):
    """Process the completion of a torrent download."""
    # +-----------------+----------------+---------------------------+
    # | src_in_seed_dir | remove_torrent | Action                    |
    # +-----------------+----------------+---------------------------+
    # | True            | True           | Copy src to dst.          |
    # |                 |                | Delete files and remove.  |
    # +-----------------+----------------+---------------------------+
    # | True            | False          | Copy src to dst.          |
    # +-----------------+----------------+---------------------------+
    # | False           | True           | Keep files and remove.    |
    # +-----------------+----------------+---------------------------+
    # | False           | False          | Copy src to seed_dir,     |
    # |                 |                | set new location.         |
    # +-----------------+----------------+---------------------------+
    # * src_in_seed_dir: True if the torrent's downloadDir is within seed_dir
    # * remove_torrent: True if user only seed private and torrent is public

    if not client.is_localhost:
        raise ValueError("Cannot manage download completion on a remote host.")

    t = client.torrent_get(
        fields=("downloadDir", "files", "isPrivate", "name", "sizeWhenDone", "status"),
        ids=tid,
    )["torrents"][0]

    # Check for torrent status
    ok_status = {TRStatus.STOPPED, TRStatus.SEED_WAIT, TRStatus.SEED}
    if t["status"] not in ok_status:
        client.wait_status(tid, ok_status, timeout=15)

    src_dir = op.realpath(t["downloadDir"])
    name = t["name"]
    src = op.join(src_dir, name)

    src_in_seed_dir = is_subpath(src_dir, client.seed_dir)
    remove_torrent = private_only and not t["isPrivate"]

    # Determine the destination
    if src_in_seed_dir:
        cat = Categorizer().categorize(t["files"])
        logger.info('Categorize "%s" as: %s', name, cat.name)
        dst_dir = op.normpath(dsts.get(cat.value) or dsts[Cat.DEFAULT.value])
        # Create a directory for a single file torrent
        if not op.isdir(src):
            dst_dir = op.join(dst_dir, op.splitext(name)[0])
    else:
        dst_dir = client.seed_dir
        # Ensure free space in seed_dir
        if not remove_torrent:
            storage.apply_quotas(t["sizeWhenDone"], in_seed_dir=False)

    # File operations
    if src_in_seed_dir or not remove_torrent:
        dst = op.join(dst_dir, name)
        logger.info('Copy: "%s" -> "%s" (%s)', src, dst, humansize(t["sizeWhenDone"]))
        os.makedirs(dst_dir, exist_ok=True)
        copy_file(src, dst)

    # Remove or redirect the torrent
    if remove_torrent:
        logger.info("Remove public torrent: %s", name)
        client.torrent_remove(tid, delete_local_data=src_in_seed_dir)
    elif not src_in_seed_dir:
        client.torrent_set_location(tid, dst_dir, move=False)


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
            logger.warning(e.stderr.strip().decode() or str(e))
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
    conf = {
        "rpc-port": 9091,
        "rpc-url": "/transmission/rpc",
        "rpc-username": "",
        "rpc-password": "",
        "download-dir": "",
        "download-dir-cleanup-enable": False,
        "download-dir-size-limit-gb": 0,
        "download-dir-space-floor-gb": 0,
        "watch-dir": "",
        "only-seed-private": False,
        "log-level": "INFO",
        "destinations": {c.value: "" for c in Cat},
    }

    def _dump_config(data):
        with open(configfile, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    try:
        with open(configfile, "r", encoding="utf-8") as f:
            conf.update(json.load(f))

        # Validation
        if not conf["destinations"][Cat.DEFAULT.value]:
            raise ValueError("The default destination path is not set.")

        # Password
        p = conf["rpc-password"]
        if not p:
            pass
        elif p[0] == "{" and p[-1] == "}":
            conf["rpc-password"] = base64.b64decode(p[-2:0:-1]).decode()
        else:
            conf["rpc-password"] = f"{{{base64.b64encode(p.encode()).decode()[::-1]}}}"
            _dump_config(conf)
            conf["rpc-password"] = p

    except FileNotFoundError:
        _dump_config(conf)
        sys.exit(
            f'A blank configuration file has been created at "{configfile}". '
            "Edit the settings before running this script again."
        )
    except Exception as e:
        sys.exit(f"Configuration error: {e}")

    return conf


def config_logger(logger: logging.Logger, logfile: str, level: str = "INFO"):
    """Configure the logging system with both console and file handlers."""
    logger.handlers.clear()
    level = level.upper()
    if level == "INFO" or level not in ("DEBUG", "WARNING", "ERROR", "CRITICAL"):
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(getattr(logging, level))

    # Console handler
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)

    # File handler
    handler = RotatingFileHandler(logfile, maxBytes=10485760, backupCount=2)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)


def main(torrent_added: bool):
    """Entry point for the script.

    Parameters:
     - torrent_added (bool): Indicates the mode of operation. If True, the
       function is triggered as 'script-torrent-added' to handle newly added
       torrents; if False, it operates as 'script-torrent-done' to manage
       completed torrents.
    """

    conf = parse_config(op.join(script_root, "config.json"))
    config_logger(logger, op.join(script_root, "logfile.log"), conf["log-level"])

    flock = FileLocker(__file__)
    try:
        flock.acquire()
        start = time.perf_counter()

        tid = os.environ.get("TR_TORRENT_ID")
        if tid is not None:
            logger.info(
                "Script-torrent-%s triggered with torrent ID: %s",
                "added" if torrent_added else "done",
                tid,
            )
            tid = int(tid)

        client = TRClient(
            port=conf["rpc-port"],
            path=conf["rpc-url"],
            username=conf["rpc-username"],
            password=conf["rpc-password"],
            seed_dir=conf["download-dir"],
        )
        storage = StorageManager(
            client=client,
            seed_dir_cleanup=conf["download-dir-cleanup-enable"],
            size_limit_gb=conf["download-dir-size-limit-gb"],
            space_floor_gb=conf["download-dir-space-floor-gb"],
            watch_dir=conf["watch-dir"],
        )

        if torrent_added:
            storage.cleanup()
            if tid is None:
                storage.apply_quotas()
            elif tid in storage.torrents:
                storage.apply_quotas(storage.torrents[tid], in_seed_dir=True)

        elif tid is not None:
            process_torrent_done(
                tid=tid,
                client=client,
                storage=storage,
                dsts=conf["destinations"],
                private_only=conf["only-seed-private"],
            )

    except Exception as e:
        logger.critical(str(e))

    else:
        logger.info("Execution completed in %.2f seconds.", time.perf_counter() - start)

    finally:
        flock.release()
