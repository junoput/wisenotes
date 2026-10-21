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
    """A short reason for a failure, never text taken from the exception."""
    if isinstance(e, OSError) and e.errno in _WORDS:
        return _WORDS[e.errno]
    if isinstance(e, OSError):
        return f"system error {e.errno}" if e.errno is not None else "system error"
    return type(e).__name__
