import logging
import os
import os.path as op
import tempfile
import time
from logging.handlers import RotatingFileHandler
from typing import Dict

from . import PKG_NAME, config, logger
from .cat import Cat, Categorizer
from .client import Client, Torrent
from .filelock import FileLocker
from .storage import StorageManager
from .utils import copy_file, humansize, is_subpath


def init_logger(logfile: str, level: str = "INFO"):
    """Configure the logging system with both console and file handlers."""
    logger.handlers.clear()
    logger.propagate = False

    try:
        logger.setLevel(level.upper())
    except ValueError:
        logger.setLevel(logging.INFO)
        logger.warning('Invalid log level "%s", using INFO instead.', level)

    # Console handler
    hd = logging.StreamHandler()
    hd.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(hd)

    # Rotating File handler (10 MiB * 3)
    hd = RotatingFileHandler(logfile, maxBytes=10485760, backupCount=3)
    hd.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(hd)


def set_public_up_limit(tid: int, client: Client, limit_kbps: int):
    """Set upload limit for a public torrent."""
    if limit_kbps < 0:
        raise ValueError("limit_kbps must be non-negative.")
    t = client.torrents[tid]
    if t.isPrivate:
        return
    logger.debug(
        'Setting upload limit to %d kB/s for public torrent: "%s"',
        limit_kbps,
        t.name,
    )
    client.torrent_set(tid, uploadLimit=limit_kbps, uploadLimited=True)


def process_torrent_done(
    tid: int,
    client: Client,
    storage: StorageManager,
    dests: Dict[Cat, str],
    remove_public: bool,
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
        ("downloadDir", "files", "isPrivate", "name", "percentDone", "sizeWhenDone"),
        ids=tid,
    )
    try:
        t = t[0]
    except IndexError:
        raise ValueError(f"Torrent ID {tid} does not exist.")
    _ensure_torrent_done(tid, t, client)

    remove_torrent = remove_public and not t.isPrivate
    name = t.name
    size = t.sizeWhenDone

    src = t.downloadDir
    if src == client.seed_dir:
        src_in_seed_dir = True
    else:
        src = op.realpath(src)
        src_in_seed_dir = is_subpath(src, client.seed_dir)
    src = op.join(src, name)

    # Determine the destination
    if src_in_seed_dir:
        c = Categorizer().infer(t.files)
        logger.info('Categorize "%s" as: %s', name, c.name)
        dest_dir = dests[c] or dests[Cat.DEFAULT]
        # Create a directory for a single file torrent
        if not op.isdir(src):
            dest_dir = op.join(dest_dir, op.splitext(name)[0])
    else:
        dest_dir = client.seed_dir
        # Ensure free space in seed_dir
        if not remove_torrent:
            storage.apply_quotas(tid, torrent_added=False)

    # File operations
    if src_in_seed_dir or not remove_torrent:
        dst = op.join(dest_dir, name)
        os.makedirs(dest_dir, exist_ok=True)
        elapsed = time.perf_counter()
        copy_file(src, dst)
        elapsed = time.perf_counter() - elapsed
        logger.info(
            'Copied: "%s" -> "%s" (size: %s, elapsed: %.2fs, speed: %s/s)',
            src,
            dst,
            humansize(size),
            elapsed,
            humansize(size / elapsed) if elapsed else "N/A",
        )

    # Remove or redirect the torrent
    if remove_torrent:
        logger.debug("Remove public torrent: %s", name)
        client.torrent_remove(tid, delete_local_data=src_in_seed_dir)
    elif not src_in_seed_dir:
        client.torrent_set_location(tid, dest_dir, move=False)


def _ensure_torrent_done(tid: int, t: Torrent, client: Client, retry: int = 20):
    """Ensure the torrent is fully downloaded, retrying if necessary."""
    while t.percentDone < 1:
        if retry <= 0:
            raise TimeoutError(f"Timeout waiting for torrent ID {tid} to complete.")
        retry -= 1
        time.sleep(3)
        t = client.torrent_get(("percentDone",), tid)[0]


def main(torrent_added: bool, config_dir: str):
    """
    Main entry point.

    Parameters:
     - torrent_added (bool): The mode of operation. If True, the function is
       triggered as 'script-torrent-added' to handle newly added torrents; if
       False, it operates as 'script-torrent-done' to manage completed torrents.
     - config_dir (str): The configuration directory.
    """
    conf = config.parse(op.join(config_dir, "config.json"))
    init_logger(op.join(config_dir, "logfile.log"), conf["log-level"])

    flock = FileLocker(op.join(tempfile.gettempdir(), PKG_NAME + ".lock"))
    try:
        flock.acquire()
        start = time.perf_counter()

        client = Client(
            port=conf["rpc-port"],
            path=conf["rpc-path"],
            username=conf["rpc-username"],
            password=conf["rpc-password"],
            seed_dir=conf["seed-dir"],
        )
        storage = StorageManager(
            client=client,
            quota_gib=conf["seed-dir-quota-gib"],
            reserve_space_gib=conf["seed-dir-reserve-space-gib"],
            seed_dir_purge=conf["seed-dir-purge"],
            watch_dir=conf["watch-dir"],
        )

        tid = os.environ.get("TR_TORRENT_ID")
        if tid is None:
            # Script is invoked by user
            logger.debug(
                "Script invoked without a torrent ID, performing maintenance tasks."
            )
            storage.cleanup()
            storage.apply_quotas()

        else:
            # Script is invoked by Transmission
            logger.debug(
                "Script-torrent-%s triggered with torrent ID: %s",
                "added" if torrent_added else "done",
                tid,
            )
            tid = int(tid)

            if torrent_added:
                # Set upload limit for public torrents
                if conf["public-upload-limited"]:
                    set_public_up_limit(tid, client, conf["public-upload-limit-kbps"])

                # Clear junk in seed_dir and watch_dir
                storage.cleanup()

                # If new torrent is in seed_dir, ensure free space
                if tid in client.seed_dir_torrents:
                    storage.apply_quotas(tid, torrent_added=True)

            else:
                # Process completed torrent
                process_torrent_done(
                    tid=tid,
                    client=client,
                    storage=storage,
                    dests={c: conf[c.value] for c in Cat},
                    remove_public=conf["remove-public-on-complete"],
                )

    except Exception as e:
        logger.critical(
            'Error processing torrent "%s": %s',
            os.environ.get("TR_TORRENT_NAME", "N/A"),
            e,
        )
        logger.debug("Traceback:", exc_info=True)

    else:
        logger.debug("Execution completed in %.2f seconds", time.perf_counter() - start)

    finally:
        flock.release()
