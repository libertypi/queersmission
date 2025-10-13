import os.path as op
import shutil
from dataclasses import dataclass
from enum import IntEnum
from functools import cached_property
from typing import Dict, List, Optional, Tuple

import requests

from . import logger
from .utils import is_subpath


class TRStatus(IntEnum):
    STOPPED = 0
    CHECK_WAIT = 1
    CHECK = 2
    DOWNLOAD_WAIT = 3
    DOWNLOAD = 4
    SEED_WAIT = 5
    SEED = 6


@dataclass
class Torrent:
    """A Transmission torrent as returned by the "torrent-get" API."""

    activityDate: Optional[int] = None
    doneDate: Optional[int] = None
    downloadDir: Optional[str] = None
    files: Optional[list] = None
    id: Optional[int] = None
    isPrivate: Optional[bool] = None
    name: Optional[str] = None
    peers: Optional[list] = None
    percentDone: Optional[float] = None
    sizeWhenDone: Optional[int] = None
    status: Optional[TRStatus] = None
    trackerStats: Optional[list] = None


class Client:
    """A client for interacting with the local Transmission RPC interface."""

    _SSID = "X-Transmission-Session-Id"
    _RETRIES = 3
    _BAD_CODES = {401, 403, 409}

    def __init__(
        self,
        *,
        port: int = 9091,
        path: str = "/transmission/rpc",
        username: Optional[str] = None,
        password: Optional[str] = None,
        seed_dir: Optional[str] = None,
    ) -> None:

        self._url = f"http://127.0.0.1:{port}{path}"
        self._seed_dir = seed_dir

        self._session = requests.Session()
        if username and password:
            self._session.auth = (username, password)

    def _call(self, method: str, arguments: Optional[dict] = None, *, ids=None) -> dict:
        """Make a call to the Transmission RPC."""

        # If `ids` is omitted, all torrents are used.
        if ids is not None:
            check_ids(ids)
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
                res = self._session.post(self._url, json=query)
                if res.status_code not in self._BAD_CODES:
                    data = res.json()
                    logger.debug("Response: %s", data)
                    if data["result"] == "success":
                        return data["arguments"]
                elif res.status_code == 409:
                    self._session.headers[self._SSID] = res.headers[self._SSID]
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

    def torrent_get(self, fields: List[str], ids=None) -> List[Torrent]:
        return [
            Torrent(**t)
            for t in self._call("torrent-get", {"fields": fields}, ids=ids)["torrents"]
        ]

    def torrent_remove(self, ids, delete_local_data: bool):
        self._call(
            "torrent-remove",
            {"delete-local-data": delete_local_data},
            ids=ids,
        )

    def torrent_set(self, ids=None, **kwargs):
        self._call("torrent-set", kwargs, ids=ids)

    def torrent_set_location(self, ids, location: str, move: bool):
        self._call(
            "torrent-set-location",
            {"location": location, "move": move},
            ids=ids,
        )

    def get_freespace(self, path: Optional[str] = None) -> Tuple[int, int]:
        """
        Tests how much space is available in a client-specified folder. If
        `path` is None, test seed_dir.
        """
        if path is None:
            path = self.seed_dir
        try:
            res = shutil.disk_usage(path)
            return res.total, res.free
        except OSError as e:
            logger.warning(e)
        res = self._call("free-space", {"path": path})
        return res["total_size"], res["size-bytes"]

    @cached_property
    def session_settings(self) -> dict:
        """The complete settings returned by the "session-get" API."""
        return self._call("session-get")

    @cached_property
    def seed_dir(self) -> str:
        """The canonical path of the seed directory."""
        p = self._seed_dir or self.session_settings["download-dir"]
        if not p:
            raise ValueError("Cannot get seed_dir.")
        return op.realpath(p)

    @cached_property
    def _snapshot(self):
        """
        A snapshot of all and seed_dir torrents. `downloadDir` is canonicalized
        to real paths.
        """
        data = self.torrent_get(
            ("downloadDir", "id", "isPrivate", "name", "sizeWhenDone")
        )
        torrents = {t.id: t for t in data}
        seed_dir_torrents = torrents.copy()
        seed_dir = self.seed_dir

        for t in data:
            if t.downloadDir != seed_dir:
                t.downloadDir = op.realpath(t.downloadDir)  # Update to real path
                if not is_subpath(t.downloadDir, seed_dir):
                    # Torrent is outside of seed_dir.
                    del seed_dir_torrents[t.id]

        return torrents, seed_dir_torrents

    @property
    def torrents(self) -> Dict[int, Torrent]:
        """A dictionary of torrents known to Transmission, indexed by ID."""
        return self._snapshot[0]

    @property
    def seed_dir_torrents(self) -> Dict[int, Torrent]:
        """Torrents whose downloadDir is within seed_dir."""
        return self._snapshot[1]


def check_ids(ids):
    """Validate the IDs passed to the Transmission RPC.

    ids should be one of the following:
    - an integer referring to a torrent id
    - a list of torrent id numbers, SHA1 hash strings, or both
    - a string, 'recently-active', for recently-active torrents
    """
    for i in ids if isinstance(ids, (list, tuple)) else (ids,):
        if isinstance(i, int):
            if i >= 0:  # can it be 0?
                continue
        elif isinstance(i, str):
            if len(i) in (40, 64):  # SHA-1 or SHA-256
                try:
                    bytes.fromhex(i)
                    continue
                except ValueError:
                    pass
            elif ids == "recently-active":  # Not an element of `ids`!
                return
        raise ValueError(f'Invalid torrent ID "{i}" in IDs: {ids}')
