"""One version for the app's own static files, taken from their content.

base.html appends it to every stylesheet and script it loads, so a deploy that
changes any of them changes every URL, and nobody has to remember to bump a
number (style.css carried a hand-kept ?v=18; app.js carried none, 20261021-011).
Computed once at import: the container's files never change under a running
process. A module app.js imports itself (drag-drop.js) or loads later
(codemirror) has no query; main.py serves /static with Cache-Control: no-cache,
so the browser revalidates those against their ETag instead of guessing.
"""

import hashlib
from pathlib import Path

STATIC = Path(__file__).parent / "static"
# vendor/ is excluded: it changes only by a deliberate upgrade, and is still
# revalidated through no-cache like everything under /static.
OWN = ("css", "js")


def _version() -> str:
    digest = hashlib.sha256()
    files = sorted(p for d in OWN for p in (STATIC / d).rglob("*") if p.is_file())
    for f in files:
        digest.update(f.relative_to(STATIC).as_posix().encode() + b"\0")
        digest.update(f.read_bytes() + b"\0")
    return digest.hexdigest()[:12]


ASSET_VERSION = _version()
