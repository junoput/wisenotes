"""Which container may write the data directory, when two share it.

A deploy starts the new container beside the one serving, on the same data
directory, and smokes it before any request reaches it. Two containers must
never write that directory at once, so deploy/deploy.sh names the one that may
in <data>/.writer. It changes the name while holding an exclusive flock on
<data>/.writer.lock; every write holds a shared flock on that file for its
whole length. So a change of writer waits for the writes in flight to finish,
and after it the container no longer named refuses writes (20261022-035).

The container learns its own name from WISENOTES_WRITER_ID. Unset (development,
the tests, a container started by hand) means no fence: every write is allowed.
Set, a write is allowed only while .writer holds exactly that name; a missing
lock or name file refuses (fail closed), since deploy.sh writes both before it
starts a container.
"""

import fcntl
import logging
import os
from contextlib import contextmanager
from pathlib import Path

WRITER_FILE = ".writer"
LOCK_FILE = ".writer.lock"

logger = logging.getLogger(__name__)


def writer_id() -> str | None:
    return os.environ.get("WISENOTES_WRITER_ID") or None


def acquire(data_dir: Path) -> tuple[int | None, bool]:
    """Take the shared lock and say whether this container may write.

    Returns (fd, allowed). The lock is held until release(fd); fd is None when
    nothing is held. Blocks only while deploy.sh changes the writer."""
    me = writer_id()
    if me is None:
        return None, True
    try:
        fd = os.open(data_dir / LOCK_FILE, os.O_RDONLY)
    except OSError as e:
        # The reason only, never names or paths: deploy.sh --check repairs this.
        logger.warning("write refused: the writer lock file cannot be opened (errno %s)", e.errno)
        return None, False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        try:
            named = (data_dir / WRITER_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            named = None
    except BaseException:
        os.close(fd)
        raise
    if named != me:
        os.close(fd)
        logger.warning(
            "write refused: %s",
            "no writer file" if named is None else "another container is the named writer",
        )
        return None, False
    return fd, True


def release(fd: int | None) -> None:
    if fd is not None:
        os.close(fd)  # closing the only descriptor drops the flock


@contextmanager
def hold(data_dir: Path):
    """Yield whether this container may write, holding the shared lock until the block ends."""
    fd, allowed = acquire(data_dir)
    try:
        yield allowed
    finally:
        release(fd)
