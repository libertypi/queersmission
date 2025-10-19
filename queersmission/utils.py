import os.path as op
import re
import shutil
import sys

from . import logger


def _shutil_copy_file(src: str, dst: str) -> None:
    """Copy `src` to `dst` using shutil."""
    if op.isdir(src):
        shutil.copytree(
            src,
            dst,
            symlinks=True,
            copy_function=shutil.copy,
            dirs_exist_ok=True,
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
        Copy `src` to `dst` using cp. If `dst` exists, it will be overwritten.
        If `src` is a file and `dst` is a directory or vice versa, an OSError
        will be raised.
        """
        try:
            subprocess.run(
                ("cp", "-d", "-f", "-R", "--reflink=auto", "-T", "--", src, dst),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            # If cp reports nothing or unrecognized option, retry with shutil,
            # otherwise re-raise.
            stderr = e.stderr.strip()
            if stderr and not re.search(
                r"\b(unrecogni[sz]ed|invalid|unknown|illegal)\s+options?\b",
                stderr,
                re.IGNORECASE,
            ):
                raise OSError(stderr) from e
            logger.debug(stderr or e)
            _shutil_copy_file(src, dst)
        except FileNotFoundError as e:
            logger.debug(e)
            _shutil_copy_file(src, dst)

else:
    copy_file = _shutil_copy_file


def is_subpath(child: str, parent: str, sep: str = op.sep) -> bool:
    """
    Check if `child` is within `parent`. It's the caller's responsibility to
    ensure both paths are canonical.
    """
    if not child.endswith(sep):
        child += sep
    if not parent.endswith(sep):
        parent += sep
    return child.startswith(parent)


def humansize(size) -> str:
    """Convert a byte count to a human-readable IEC size up to YiB."""
    size = int(size)
    if size == 0:
        return "0.00 B"
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")
    idx = (abs(size).bit_length() - 1) // 10
    if idx >= len(units):
        idx = len(units) - 1
    return f"{size / (1 << (idx * 10)):.2f} {units[idx]}"
