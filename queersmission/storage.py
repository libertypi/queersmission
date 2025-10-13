import os
import os.path as op
import shutil
import time
from typing import Dict, List, Optional, Set

from . import logger
from .client import Client, Torrent, TRStatus
from .utils import humansize

try:
    removesuffix = str.removesuffix  # Python 3.9+
except AttributeError:
    removesuffix = lambda s, f: s[: -len(f)] if f and s.endswith(f) else s


class StorageManager:
    """Manages storage space in Transmission's seed directory."""

    def __init__(
        self,
        client: Client,
        seed_dir_purge: bool = False,
        quota_gib: int = 0,
        reserve_space_gib: int = 0,
        watch_dir: Optional[str] = None,
    ) -> None:
        if quota_gib < 0 or reserve_space_gib < 0:
            raise ValueError("Quota and reserve space must be non-negative.")

        self.client = client
        self.seed_dir_purge = seed_dir_purge
        self.quota = gib_to_bytes(quota_gib)
        self.reserve_space = gib_to_bytes(reserve_space_gib)
        self.watch_dir = watch_dir

    def cleanup(self) -> None:
        """Perform the enabled cleanup tasks."""
        if self.watch_dir:
            self._clean_watch_dir()
        if self.seed_dir_purge:
            self._clean_seed_dir()

    def _clean_watch_dir(self) -> None:
        """Remove old or zero-length '.torrent' files from the watch-dir."""
        assert self.watch_dir
        try:
            with os.scandir(self.watch_dir) as it:
                entries = [
                    e for e in it if op.splitext(e.name)[1].lower() == ".torrent"
                ]
        except OSError as err:
            logger.error(err)
            return
        for e in entries:
            try:
                s = e.stat()
                if e.is_file() and (not s.st_size or s.st_mtime < time.time() - 3600):
                    logger.debug("Cleanup watch-dir: %s", e.path)
                    os.unlink(e.path)
            except OSError as err:
                logger.error(err)

    def _clean_seed_dir(self) -> None:
        """Remove files from seed_dir if they do not exist in Transmission."""
        assert self.seed_dir_purge

        # Build a set of allowed first-level subdirs in seed_dir.
        seed_dir = self.client.seed_dir
        allowed = set()
        for t in self.client.seed_dir_torrents.values():
            if t.downloadDir != seed_dir:
                # Subdirectory: Find the first segment after seed_dir.
                name = op.relpath(t.downloadDir, seed_dir).partition(op.sep)[0]
                if name not in ("", ".", ".."):
                    allowed.add(name)
                    continue
            allowed.add(t.name)

        try:
            with os.scandir(self.client.seed_dir) as it:
                entries = [e for e in it if e.name not in allowed]
        except OSError as err:
            logger.error(err)
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
            except OSError as err:
                logger.error(err)

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
        # NOTE: This function does not fully test these conditions. It is
        # assumed to be called only under cases 1 and 4, before files are added
        # to seed_dir.
        total, free = self.client.get_freespace()
        total_size = sum(t.sizeWhenDone for t in self.client.seed_dir_torrents.values())

        if add_size is not None:  # cases 1, 4
            free -= add_size
            if not in_seed_dir:  # case 4
                total_size += add_size

        cap = total - self.reserve_space  # disk capacity
        if 0 < self.quota < cap:
            cap = self.quota  # user limit

        size_to_free = max(
            total_size - cap,  # size limit
            self.reserve_space - free,  # free space
        )

        if size_to_free <= 0:
            logger.debug("No need to free up space.")
            return

        logger.info("Storage limits exceeded by %s.", humansize(size_to_free))

        removal = self._find_optimal_removals(size_to_free)
        if removal:
            logger.info(
                "Remove %d torrent%s (%s): %s",
                len(removal),
                "" if len(removal) == 1 else "s",
                humansize(sum(t.sizeWhenDone for t in removal)),
                ", ".join(t.name for t in removal),
            )
            self.client.torrent_remove(
                ids=[t.id for t in removal],
                delete_local_data=True,
            )
        else:
            logger.warning("No suitable torrents found for removal.")

    def _find_optimal_removals(self, size_to_free: int) -> List[Torrent]:
        """Find an optimal set of torrents to remove to free up `size_to_free`
        bytes of space.
        """
        if size_to_free <= 0:
            raise ValueError('Expect "size_to_free" to be a positive integer.')
        # Categorize torrents based on leecher count.
        removal = []
        with_leechers = []
        leecher_counts = []
        for t in self._get_removal_cands():
            # leachers: the max leecher count among trackers (-1 if unknown),
            # or the number of connected peers that are not yet complete.
            leecher = max(
                max((ts["leecherCount"] for ts in t.trackerStats), default=0),
                sum(p["progress"] < 1 for p in t.peers),
            )
            if leecher > 0:
                with_leechers.append(t)
                leecher_counts.append(leecher)
            else:
                # Add zero-leecher torrents to removal list.
                removal.append(t)

        # First: Pick all zero-leecher torrents, least active first, until we
        # satisfy the size requirement.
        removal.sort(key=lambda t: t.activityDate)
        for i, t in enumerate(removal):
            size_to_free -= t.sizeWhenDone
            if size_to_free <= 0:
                return removal[: i + 1]

        # Second: Use knapsack to pick among the remaining torrents to maximize
        # the number of leechers.
        sizes = [t.sizeWhenDone for t in with_leechers]
        keep = knapsack(
            weights=sizes,
            values=leecher_counts,
            capacity=sum(sizes) - size_to_free,
            max_cells=1024**2,
        )
        removal.extend(t for i, t in enumerate(with_leechers) if i not in keep)
        return removal

    def _get_removal_cands(self):
        """Get torrents that are candidates for removal."""
        torrents = self.client.torrent_get(
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
            ids=list(self.client.seed_dir_torrents),
        )
        # Torrents are only removed if they have been completed for more than 12
        # hours in case another instance is waiting to process them.
        threshold = time.time() - 43200
        statuses = {TRStatus.STOPPED, TRStatus.SEED_WAIT, TRStatus.SEED}
        return (
            t
            for t in torrents
            if t.percentDone == 1
            and t.status in statuses
            and 0 < t.doneDate < threshold
        )


def gib_to_bytes(size) -> int:
    """Converts GiB to bytes."""
    return int(size * 1073741824)


def knapsack(
    weights: List[int],
    values: List[int],
    capacity: int,
    max_cells: Optional[int] = None,
) -> Set[int]:
    """
    Solve the 0-1 knapsack problem via dynamic programming.

    Args:
        weights (List[int]): Item weights.
        values (List[int]): Item values.
        capacity (int): Maximum knapsack capacity.
        max_cells (int, optional): Target upper bound on DP table cells,
            used to scale down the capacity/weights for speed.

    Returns:
        Set[int]: Indices of the items forming a maximum-value solution.
    """
    if not isinstance(capacity, int):
        raise TypeError(f'Expect "capacity" to be an integer, not {type(capacity)}.')
    if capacity <= 0:
        return set()
    n = len(weights)
    if capacity >= sum(weights):
        return set(range(n))

    # Optional scaling to bound DP size:
    # Target: (capacity / scale + 1) * (n + 1) ≈ max_cells
    if max_cells is not None:
        max_cells = max(2 * (n + 1), max_cells)
        scale = capacity * (n + 1) / (max_cells - n - 1)  # denom >= (n + 1) >= 1
        if scale > 1:
            weights = [ceil(w / scale) for w in weights]  # round weights up
            capacity = int(capacity // scale)  # round capacity down

    # DP table: dp[i][w] = best value using first i items with capacity w
    dp = [[0] * (capacity + 1)]  # row 0

    for i in range(1, n + 1):
        wt = weights[i - 1]
        vl = values[i - 1]
        pre = dp[-1]
        cur = pre[:]  # copy the previous row
        for w in range(wt, capacity + 1):
            cand = pre[w - wt] + vl
            if cand > cur[w]:
                cur[w] = cand
        dp.append(cur)

    # Backtrack to recover chosen items
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
    return i + 1 if i < n else i
