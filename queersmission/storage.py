import os
import os.path as op
import shutil
import time
from functools import cached_property
from typing import Dict, List, Optional, Set

from . import logger
from .client import Client, TRStatus
from .utils import humansize, is_subpath

try:
    removesuffix = str.removesuffix  # Python 3.9+
except AttributeError:
    removesuffix = lambda s, f: s[: -len(f)] if f and s.endswith(f) else s


class StorageManager:

    def __init__(
        self,
        client: Client,
        seed_dir_purge: bool = False,
        size_limit_gb: int = 0,
        space_floor_gb: int = 0,
        watch_dir: Optional[str] = None,
    ) -> None:

        if not client.is_localhost:
            raise ValueError("Cannot manage storage on a remote host.")

        self.client = client
        self.seed_dir_purge = seed_dir_purge
        self.size_limit = gb_to_bytes(size_limit_gb)
        self.space_floor = gb_to_bytes(space_floor_gb)
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
            if t["downloadDir"] == seed_dir:
                allowed.add(t["name"])
            else:
                path = op.realpath(t["downloadDir"])
                if not is_subpath(path, seed_dir):
                    # Torrent is outside of seed_dir.
                    continue
                # Find the first segment after seed_dir.
                allowed.add(
                    path[len(seed_dir) :].lstrip(op.sep).partition(op.sep)[0]
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
        if self.seed_dir_purge:
            self._purge_seed_dir()

    def _clean_watch_dir(self) -> None:
        """Remove old or zero-length '.torrent' files from the watch-dir."""
        if not self.watch_dir:
            raise ValueError('Value "watch_dir" should not be null.')
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
                    logger.debug("Cleanup watch-dir: %s", e.path)
                    os.unlink(e.path)
            except OSError as e:
                logger.error(e)

    def _purge_seed_dir(self) -> None:
        """Remove files from seed_dir if they do not exist in Transmission."""
        if not self.seed_dir_purge:
            raise ValueError('Flag "seed_dir_purge" should be True.')
        allowed = self.allowed
        try:
            with os.scandir(self.client.seed_dir) as it:
                entries = tuple(e for e in it if e.name not in allowed)
        except OSError as e:
            logger.error(e)
            return
        for e in entries:
            try:
                if e.is_file() and removesuffix(e.name, ".part") in allowed:
                    continue
                logger.info("Cleanup seed-dir: %s", e.path)
                if e.is_dir():
                    shutil.rmtree(e.path, ignore_errors=True)
                else:
                    os.unlink(e.path)
            except OSError as e:
                logger.error(e)

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
        status = {TRStatus.STOPPED, TRStatus.SEED_WAIT, TRStatus.SEED}
        return (
            t
            for t in data
            if t["status"] in status
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
        leecher_counts = []
        for t in self._get_removables():
            leecher = 0
            for tracker in t["trackerStats"]:
                i = tracker["leecherCount"]  # int
                if i > 0:  # skip "unknown" (-1)
                    leecher += i
            leecher = max(leecher, sum(p["progress"] < 1 for p in t["peers"]))
            if leecher > 0:
                with_leechers.append(t)
                leecher_counts.append(leecher)
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
        survived = knapsack(
            weights=sizes,
            values=leecher_counts,
            capacity=sum(sizes) - size_to_free,
            max_cells=1024**2,
        )
        results.extend(t for i, t in enumerate(with_leechers) if i not in survived)
        return results


def gb_to_bytes(size) -> int:
    """Converts GiB to bytes. Returns 0 if the input is negative."""
    return int(size * 1073741824) if size > 0 else 0


def knapsack(
    weights: List[int],
    values: List[int],
    capacity: int,
    max_cells: Optional[int] = None,
) -> Set[int]:
    """
    Solve the 0-1 knapsack problem using dynamic programming.

    Args:
        weights (List[int]): The weights of the items.
        values (List[int]): The values of the items.
        capacity (int): The maximum capacity of the knapsack.
        max_cells (int, optional): Maximum number of cells in the DP table, used
        for scaling.

    Returns:
        Set[int]: A set of indices of the items to include to maximize value.
    """
    if not isinstance(capacity, int):
        raise TypeError('Expect "capacity" to be of type "int."')

    if capacity <= 0:
        return set()
    n = len(weights)
    if capacity >= sum(weights):
        return set(range(n))

    # Scale down
    # We want: (capacity / i + 1) * (n + 1) = max_cells
    if max_cells is not None:
        max_cells = max(2 * (n + 1), max_cells)
        i = capacity * (n + 1) / (max_cells - n - 1)  # scale factor
        if i > 1:
            weights = tuple(ceil(w / i) for w in weights)
            capacity = int(capacity // i)  # round up weights, round down capacity

    # Fill dynamic programming table
    dp = [[0] * (capacity + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        wt = weights[i - 1]
        vl = values[i - 1]
        for w in range(1, wt):
            dp[i][w] = dp[i - 1][w]
        for w in range(wt, capacity + 1):
            dp[i][w] = max(dp[i - 1][w], dp[i - 1][w - wt] + vl)

    # Backtrack to find which items are included
    res = set()
    w = capacity
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            res.add(i - 1)
            w -= weights[i - 1]
    return res


def ceil(n: float) -> int:
    """Computes the ceiling of a number."""
    i = int(n)
    return i + 1 if n != i and n > 0 else i
