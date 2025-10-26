import os.path as op
import shutil
from dataclasses import dataclass
from functools import cached_property
from typing import Dict, List, Optional, Sequence, Tuple

import requests

from . import logger
from .utils import is_subpath


@dataclass
class Torrent:
    """A Transmission torrent as returned by the "torrent-get" API."""

    activityDate: Optional[int] = None
    doneDate: Optional[int] = None
    downloadDir: Optional[str] = None
    files: Optional[List[dict]] = None
    id: Optional[int] = None
    isPrivate: Optional[bool] = None
    name: Optional[str] = None
    peers: Optional[List[dict]] = None
    percentDone: Optional[float] = None
    sizeWhenDone: Optional[int] = None
    status: Optional[int] = None
    trackerStats: Optional[List[dict]] = None


class Client:
    """A client for interacting with local Transmission RPC interface."""

    _SSID = "X-Transmission-Session-Id"
    _RETRIES = 3

    def __init__(
        self,
        *,
        port: int = 9091,
        path: str = "/transmission/rpc",
        username: str = "",
        password: str = "",
        seed_dir: str = "",
    ) -> None:
        if not path.startswith("/"):
            path = "/" + path

        self._url = f"http://127.0.0.1:{port}{path}"
        self._seed_dir = seed_dir

        self._session = requests.Session()
        if username and password:
            self._session.auth = (username, password)

    def _call(self, method: str, arguments: Optional[dict] = None, *, ids=None) -> dict:
        """
        Make a call to the Transmission RPC. If `ids` is an empty list, an empty
        result is returned. If `ids` is None, all torrents are returned.
        """
        query = {"method": method}
        if ids is not None:
            check_ids(ids)
            if arguments is None:
                arguments = {"ids": ids}
            else:
                arguments["ids"] = ids
        if arguments is not None:
            query["arguments"] = arguments

        last_err = None
        for attempt in range(1, self._RETRIES + 1):
            logger.debug("Query (attempt %d): %s", attempt, query)
            try:
                res = self._session.post(self._url, json=query)
                res.raise_for_status()

                data = res.json()
                logger.debug("Response: %s", data)

                if data["result"] == "success":
                    return data["arguments"]

                last_err = RuntimeError(f"Transmission RPC error: {data}")

            except requests.HTTPError as e:
                last_err = e
                res = e.response

                if res.status_code == 409:
                    self._session.headers[self._SSID] = res.headers.get(self._SSID, "")

                elif res.status_code in (401, 403):
                    raise PermissionError(
                        "Authentication failed for Transmission RPC."
                    ) from e

            except Exception as e:
                last_err = e

        raise last_err or RuntimeError("Unexpected execution flow in _call.")

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

    def torrent_get(self, fields: Sequence[str], ids=None) -> List[Torrent]:
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
        self.cache_clear()

    def torrent_set(self, ids=None, **kwargs):
        self._call("torrent-set", kwargs, ids=ids)

    def torrent_set_location(self, ids, location: str, move: bool):
        self._call(
            "torrent-set-location",
            {"location": location, "move": move},
            ids=ids,
        )
        self.cache_clear()

    def session_get(self, fields: Optional[Sequence[str]] = None) -> dict:
        return self._call("session-get", {"fields": fields} if fields else None)

    @cached_property
    def seed_dir(self) -> str:
        """The canonical path of the seed directory."""
        p = self._seed_dir or self.session_get(["download-dir"])["download-dir"]
        if not p:
            raise ValueError("Cannot get seed_dir.")
        return op.realpath(p)

    @cached_property
    def _snapshot(self):
        """
        A snapshot of the basic information for "all" and "seed_dir" torrents.
        `t.downloadDir` is canonicalized to real paths.
        """
        data = self.torrent_get(
            ("downloadDir", "id", "isPrivate", "name", "sizeWhenDone")
        )
        seed_dir_torrents = {}
        seed_dir = self.seed_dir

        for t in data:
            if t.downloadDir != seed_dir:
                t.downloadDir = op.realpath(t.downloadDir)  # Update to real path
                if not is_subpath(t.downloadDir, seed_dir):
                    # Torrent is outside of seed_dir.
                    continue
            seed_dir_torrents[t.id] = t

        return {t.id: t for t in data}, seed_dir_torrents

    @property
    def torrents(self) -> Dict[int, Torrent]:
        """All torrents known to Transmission: {id: Torrent}."""
        return self._snapshot[0]

    @property
    def seed_dir_torrents(self) -> Dict[int, Torrent]:
        """Torrents whose downloadDir is within seed_dir: {id: Torrent}."""
        return self._snapshot[1]

    def cache_clear(self):
        """
        Clear the '_snapshot' cache behind 'torrents' and 'seed_dir_torrents'
        properties.
        """
        self.__dict__.pop("_snapshot", None)

    def get_freespace(self, path: Optional[str] = None) -> Tuple[int, int]:
        """
        Tests how much space is available in `path`. If `path` is None, test
        seed_dir.
        """
        if path is None:
            path = self.seed_dir
        try:
            res = shutil.disk_usage(path)
            return res.total, res.free
        except OSError as e:
            logger.warning("shutil.disk_usage error: %s", e)
        # Fallback to Transmission API
        res = self._call("free-space", {"path": path})
        return res["total_size"], res["size-bytes"]


def check_ids(ids):
    """
    Validate the IDs passed to the Transmission RPC.

    ids should be one of the following:
    - an integer referring to a torrent id
    - a list of torrent id numbers, SHA1 hash strings, or both
    - a string, 'recently-active', for recently-active torrents
    """
    for i in ids if isinstance(ids, (list, tuple)) else (ids,):
        if isinstance(i, int):
            if i >= 0:
                continue
        elif isinstance(i, str):
            if len(i) == 40:  # SHA-1
                try:
                    bytes.fromhex(i)
                    continue
                except ValueError:
                    pass
            elif ids == "recently-active":  # not 'i'
                return
        raise ValueError(f'Invalid entry "{i}" in IDs: "{ids}"')
