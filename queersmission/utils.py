import os
import os.path as op
import re
import shutil
import sys
from functools import lru_cache

from . import logger

re_compile = lru_cache(maxsize=None)(re.compile)


def _copy_file_fallback(src: str, dst: str) -> None:
    """Copy src to dst using shutil."""
    if op.isdir(src):
        shutil.copytree(
            src, dst, symlinks=True, copy_function=shutil.copy, dirs_exist_ok=True
        )
    else:
        # Avoid shutil.copy() because if dst is a dir, we want to throw an error
        # instead of copying src into it.
        shutil.copyfile(src, dst, follow_symlinks=False)
        shutil.copymode(src, dst, follow_symlinks=False)


if sys.platform.startswith("linux"):
    import subprocess

    def copy_file(src: str, dst: str) -> None:
        """
        Copy src to dst, trying to use reflink. If dst exists, it will be
        overwritten. If src is a file and dst is a directory or vice versa, an
        error will occur.

        Example:
            `copy_file("/src_dir/name", "/dst_dir/name")` -> "/dst_dir/name"
        """
        try:
            subprocess.run(
                ("cp", "-d", "-f", "-R", "--reflink=auto", "-T", "--", src, dst),
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(e.stderr.strip().decode() or str(e))
            _copy_file_fallback(src, dst)
        except FileNotFoundError as e:
            logger.warning(str(e))
            _copy_file_fallback(src, dst)

else:
    copy_file = _copy_file_fallback


def is_subpath(child: str, parent: str, sep: str = os.sep) -> bool:
    """Check if `child` is within `parent`. Both paths must be absolute and
    normalized."""
    if not child.endswith(sep):
        child += sep
    if not parent.endswith(sep):
        parent += sep
    return child.startswith(parent)


def humansize(size: int) -> str:
    """Convert bytes to human readable sizes."""
    for suffix in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
        if -1024 < size < 1024:
            return f"{size:.2f} {suffix}B"
        size /= 1024
    return f"{size:.2f} YiB"
