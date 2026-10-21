"""What a media block's content points at: one rule for import, the block view,
the edit form and the note's notice (20261021-009).

The CSP allows images from 'self' and data: only. The rule reads a URL the way
a browser does: tabs and newlines anywhere are removed, leading and trailing
spaces and control characters are ignored, the scheme's case does not matter,
and a backslash is a slash (so /\\host and \\\\host are another host, like //host).
"""

import re
from urllib.parse import unquote
from urllib.parse import urlsplit

MISSING_PREFIX = "missing:"  # media block content for an image the import could not store

_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")
_INSIDE = re.compile(r"[\t\n\r]")
_EDGES = "".join(map(chr, range(0x21)))  # C0 controls and space


def clean(content: str | None) -> str:
    """The URL as a browser reads it: tabs and newlines removed, edges stripped."""
    return _INSIDE.sub("", content or "").strip(_EDGES)


def missing_name(content: str | None) -> str:
    """What an import placeholder says was not stored; "" for any other content.
    Read through the same cleaning as media_kind, so the two never disagree."""
    s = clean(content)
    return s[len(MISSING_PREFIX) :] if s.startswith(MISSING_PREFIX) else ""


_OUR_MEDIA = re.compile(r"^/api/notes/([^/]+)/media/([^/]+)$")


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 5.2.4, as browsers apply it, %2e counting as a dot: /./a/../b -> /b."""
    segments = path.split("/")[1:]
    out: list[str] = []
    for i, seg in enumerate(segments):
        last = i == len(segments) - 1
        dots = seg.lower().replace("%2e", ".")
        if dots in (".", ".."):
            if dots == ".." and out:
                out.pop()
            if last:
                out.append("")
            continue
        out.append(seg)
    return "/" + "/".join(out)


def local_path(content: str | None) -> str | None:
    """The path a browser would request on THIS server for a media block's URL,
    dot segments resolved and percent-decoded; None when the URL names another
    host, has a scheme, or is not an absolute path. Query and fragment are not
    part of which file is sent."""
    url = clean(content).replace("\\", "/")
    if not url.startswith("/") or url.startswith("//"):
        return None
    return unquote(_remove_dot_segments(urlsplit(url).path))


def our_media(content: str | None) -> tuple[str, str] | None:
    """(note id, file name) when a media block's URL names one of our stored
    images, read the way a browser reads it; None otherwise. The one parser for
    the in-use check, the existence check and media_kind (20261021-020)."""
    path = local_path(content)
    m = _OUR_MEDIA.match(path) if path is not None else None
    return (m.group(1), m.group(2)) if m else None


def media_kind(content: str | None) -> str:
    """One of:
    "empty"    nothing chosen yet;
    "missing"  an import placeholder, MISSING_PREFIX + what was not stored;
    "image"    a path on this server: drawn;
    "inline"   a data:image/ URL: drawn (the CSP allows data:). This says how
               to render, not what may be stored: import decodes and
               re-encodes it like any image (bundle._inline_image);
    "external" another host (http:, https:, //host): not drawn, the CSP blocks it;
    "other"    anything else (javascript:, file:, a relative path): not drawn,
               and dropped on import.
    """
    s = clean(content)
    if not s:
        return "empty"
    if s.startswith(MISSING_PREFIX):
        return "missing"
    url = s.replace("\\", "/")
    m = _SCHEME.match(url)
    if m:
        scheme = m.group(1).lower()
        if scheme == "data" and url[m.end() :].lower().startswith("image/"):
            return "inline"
        return "external" if scheme in ("http", "https") else "other"
    if url.startswith("//"):
        return "external"
    return "image" if local_path(s) is not None else "other"
