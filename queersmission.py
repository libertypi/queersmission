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
from enum import Enum
from functools import lru_cache
from typing import Iterable, List, Tuple

import requests

logger = logging.getLogger(__name__)

try:
    import fcntl

    class FileLocker:
        __slots__ = ("lockfile", "fd")

        def __init__(self, lockfile: str) -> None:
            self.lockfile = lockfile
            self.fd = None

        def acquire(self):
            try:
                self.fd = open(self.lockfile, "r")
            except FileNotFoundError:
                self.fd = open(self.lockfile, "w")
            fcntl.flock(self.fd, fcntl.LOCK_EX)
            logger.debug("Lock acquired.")

        def release(self):
            if self.fd:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                self.fd.close()
                self.fd = None
                logger.debug("Lock released.")

except ImportError:

    class FileLocker:
        def __init__(self, lockfile: str) -> None:
            pass

        def acquire(self):
            pass

        def release(self):
            pass


class TransmissionClient:
    """A client for interacting with the Transmission RPC interface."""

    _SSID: str = "X-Transmission-Session-Id"
    _RETRIES: int = 3
    _seed_dir: str = None
    _session_data: dict = None

    def __init__(
        self,
        *,
        protocol: str = "http",
        host: str = "127.0.0.1",
        port: int = 9091,
        path: str = "/transmission/rpc",
        username: str = None,
        password: str = None,
        seed_dir: str = None,
    ) -> None:

        self.url = f"{protocol}://{host}:{port}{path}"
        self.is_localhost = host.lower() in ("127.0.0.1", "localhost", "::1")
        if seed_dir:
            self._seed_dir = op.realpath(seed_dir) if self.is_localhost else seed_dir

        self.session = requests.Session()
        if username and password:
            self.session.auth = username, password
        self.session.headers.update({self._SSID: ""})

    def _call(self, method: str, arguments: dict = None) -> dict:
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
            except Exception as e:
                if retry == self._RETRIES:
                    raise
            else:
                if retry == self._RETRIES:
                    raise Exception(f"API Error {r.status_code}: {r.text}")

        assert False, "Unexpected error in the retry logic."

    @property
    def seed_dir(self) -> str:
        if not self._seed_dir:
            s = self.session_get()["download-dir"]
            if not s:
                raise ValueError("Unable to get seed_dir.")
            self._seed_dir = op.realpath(s) if self.is_localhost else s
        return self._seed_dir

    def session_get(self):
        """Get the session details, cached."""
        if not self._session_data:
            self._session_data = self._call("session-get")
        return self._session_data

    def torrent_get(self, fields: List[str], ids=None):
        arguments = {"fields": fields}
        if ids is not None:
            # If `ids` is absent, all torrents are returned. If `ids` is an
            # empty list, an empty list is returned.
            arguments["ids"] = ids
        return self._call("torrent-get", arguments)

    def torrent_remove(self, ids, delete_local_data: bool):
        self._call(
            "torrent-remove",
            {"ids": ids, "delete-local-data": delete_local_data},
        )

    def set_location(self, ids, location, move: bool):
        self._call(
            "torrent-set-location",
            {"ids": ids, "location": location, "move": move},
        )


class Cat(Enum):
    """Enumeration for categorizing torrent files."""

    DEFAULT = "default"
    MOVIES = "movies"
    TV_SHOWS = "tv-shows"
    MUSIC = "music"
    AV = "av"


class Categorizer:

    _VIDEO_THRESH = 52428800  # 50 MiB
    VIDEO, AUDIO, DEFAULT = range(3)

    def __init__(self, pattern_file: str = None) -> None:
        """Initialize the Categorizer with data from the pattern file."""

        if pattern_file is None:
            pattern_file = op.join(op.dirname(__file__), "patterns.json")
        with open(pattern_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not all(data.values()):
            raise ValueError(f"Empty entry in pattern file: '{pattern_file}'")

        self.video_ext = frozenset(data["video_exts"])
        self.audio_ext = frozenset(data["audio_exts"])
        self.software_re = data["software_regex"]
        self.tv_re = data["tv_regex"]
        self.av_re = data["av_regex"]

    def categorize(self, files: List[dict]):
        """
        Categorize the torrent based on the provided list of files. The `files`
        parameter is the array returned by the Transmission "torrent-get" API.
        """

        # Does the torrent name pass the AV test? Torrent name is the file name
        # if there is only one file, or the root directory name otherwise.
        name = files[0]["name"].partition("/")
        name = name[0] if name[1] else op.splitext(name[0])[0]
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

        raise ValueError(f"Invalid main_type: {main_type}")

    def _analyze_file_types(self, files: List[dict]) -> Tuple[int, list]:
        """Analyze and categorize files by type, finding the most common
        type."""
        type_to_size = defaultdict(int)
        video_to_size = defaultdict(int)

        for file in files:
            root, ext = op.splitext(file["name"])
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
            type_to_size[file_type] += size
            if file_type == self.VIDEO:
                video_to_size[root, ext] += size

        # Filter the videos by size
        if any(f["length"] >= self._VIDEO_THRESH for f in files):
            videos = (k for k, v in video_to_size.items() if v >= self._VIDEO_THRESH)
        else:
            videos = video_to_size

        return (
            max(type_to_size, key=type_to_size.get),
            sorted(videos, key=video_to_size.get, reverse=True),
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


class StorageManager:

    def __init__(
        self,
        client: TransmissionClient,
        seed_dir_cleanup: bool = False,
        size_limit_gb: int = None,
        space_floor_gb: int = None,
        watch_dir: str = None,
        watch_dir_cleanup: bool = False,
    ) -> None:

        if not client.is_localhost:
            raise ValueError("Cannot manage storage on a remote host.")

        self.client = client
        self.size_limit = self._gb_to_bytes(size_limit_gb)
        self.space_floor = self._gb_to_bytes(space_floor_gb)
        self.seed_dir_cleanup = seed_dir_cleanup
        self.watch_dir = watch_dir if watch_dir_cleanup else None

        self._init_maindata()

    def _init_maindata(self):
        """Retrieve and filter torrents located in `seed_dir`."""
        data = self.client.torrent_get(
            fields=("downloadDir", "id", "name", "sizeWhenDone")
        )["torrents"]

        self.torrents = torrents = []
        self.allowed_files = allowed = set()
        seed_dir = self.client.seed_dir

        for t in data:
            if seed_dir == t["downloadDir"]:
                allowed.add(t["name"])
            else:
                path = op.realpath(t["downloadDir"])
                if seed_dir != op.commonpath((path, seed_dir)):
                    # torrent is outside of seed_dir
                    continue
                # the first segment after seed_dir
                allowed.add(
                    path[len(seed_dir) :].lstrip(os.sep).partition(os.sep)[0]
                    or t["name"]
                )
            torrents.append(t)

    def cleanup(self):
        """Perform the enabled cleanup tasks."""
        if self.seed_dir_cleanup:
            self._clean_seed_dir()
        if self.watch_dir:
            self._clean_watch_dir()

    def _clean_seed_dir(self):
        """Remove files from seed_dir if they do not exist in Transmission."""
        assert self.seed_dir_cleanup, "'seed_dir_cleanup' should be True."
        allowed = self.allowed_files
        try:
            with os.scandir(self.client.seed_dir) as it:
                entries = tuple(e for e in it if e.name not in allowed)
        except OSError as e:
            logger.error(e)
            return
        for e in entries:
            try:
                if e.is_file() and re_sub(r"\.part$", "", e.name) in allowed:
                    continue
                logger.info("Cleanup download-dir: %s", e.name)
                if e.is_dir():
                    shutil.rmtree(e.path, ignore_errors=True)
                else:
                    os.unlink(e.path)
            except OSError as e:
                logger.error(e)

    def _clean_watch_dir(self):
        """Remove old and zero-length ".torrent" files from watch dir."""
        assert self.watch_dir, "'watch_dir' should not be null or empty."
        try:
            with os.scandir(self.watch_dir) as it:
                entries = tuple(e for e in it if e.name.lower().endswith(".torrent"))
        except OSError as e:
            logger.error(e)
            return
        for e in entries:
            try:
                s = e.stat()
                if e.is_file() and (not s.st_size or s.st_mtime < time.time() - 3600):
                    logger.debug("Cleanup watch-dir: %s", e.name)
                    os.unlink(e.path)
            except OSError as e:
                logger.error(e)

    def apply_quotas(self):
        """Enforce size limits and free space requirements in seed_dir."""
        size_to_free = self._calculate_size_to_free()
        if size_to_free <= 0:
            return

        logger.debug("%s bytes need to be freed from disk.", size_to_free)
        ids = self._get_removable_torrents(size_to_free)
        if ids:
            self.client.torrent_remove(ids, delete_local_data=True)

    def _calculate_size_to_free(self):
        """Calculate the total size that needs to be freed."""
        size_to_free = 0

        if self.size_limit:
            n = sum(t["sizeWhenDone"] for t in self.torrents) - self.size_limit
            if n > 0:
                logger.debug("Total size limit exceeded by %s bytes.", n)
                size_to_free = n

        if self.space_floor:
            try:
                n = self.space_floor - shutil.disk_usage(self.client.seed_dir).free
            except OSError as e:
                logger.error(e)
            else:
                if n > 0:
                    logger.debug("Free space below threshold by %s bytes.", n)
                    if n > size_to_free:
                        size_to_free = n
        return size_to_free

    def _get_removable_torrents(self, size_to_free: int):
        """Select torrents to remove to free the required size."""
        assert size_to_free > 0, f"'size_to_free' should be positive: {size_to_free}"
        ids = []
        data: list = self.client.torrent_get(
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
            ids=[t["id"] for t in self.torrents],
        )["torrents"]
        data.sort(key=self._torrent_value)

        # Status: stopped, queued to seed, seeding
        rm_status = {0, 5, 6}
        # Torrents are only removed if they have been completed for more than an
        # hour, in case they are queueing to be copied.
        one_hour_ago = time.time() - 3600

        for t in data:
            if (
                t["status"] in rm_status
                and t["percentDone"] == 1
                and 0 < t["doneDate"] < one_hour_ago
            ):
                logger.info("Remove torrent: %s", t["name"])
                ids.append(t["id"])
                size_to_free -= t["sizeWhenDone"]
                if size_to_free <= 0:
                    break
        return ids

    @staticmethod
    def _torrent_value(t: dict):
        """Return a tuple of `Value` and `activityDate`, where:
        Value = Leechers * (Leechers / Seeders)
        """
        l = sum(i["leecherCount"] for i in t["trackerStats"])
        s = sum(i["seederCount"] for i in t["trackerStats"]) or 1
        return (l**2 / s, t["activityDate"])

    @staticmethod
    def _gb_to_bytes(gb: int):
        return gb * 1073741824 if gb and gb > 0 else 0


re_compile = lru_cache(maxsize=None)(re.compile)


def re_test(pattern: str, string: str, _flags=re.A | re.I):
    """Replace all '_' with '-', then perform a ASCII-only and case-insensitive
    test."""
    return re_compile(pattern, _flags).search(string.replace("_", "-"))


def re_sub(pattern: str, repl, string: str, _flags=re.A | re.I):
    """Perform a ASCII-only and case-insensitive substitution."""
    return re_compile(pattern, _flags).sub(repl, string)


def process_torrent_done(
    tid: int,
    client: TransmissionClient,
    dsts: dict,
    private_only: bool,
):
    """Process the completion of a torrent download."""
    # +------------+--------------+-----------------+---------------------------+
    # | is_private | private_only | src_in_seed_dir | Action                    |
    # +------------+--------------+-----------------+---------------------------+
    # | No         | Yes          | Yes             | Remove from Transmission, |
    # |            |              |                 | move src to dst.          |
    # +------------+--------------+-----------------+---------------------------+
    # | No         | Yes          | No              | Remove from Transmission. |
    # +------------+--------------+-----------------+---------------------------+
    # | Yes/No     | No           | Yes             | Copy src to dst.          |
    # | Yes        | Yes          |                 |                           |
    # +------------+--------------+-----------------+---------------------------+
    # | Yes/No     | No           | No              | Copy src to seed_dir,     |
    # | Ye         | Yes          |                 | set new location.         |
    # +------------+--------------+-----------------+---------------------------+

    assert isinstance(tid, int), "Torrent ID must be an integer."
    if not client.is_localhost:
        raise ValueError("Cannot manage download completion on a remote host.")

    data = client.torrent_get(
        fields=("name", "downloadDir", "files", "isPrivate"),
        ids=tid,
    )["torrents"][0]

    name = data["name"]
    download_dir = op.realpath(data["downloadDir"])
    seed_dir = client.seed_dir
    src = op.join(download_dir, name)
    src_in_seed_dir = op.commonpath((download_dir, seed_dir)) == seed_dir

    # Determine the destination
    if src_in_seed_dir:
        dst = Categorizer().categorize(data["files"])
        logger.info("Categorize '%s' as: %s", name, dst.name)
        dst = op.realpath(dsts.get(dst.value) or dsts[Cat.DEFAULT.value])
        if not op.isdir(src):
            # Create a directory for a single file torrent
            dst = op.join(dst, op.splitext(name)[0])
    else:
        dst = seed_dir

    # Ensure the dir exists (important!)
    os.makedirs(dst, exist_ok=True)

    if private_only and not data["isPrivate"]:
        # Torrent is not private and user only seeds private
        logger.info("Remove public torrent: %s", name)
        client.torrent_remove(tid, delete_local_data=False)
        if src_in_seed_dir:
            logger.info("Move: '%s' -> '%s'", src, dst)
            move_file(src, dst)
    else:
        # Torrent is private or user seeds any torrents
        logger.info("Copy: '%s' -> '%s'", src, dst)
        copy_file(src, dst)
        if not src_in_seed_dir:
            client.set_location(tid, seed_dir, move=False)


def copy_file(src: str, dst: str):
    """Copy src to dst, trying to use reflink.
    Result: `/src_path/name` -> `/dst_path` = `/dst_path/name`
    """
    try:
        subprocess.run(
            ("cp", "-a", "-f", "--reflink=auto", "--", src,
             dst if dst.endswith(os.sep) else dst + os.sep),
            check=True,
        )  # fmt: skip
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        if os.name != "nt":
            logger.warning("Copy command failed: %s", e)
        # Fallback
        if op.isdir(src):
            shutil.copytree(src, op.join(dst, op.basename(src)), dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def move_file(src: str, dst: str):
    """Move src to dst."""
    try:
        os.rename(src, op.join(dst, op.basename(src)))
    except OSError:
        # dst is a non-empty directory or on a different filesystem
        copy_file(src, dst)
        if op.isdir(src):
            shutil.rmtree(src, ignore_errors=True)
        else:
            os.unlink(src)


def parse_config(config_path):
    """Parse and validate the configuration file."""
    config = {
        "rpc-port": 9091,
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

    def _dump_config(config):
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config.update(json.load(f))

        # Validation
        if not isinstance(config["rpc-port"], int):
            raise ValueError("The 'rpc-port' must be an integer.")
        if config["download-dir"] and not op.isdir(config["download-dir"]):
            raise ValueError("The 'download-dir' is not a valid directory.")
        if not op.isdir(config["destinations"][Cat.DEFAULT.value]):
            raise ValueError("The 'destinations' default must be a valid directory.")

        # Password
        p: str = config["rpc-password"]
        if p:
            if p[0] == "{" and p[-1] == "}":
                config["rpc-password"] = base64.b64decode(p[-2:0:-1]).decode()
            else:
                config["rpc-password"] = (
                    f"{{{base64.b64encode(p.encode()).decode()[::-1]}}}"
                )
                _dump_config(config)
                config["rpc-password"] = p

    except FileNotFoundError:
        _dump_config(config)
        sys.exit(
            f"A blank configuration file has been created at '{config_path}'. "
            "Edit the settings before running this script again."
        )
    except json.JSONDecodeError:
        sys.exit(f"The configuration file at '{config_path}' is malformed.")
    except Exception as e:
        sys.exit(f"Configuration error: {e}")
    else:
        return config


def config_logger(logger: logging.Logger, logfile, log_level="INFO"):
    """Configure the logging system."""
    logger.handlers.clear()
    log_level = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }.get(log_level, logging.INFO)
    logger.setLevel(log_level)

    # Console handler
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)

    # FIle handler
    handler = logging.FileHandler(logfile)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)


def main():

    script_dir = op.dirname(__file__)
    conf = parse_config(op.join(script_dir, "config.json"))
    config_logger(logger, op.join(script_dir, "logfile.log"), conf["log-level"])

    flock = FileLocker(__file__)
    try:
        flock.acquire()
        client = TransmissionClient(
            port=conf["rpc-port"],
            username=conf["rpc-username"],
            password=conf["rpc-password"],
            seed_dir=conf["download-dir"],
        )

        tid = os.environ.get("TR_TORRENT_ID")
        logger.debug("ENV:TR_TORRENT_ID: %s", tid)
        if tid:
            # The script is invoked by Transmission as 'script-torrent-done'.
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
                    e,
                )

        sm = StorageManager(
            client=client,
            size_limit_gb=conf["download-dir-size-limit-gb"],
            space_floor_gb=conf["download-dir-space-floor-gb"],
            seed_dir_cleanup=conf["download-dir-cleanup-enable"],
            watch_dir=conf["watch-dir"],
            watch_dir_cleanup=conf["watch-dir-cleanup-enable"],
        )
        sm.cleanup()
        sm.apply_quotas()

    except Exception as e:
        logger.critical(e)

    finally:
        flock.release()


if __name__ == "__main__":
    main()
