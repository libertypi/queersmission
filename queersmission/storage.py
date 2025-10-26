import os
import os.path as op
import shutil
import time
from typing import List, Optional, Set

from . import logger
from .client import Client, Torrent
from .utils import humansize


class StorageManager:
    """Manages storage space in Transmission's seed directory."""

    def __init__(
        self,
        *,
        client: Client,
        quota_gib: int = 0,
        reserve_space_gib: int = 0,
        seed_dir_purge: bool = False,
        watch_dir: str = "",
    ) -> None:

        if quota_gib < 0 or reserve_space_gib < 0:
            raise ValueError("quota_gib and reserve_space_gib must be non-negative.")

        self.client = client
        self.quota = gib_to_bytes(quota_gib)
        self.reserve_space = gib_to_bytes(reserve_space_gib)
        self.seed_dir_purge = seed_dir_purge
        self.watch_dir = watch_dir

    def cleanup(self) -> None:
        """Perform the enabled cleanup tasks."""
        if self.watch_dir:
            self._clean_watch_dir()
        if self.seed_dir_purge:
            self._clean_seed_dir()

    def _clean_watch_dir(self) -> None:
        """Remove old or zero-length '.torrent' files from watch-dir."""
        assert self.watch_dir

        try:
            with os.scandir(self.watch_dir) as it:
                entries = [
                    e for e in it if op.splitext(e.name)[1].lower() == ".torrent"
                ]
        except OSError as err:
            logger.error("Error scanning watch-dir: %s", err)
            return

        for e in entries:
            try:
                if not e.is_file():
                    continue
                s = e.stat()
                if not s.st_size or s.st_mtime < time.time() - 3600:
                    logger.debug("Cleanup watch-dir: %s", e.path)
                    os.unlink(e.path)
            except OSError as err:
                logger.error('Error removing "%s": %s', e.path, err)

    def _clean_seed_dir(self) -> None:
        """Remove files from seed_dir if they do not exist in Transmission."""
        assert self.seed_dir_purge

        # Build a set of allowed first-level subdirs in seed_dir.
        allowed = set()
        seed_dir = self.client.seed_dir
        for t in self.client.seed_dir_torrents.values():
            if t.downloadDir != seed_dir:
                # Subdirectory: Find the first segment after seed_dir.
                name = op.relpath(t.downloadDir, seed_dir).partition(op.sep)[0]
                if name not in ("", ".", ".."):
                    allowed.add(name)
                    continue
            allowed.add(t.name)

        total = 0
        extras = []
        try:
            with os.scandir(self.client.seed_dir) as it:
                for e in it:
                    total += 1
                    if e.name in allowed:
                        continue
                    stem, ext = op.splitext(e.name)
                    if ext.lower() == ".part" and stem in allowed:
                        try:
                            if e.is_file():
                                continue
                        except OSError as err:
                            logger.error('Error checking "%s": %s', e.path, err)
                            continue
                    extras.append(e)
        except OSError as err:
            logger.error("Error scanning seed-dir: %s", err)
            return

        if extras and len(extras) == total:
            logger.warning("Skipping seed-dir cleanup: refused to delete all files.")
            return

        for e in extras:
            logger.info("Cleanup seed-dir: %s", e.path)
            try:
                if e.is_dir(follow_symlinks=False):
                    shutil.rmtree(e.path, ignore_errors=True)
                else:
                    os.unlink(e.path)
            except OSError as err:
                logger.error('Error removing "%s": %s', e.path, err)

    def apply_quotas(
        self,
        tid: Optional[int] = None,
        torrent_added: Optional[bool] = None,
    ):
        """
        Enforce size limits and free space requirements in seed_dir.

        If `tid` is set, ensure additional free space for this torrent. If
        `torrent_added` is True, the torrent is starting to download to
        seed_dir; if False, it has finished downloading elsewhere, waiting to be
        copied to seed_dir.

        If `tid` is None, perform a general quota check.
        """
        # +---+---------------+-------------+-----------------------+
        # |   | Mode          | In Seed Dir | Action                |
        # +---+---------------+-------------+-----------------------+
        # | 1 | torrent-added | True        | disk_free -= t_size   |
        # | 2 | torrent-added | False       | error                 |
        # | 3 | torrent-done  | True        | error                 |
        # | 4 | torrent-done  | False       | disk_free -= t_size;  |
        # |   |               |             | used_size += t_size   |
        # +---+---------------+-------------+-----------------------+

        client = self.client
        disk_total, disk_free = client.get_freespace()
        used_size = sum(t.sizeWhenDone for t in client.seed_dir_torrents.values())

        if tid is not None:
            if torrent_added is None:
                raise ValueError(
                    'Calling with "tid" but "torrent_added" is not specified.'
                )
            in_seed_dir = tid in client.seed_dir_torrents
            if torrent_added and not in_seed_dir:  # case 2
                raise ValueError(
                    'Calling as "torrent_added" but torrent not in seed_dir.'
                )
            if not torrent_added and in_seed_dir:  # case 3
                raise ValueError(
                    'Calling as "torrent_done" but torrent already in seed_dir.'
                )

            t_size = client.torrents[tid].sizeWhenDone
            disk_free -= t_size  # case 1 and 4
            if not torrent_added:  # case 4
                used_size += t_size

        cap = disk_total - self.reserve_space  # disk capacity
        if 0 < self.quota < cap:
            cap = self.quota  # user-defined quota

        size_to_free = max(
            used_size - cap,  # size limit
            self.reserve_space - disk_free,  # free space
        )

        if size_to_free <= 0:
            logger.debug("Storage OK. Headroom: %s.", humansize(-size_to_free))
            return

        logger.info("Storage limits exceeded by %s.", humansize(size_to_free))

        removal = self._find_optimal_removals(size_to_free)
        if removal:
            logger.info(
                'Remove %d torrent%s (%s): "%s"',
                len(removal),
                "" if len(removal) == 1 else "s",
                humansize(sum(t.sizeWhenDone for t in removal)),
                '", "'.join(t.name for t in removal),
            )
            client.torrent_remove([t.id for t in removal], delete_local_data=True)
        else:
            logger.warning("No suitable torrents found for removal.")

    def _find_optimal_removals(self, size_to_free: int) -> List[Torrent]:
        """
        Find an optimal set of torrents to remove to free at least
        `size_to_free` bytes. Tries to maximize the number of leechers among the
        remaining torrents. Returns a list of torrents to remove.
        """
        if size_to_free <= 0:
            raise ValueError('"size_to_free" must be positive.')

        # Classify torrents into two groups: those with leechers and those without.
        removal = []
        with_leechers = []
        leecher_counts = []
        for t in self._get_removal_cands():
            # leechers: the max leecher count among trackers (-1 if unknown),
            # or the number of connected peers that are not yet complete.
            leecher = max(
                max((ts["leecherCount"] for ts in t.trackerStats), default=0),
                sum(p["progress"] < 1 for p in t.peers),
            )
            if leecher > 0:
                with_leechers.append(t)
                leecher_counts.append(leecher)
            else:
                removal.append(t)

        # First: Pick all zero-leecher torrents, oldest activity first, until we
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

    def _get_removal_cands(self) -> List[Torrent]:
        """
        Get a list of torrents in seed_dir that are eligible for removal.
        Reannounces if needed to get up-to-date leecher counts.
        """
        fields = (
            "activityDate",
            "doneDate",
            "id",
            "name",
            "peers",
            "percentDone",
            "sizeWhenDone",
            "status",
            "trackerStats",
        )
        # Fetch and filter
        torrents = self.client.torrent_get(fields, tuple(self.client.seed_dir_torrents))
        torrents = self._filter_removal_cands(torrents)

        # Reannounce if:
        # - The torrent has at least one tracker, AND
        # - all trackers report 0 leechers, AND
        # - no tracker has a successful announce/scrape in the last 5 minutes.
        pending = set()
        cutoff = time.time() - 300  # 5 minutes ago
        for t in torrents:
            if t.trackerStats and all(
                ts["leecherCount"] <= 0 and not _announced_since(ts, cutoff)
                for ts in t.trackerStats
            ):
                pending.add(t.id)

        if not pending:
            return torrents

        cutoff = time.time()
        self.client.torrent_reannounce(tuple(pending))

        # Wait up to 20 seconds for reannounce to complete.
        deadline = time.monotonic() + 20
        while pending and time.monotonic() < deadline:
            time.sleep(3)
            for t in self.client.torrent_get(("id", "trackerStats"), tuple(pending)):
                if any(_announced_since(ts, cutoff) for ts in t.trackerStats):
                    pending.remove(t.id)

        # Fetch full details again.
        return self.client.torrent_get(fields, [t.id for t in torrents])

    @staticmethod
    def _filter_removal_cands(torrents: List[Torrent]):
        """Return torrents eligible for removal."""
        # Transmission status codes (libtransmission/transmission.h):
        # 0 = TR_STATUS_STOPPED        — Torrent is stopped.
        # 1 = TR_STATUS_CHECK_WAIT     — Queued to check files.
        # 2 = TR_STATUS_CHECK          — Checking files.
        # 3 = TR_STATUS_DOWNLOAD_WAIT  — Queued to download.
        # 4 = TR_STATUS_DOWNLOAD       — Downloading.
        # 5 = TR_STATUS_SEED_WAIT      — Queued to seed.
        # 6 = TR_STATUS_SEED           — Seeding.
        allowed_statuses = {0, 5, 6}
        cutoff = time.time() - 43200  # 12 hours grace period
        return [
            t
            for t in torrents
            if t.percentDone == 1.0
            and t.status in allowed_statuses
            and 0 < t.doneDate < cutoff
        ]


def gib_to_bytes(size) -> int:
    """Converts GiB to bytes."""
    return int(size * 1073741824)


def _announced_since(ts: dict, cutoff: float) -> bool:
    """Check if a tracker status has announced successfully since cutoff."""
    return (ts["lastAnnounceSucceeded"] and ts["lastAnnounceTime"] > cutoff) or (
        ts["lastScrapeSucceeded"] and ts["lastScrapeTime"] > cutoff
    )


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
        raise TypeError('"capacity" must be an integer.')

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
