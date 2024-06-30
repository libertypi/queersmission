import os

from . import logger

_MODE = 0o666

if os.name == "nt":
    import msvcrt
    import time
    from errno import EDEADLK

    _FLAG = os.O_RDWR | os.O_TRUNC | os.O_CREAT

    class FileLocker:
        """A file locker that uses msvcrt for Windows platforms."""

        __slots__ = ("file", "fd")

        def __init__(self, file: str) -> None:
            self.file = file
            self.fd = None

        def acquire(self):
            """Acquire an exclusive lock on the file using msvcrt."""
            if self.fd is None:
                fd = os.open(self.file, _FLAG, _MODE)
                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                        break
                    except OSError as e:
                        # LK_LOCK raises EDEADLK after 10 retries
                        if e.errno != EDEADLK:
                            os.close(fd)
                            raise
                    time.sleep(1)
                self.fd = fd
                logger.debug("Lock acquired: %s", self.file)

        def release(self):
            """Release the acquired lock and close the file."""
            if self.fd is not None:
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                os.close(self.fd)
                self.fd = None
                try:
                    os.unlink(self.file)
                except OSError:
                    pass

else:
    try:
        import fcntl

        _FLAG = os.O_RDWR | os.O_TRUNC

        class FileLocker:
            """A file locker that uses fcntl for Unix-like systems."""

            __slots__ = ("file", "fd")

            def __init__(self, file: str) -> None:
                self.file = file
                self.fd = None

            def acquire(self):
                """Acquire an exclusive lock on the file using fcntl."""
                if self.fd is None:
                    try:
                        fd = os.open(self.file, _FLAG, _MODE)
                    except FileNotFoundError:
                        fd = os.open(self.file, _FLAG | os.O_CREAT, _MODE)
                        os.fchmod(fd, _MODE)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX)
                    except OSError:
                        os.close(fd)
                        raise
                    self.fd = fd
                    logger.debug("Lock acquired: %s", self.file)

            def release(self):
                """Release the acquired lock and close the file."""
                if self.fd is not None:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
                    os.close(self.fd)
                    self.fd = None

    except ImportError:

        class FileLocker:
            def __init__(self, *args, **kwargs):
                self._noop = lambda *args, **kwargs: None

            def __getattr__(self, _):
                return self._noop
