"""What a media block's content points at: one rule for import, the block view,
the edit form and the note's notice (20261021-009).

The CSP allows images from 'self' and data: only. The rule reads a URL the way
a browser does: tabs and newlines anywhere are removed, leading and trailing
spaces and control characters are ignored, the scheme's case does not matter,
and a backslash is a slash (so /\\host and \\\\host are another host, like //host).
"""

import re

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
    return "image" if url.startswith("/") else "other"
