"""The picture of a graph block's default view (20261022-064, slice 5).

A graph block is drawn by scripts. Without them, and on paper, a picture of its default
view stands in for the drawing. The picture is a stored image of the note, named after the
definition it shows:

    graph-<first 16 hex of sha256 of the definition>.webp

so there is no new field and no link to keep true. A definition that changes has another
name, and the block falls back to its text until a browser draws it and sends the picture
(graph-snapshot.js does that after a draw that finds none). The server never draws a graph.

What the server decides, and what it takes from the client:
- The client names the definition it drew (`spec`). The server compares that with the hash
  of the definition it stores NOW and refuses a mismatch (stale); the file name comes from the
  stored definition, never from the client.
- The image is decided by its content like any upload (charter R3): re-encoded to WebP,
  pixel-capped, SVG refused. A GIF would be kept as received, so it is refused here.
"""

from __future__ import annotations

import hashlib
import re

from app.services.image_processing import UnsupportedImage
from app.services.image_processing import process_uploaded_image

# The client sends a 2x picture of a board, about 100 KB as PNG; a flat colour or a dense
# curve stays far below this. Over it is not a snapshot of a board.
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024

_NAME = re.compile(r"graph-[0-9a-f]{16}\.webp")  # fullmatch: `$` would pass a trailing newline


def spec_hash(content: str | None) -> str:
    """16 hex characters naming a definition. Line ends are read as the newline the block
    stores (a plain form posts CRLF), so one definition has one name."""
    text = (content or "").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def snapshot_name(content: str | None) -> str:
    return f"graph-{spec_hash(content)}.webp"


def is_snapshot(name: str) -> bool:
    """Is this stored file named like a snapshot? The gallery hides these, and a save of a
    new snapshot removes the ones no graph block of the note names any more."""
    return _NAME.fullmatch(name) is not None


def decide(raw: bytes) -> bytes:
    """The bytes to store for an uploaded snapshot; UnsupportedImage (message safe to show)
    when it is not an image this app stores, or not one that is re-encoded to WebP."""
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise UnsupportedImage(f"A snapshot is at most {MAX_SNAPSHOT_BYTES // (1024 * 1024)} MB")
    _, data, meta = process_uploaded_image("graph-snapshot.png", raw)
    if meta.mime_type != "image/webp":
        raise UnsupportedImage("A snapshot is a PNG, JPEG or WebP picture")
    return data
