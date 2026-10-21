"""The words a user is shown for a failed write: a fixed table keyed by errno.

An OSError's strerror is only as safe as whoever raised it: OSError(5,
"/srv/secret") would put a path on the page. The kernel's own messages are
fine, so the table holds those words, and anything else gets a neutral
description (20261021-051).
"""

import errno

_WORDS = {
    errno.ENOSPC: "No space left on device",
    errno.EDQUOT: "Disk quota exceeded",
    errno.EACCES: "Permission denied",
    errno.EPERM: "Operation not permitted",
    errno.EROFS: "Read-only file system",
    errno.EIO: "Input/output error",
    errno.ENOENT: "No such file or directory",
    errno.EEXIST: "File exists",
    errno.ENOTEMPTY: "Directory not empty",
    errno.EBUSY: "Device or resource busy",
    errno.EMFILE: "Too many open files",
    errno.ENFILE: "Too many open files in system",
    errno.ENAMETOOLONG: "File name too long",
}


def failure_reason(e: BaseException) -> str:
    """A short reason for a failure, never text taken from the exception, and it
    never raises. errno is only trusted when it is a real int: OSError("/srv/x",
    "y") stores the path as errno, and a list there is unhashable (20261021-052
    review)."""
    try:
        if not isinstance(e, OSError):
            return type(e).__name__
        code = e.errno
        if type(code) is not int:  # also excludes bool, a subclass of int
            return "system error"
        return _WORDS.get(code, f"system error {code}")
    except Exception:
        return "system error"
