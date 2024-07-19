import os.path as op
import shutil
from enum import IntEnum
from functools import cached_property
from typing import List, Optional, Tuple

import requests

from . import logger


class TRStatus(IntEnum):
    STOPPED = 0
    CHECK_WAIT = 1
    CHECK = 2
    DOWNLOAD_WAIT = 3
    DOWNLOAD = 4
    SEED_WAIT = 5
    SEED = 6


class Client:
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

        self.session = requests.Session()
        if username and password:
            self.session.auth = (username, password)

        if host.lower() in {"127.0.0.1", "0.0.0.0", "::1", "localhost"}:
            self.is_localhost = True
            self.path_module = op
            self.normpath = op.realpath
        else:
            self.is_localhost = False

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
                logger.warning(e)
        res = self._call("free-space", {"path": path})
        return res["total_size"], res["size-bytes"]

    @cached_property
    def seed_dir(self) -> str:
        """The normalized seeding directory."""
        s = self._seed_dir or self.session_settings["download-dir"]
        if not s:
            raise ValueError("Cannot get seed_dir.")
        return self.normpath(s)

    @cached_property
    def session_settings(self) -> dict:
        """The complete settings returned by the "session-get" API."""
        return self._call("session-get")

    @cached_property
    def path_module(self):
        """The appropriate os.path module for the host."""
        # Only called when is_localhost is False.
        for k in ("config-dir", "download-dir", "incomplete-dir"):
            p = self.session_settings[k]
            if not p:
                continue
            if p[0] == "/" or ":" not in p:
                import posixpath as path
            else:
                import ntpath as path
            return path
        raise ValueError("Cannot determine path type for the remote host.")

    @cached_property
    def normpath(self):
        """The appropriate normpath function for the host."""
        # Only called when is_localhost is False.
        return self.path_module.normpath


def check_ids(ids):
    """Validate the IDs passed to the Transmission RPC.

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
            elif ids == "recently-active":
                return
        raise ValueError(f'Invalid torrent ID "{i}" in IDs: {ids}')
