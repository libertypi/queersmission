import logging
import os
import os.path as op
import tempfile
import time

from . import PKG_NAME, config, logger
from .cat import Cat, Categorizer
from .client import Client
from .filelock import FileLocker
from .storage import StorageManager
from .utils import copy_file, humansize, is_subpath


def config_logger(logfile: str, level: str = "INFO"):
    """Configure the logging system with both console and file handlers."""
    logger.handlers.clear()
    logger.propagate = False
    try:
        logger.setLevel(level.upper() or logging.INFO)
    except ValueError:
        logger.setLevel(logging.INFO)

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


def process_torrent_done(
    tid: int,
    client: Client,
    storage: StorageManager,
    dests: dict,
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

    t = client.torrent_get(
        fields=(
            "downloadDir",
            "files",
            "isPrivate",
            "name",
            "percentDone",
            "sizeWhenDone",
        ),
        ids=tid,
    )["torrents"][0]
    _check_torrent_done(tid, t, client)

    remove_torrent = private_only and not t["isPrivate"]
    src = t["downloadDir"]
    if src == client.seed_dir:
        src_in_seed_dir = True
    else:
        src = op.realpath(src)
        src_in_seed_dir = is_subpath(src, client.seed_dir)
    name = t["name"]
    src = op.join(src, name)
    size = t["sizeWhenDone"]

    # Determine the destination
    if src_in_seed_dir:
        c = Categorizer().categorize(t["files"])
        logger.info('Categorize "%s" as: %s', name, c.name)
        dest_dir = dests[c] or dests[Cat.DEFAULT]
        # Create a directory for a single file torrent
        if not op.isdir(src):
            dest_dir = op.join(dest_dir, op.splitext(name)[0])
    else:
        dest_dir = client.seed_dir
        # Ensure free space in seed_dir
        if not remove_torrent:
            storage.apply_quotas(size, in_seed_dir=False)

    # File operations
    if src_in_seed_dir or not remove_torrent:
        dst = op.join(dest_dir, name)
        os.makedirs(dest_dir, exist_ok=True)
        elapsed = time.perf_counter()
        copy_file(src, dst)
        elapsed = time.perf_counter() - elapsed
        logger.info(
            'Copied: "%s" -> "%s" (elapsed: %.2fs, speed: %s/s, size: %s)',
            src,
            dst,
            elapsed,
            humansize(size / elapsed) if elapsed else "N/A",
            humansize(size),
        )

    # Remove or redirect the torrent
    if remove_torrent:
        logger.debug("Remove public torrent: %s", name)
        client.torrent_remove(tid, delete_local_data=src_in_seed_dir)
    elif not src_in_seed_dir:
        client.torrent_set_location(tid, dest_dir, move=False)


def _check_torrent_done(tid: int, t: dict, client: Client, retry: int = 10):
    """Checks if a torrent has finished downloading. Retries every second.
    Raises TimeoutError after `retry` retries."""
    while t["percentDone"] < 1:
        if retry <= 0:
            raise TimeoutError("Timeout while waiting for torrent to finish.")
        retry -= 1
        time.sleep(1)
        t = client.torrent_get(("percentDone",), tid)["torrents"][0]


def main(torrent_added: bool, config_dir: str):
    """Entry point for the script.

    Parameters:
     - torrent_added (bool): The mode of operation. If True, the function is
       triggered as 'script-torrent-added' to handle newly added torrents; if
       False, it operates as 'script-torrent-done' to manage completed torrents.
     - config_dir (str): The configuration directory.
    """
    config_dir = op.abspath(config_dir)
    conf = config.parse(op.join(config_dir, "config.json"))
    config_logger(op.join(config_dir, "logfile.log"), conf["log-level"])

    flock = FileLocker(op.join(tempfile.gettempdir(), PKG_NAME + ".lock"))
    try:
        flock.acquire()
        start = time.perf_counter()

        tid = os.environ.get("TR_TORRENT_ID")
        if tid is not None:
            logger.debug(
                "Script-torrent-%s triggered with torrent ID: %s",
                "added" if torrent_added else "done",
                tid,
            )
            tid = int(tid)

        client = Client(
            port=conf["rpc-port"],
            path=conf["rpc-path"],
            username=conf["rpc-username"],
            password=conf["rpc-password"],
            seed_dir=conf["seed-dir"],
        )
        storage = StorageManager(
            client=client,
            seed_dir_purge=conf["seed-dir-purge"],
            quota_gib=conf["seed-dir-quota-gib"],
            reserve_space_gib=conf["seed-dir-reserve-space-gib"],
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
                dests={c: conf[c.value] for c in Cat},
                private_only=conf["only-seed-private"],
            )

    except Exception as e:
        logger.critical(e)

    else:
        logger.debug("Execution completed in %.2f seconds", time.perf_counter() - start)

    finally:
        flock.release()
