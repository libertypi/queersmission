import logging
import os
import os.path as op
import tempfile
import time
from logging.handlers import RotatingFileHandler

from . import PKG_NAME, config, logger
from .cat import Cat, Categorizer
from .client import Client, TRStatus
from .filelock import FileLocker
from .storage import StorageManager
from .utils import copy_file, humansize, is_subpath


def config_logger(logfile: str, level: str = "INFO"):
    """Configure the logging system with both console and file handlers."""
    logger.handlers.clear()
    logger.propagate = False

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

    try:
        logger.setLevel(level.upper() or logging.INFO)
    except ValueError:
        logger.setLevel(logging.INFO)
        logger.error("Invalid logging level: %s", level)


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

    if not client.is_localhost:
        raise ValueError("Cannot manage download completion on a remote host.")

    t = client.torrent_get(
        fields=(
            "downloadDir",
            "files",
            "isPrivate",
            "name",
            "percentDone",
            "sizeWhenDone",
            "status",
        ),
        ids=tid,
    )["torrents"][0]
    _check_torrent_done(tid, t, client)

    src_dir = op.realpath(t["downloadDir"])
    name = t["name"]
    src = op.join(src_dir, name)

    src_in_seed_dir = is_subpath(src_dir, client.seed_dir)
    remove_torrent = private_only and not t["isPrivate"]

    # Determine the destination
    if src_in_seed_dir:
        c = Categorizer().categorize(t["files"])
        logger.info('Categorize "%s" as: %s', name, c.name)
        dst_dir = op.normpath(dests[c.value] or dests[Cat.DEFAULT.value])
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


def _check_torrent_done(tid: int, t: dict, client: Client, retry: int = 10):
    """Checks if a torrent has finished downloading. Retries every second.
    Raises TimeoutError after `retry` retries."""
    status = {TRStatus.STOPPED, TRStatus.SEED_WAIT, TRStatus.SEED}
    while t["percentDone"] < 1 or t["status"] not in status:
        if retry <= 0:
            raise TimeoutError("Timeout while waiting for torrent to finish.")
        time.sleep(1)
        t = client.torrent_get(("percentDone", "status"), tid)["torrents"][0]
        retry -= 1


def main(torrent_added: bool, config_dir: str):
    """Entry point for the script.

    Parameters:
     - torrent_added (bool): Indicates the mode of operation. If True, the
       function is triggered as 'script-torrent-added' to handle newly added
       torrents; if False, it operates as 'script-torrent-done' to manage
       completed torrents.
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
            logger.info(
                "Script-torrent-%s triggered with torrent ID: %s",
                "added" if torrent_added else "done",
                tid,
            )
            tid = int(tid)

        client = Client(
            port=conf["rpc-port"],
            path=conf["rpc-url"],
            username=conf["rpc-username"],
            password=conf["rpc-password"],
            seed_dir=conf["seed-dir"],
        )
        storage = StorageManager(
            client=client,
            seed_dir_purge=conf["seed-dir-purge"],
            size_limit_gb=conf["seed-dir-size-limit-gb"],
            space_floor_gb=conf["seed-dir-space-floor-gb"],
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
                dests=conf["destinations"],
                private_only=conf["only-seed-private"],
            )

    except Exception as e:
        logger.critical(str(e))

    else:
        logger.info("Execution completed in %.2f seconds.", time.perf_counter() - start)

    finally:
        flock.release()
