"""Log records as one JSON object per line, in the conventions v6 vocabulary.

docs/OBSERVABILITY.md is the contract: the required field names, the severity
scale, a correlation id on every record of a request, and the leak rules (the
routed path only, never the query string, the Host header, or text a person
typed). Records go to standard output; nothing is exported, so there is no
collector to configure or to wait for (20261020-042).

An exception record carries its type, a fixed reason (failure_reason, never the
exception's own text), the stack frames without the final message line, and a
fingerprint on the type and the innermost frame under app/ (a library frame such as
pathlib's open() is the same whichever app function called it, and moves with the Python
version; with no app frame it is the innermost frame). The exception text is left
out because an OSError's message carries the data directory's paths, which are
note titles.
"""

import contextvars
import hashlib
import json
import logging
import os
import sys
import traceback
from datetime import UTC
from datetime import datetime
from pathlib import Path

from app.services.reasons import failure_reason

SERVICE_NAME = "wisenotes"
APP_DIR = Path(__file__).resolve().parent  # frames under here are the app's own
ENVIRONMENTS = ("dev", "staging", "prod")

# (severity_text, severity_number) by the stdlib level at or below which a record falls
_SEVERITY = (
    (logging.DEBUG - 1, "TRACE", 1),
    (logging.DEBUG, "DEBUG", 5),
    (logging.INFO, "INFO", 9),
    (logging.WARNING, "WARN", 13),
    (logging.ERROR, "ERROR", 17),
)
_FATAL = ("FATAL", 21)

correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def severity(levelno: int) -> tuple[str, int]:
    for ceiling, text, number in _SEVERITY:
        if levelno <= ceiling:
            return text, number
    return _FATAL


def service_identity() -> dict[str, str]:
    environment = os.environ.get("WISENOTES_ENVIRONMENT", "dev")
    return {
        "service.name": os.environ.get("OTEL_SERVICE_NAME") or SERVICE_NAME,
        # "unknown", not a guess: a build without WISENOTES_VERSION does not know it
        "service.version": os.environ.get("WISENOTES_VERSION") or "unknown",
        "deployment.environment": environment if environment in ENVIRONMENTS else "dev",
    }


def _site(frames: traceback.StackSummary) -> str:
    """file:function of the innermost frame under app/, else of the innermost frame."""
    if not frames:
        return "?"
    inside = [f for f in frames if Path(f.filename).is_relative_to(APP_DIR)]
    frame = (inside or frames)[-1]
    return f"{frame.filename.rsplit('/', 1)[-1]}:{frame.name}"


def _exception_fields(exc: BaseException, tb) -> dict[str, str]:
    frames = traceback.extract_tb(tb)
    site = _site(frames)
    kind = f"{type(exc).__module__}.{type(exc).__qualname__}"
    stack = "".join(traceback.format_list(frames))
    return {
        "exception.type": kind,
        "exception.message": failure_reason(exc),
        "exception.stacktrace": f"Traceback (most recent call last):\n{stack}{kind}",
        "error.fingerprint": hashlib.sha256(f"{kind}@{site}".encode()).hexdigest()[:16],
    }


class JsonFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__()
        self.identity = service_identity()

    def format(self, record: logging.LogRecord) -> str:
        text, number = severity(record.levelno)
        stamp = datetime.fromtimestamp(record.created, UTC)
        out = {
            "timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z",
            "severity_text": text,
            "severity_number": number,
            **self.identity,
            "body": record.getMessage(),
            "logger": record.name,
        }
        cid = correlation_id.get()
        if cid:
            out["correlation_id"] = cid
        for key, value in getattr(record, "attrs", {}).items():
            out.setdefault(key, value)  # a caller's field never re-spells a required one
        if record.exc_info and record.exc_info[1] is not None:
            out.update(_exception_fields(record.exc_info[1], record.exc_info[2]))
        return json.dumps(out, ensure_ascii=False, default=str)


def configure() -> None:
    """Send every record, uvicorn's included, to stdout as JSON.

    Runs when app.main is imported, which uvicorn does after applying its own
    logging config, so this replaces uvicorn's handlers. Its access log is
    switched off: the request record in app.main replaces it, because uvicorn's
    line carries the query string."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for old in list(root.handlers):
        if isinstance(getattr(old, "formatter", None), JsonFormatter):
            root.removeHandler(old)  # a second import must not double every line
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    environment = os.environ.get("WISENOTES_ENVIRONMENT")
    if environment is not None and environment not in ENVIRONMENTS:
        logging.getLogger(__name__).warning(
            "WISENOTES_ENVIRONMENT is not one of dev, staging, prod; logging as dev"
        )


def request_severity(status: int) -> int:
    """INFO for a success, WARN for the caller's failure (4xx), ERROR for ours (5xx)."""
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.INFO
