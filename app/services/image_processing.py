"""Image processing pipeline for uploaded media.

Every upload is decided by its CONTENT, never by its filename:

- Pillow must open it. Anything it cannot decode is refused (UnsupportedImage).
- GIF (Pillow says so) is kept byte-for-byte to preserve animation; a GIF is
  a binary format with no script surface.
- Everything else Pillow decodes is re-encoded to WebP, resized to a maximum
  side, which also strips metadata and any payload hidden behind the pixels.
- SVG is refused: it is XML that can carry scripts and is served from the
  app's own origin. Unknown types are refused rather than stored as-is.

Filenames are minted here; the caller's name is only kept in the metadata.
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
from dataclasses import dataclass

from PIL import Image
from PIL import UnidentifiedImageError

logger = logging.getLogger(__name__)

# Maximum dimensions (longest side)
MAX_IMAGE_DIMENSION = 2048
# WebP quality (0-100)
WEBP_QUALITY = 82
# What a stored media file may be, and how it is served
STORED_MEDIA_TYPES = {".webp": "image/webp", ".gif": "image/gif"}


class UnsupportedImage(ValueError):
    """The upload is not an image this app stores; the message is safe to show."""


@dataclass
class ImageMetadata:
    """Metadata about a processed image, intended for storage in note JSON."""

    original_filename: str
    stored_filename: str
    mime_type: str
    width: int | None = None
    height: int | None = None
    file_size: int = 0
    is_vector: bool = False
    is_animated: bool = False

    def to_dict(self) -> dict:
        return {
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
            "file_size": self.file_size,
            "is_vector": self.is_vector,
            "is_animated": self.is_animated,
        }


def _generate_unique_name(original: str, ext: str) -> str:
    """Generate a unique, collision-free filename."""
    # Use timestamp + short hash of original name
    ts = str(int(time.time() * 1000))
    digest = hashlib.md5(original.encode()).hexdigest()[:8]
    return f"{ts}_{digest}{ext}"


def process_uploaded_image(filename: str, content: bytes) -> tuple[str, bytes, ImageMetadata]:
    """Decide by content. Returns (stored_filename, bytes_to_store, metadata) or raises UnsupportedImage."""
    if filename.lower().rsplit(".", 1)[-1] in ("svg", "svgz") or content.lstrip()[:5].lower() in (
        b"<?xml",
        b"<svg ",
    ):
        raise UnsupportedImage("SVG is not accepted; upload a raster image (PNG, JPEG, WebP, GIF)")
    try:
        with Image.open(io.BytesIO(content)) as probe:
            fmt = probe.format
            probe.verify()  # structural check on the whole file before decoding pixels
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise UnsupportedImage("Not a readable image") from e
    if fmt == "GIF":
        return _process_gif(filename, content)
    return _process_raster(filename, content)


def _process_gif(filename: str, content: bytes) -> tuple[str, bytes, ImageMetadata]:
    """GIF is kept as received (verified above) so animation survives."""
    with Image.open(io.BytesIO(content)) as img:
        width, height = img.size
        animated = getattr(img, "n_frames", 1) > 1
    new_name = _generate_unique_name(filename, ".gif")
    meta = ImageMetadata(
        original_filename=filename,
        stored_filename=new_name,
        mime_type="image/gif",
        width=width,
        height=height,
        file_size=len(content),
        is_animated=animated,
    )
    return new_name, content, meta


def _process_raster(filename: str, content: bytes) -> tuple[str, bytes, ImageMetadata]:
    """Convert raster image to WebP with resizing."""

    with Image.open(io.BytesIO(content)) as img:
        # Preserve transparency (convert to RGBA if palette with transparency)
        if img.mode == "P" and "transparency" in img.info:
            img = img.convert("RGBA")
        elif img.mode not in ("RGB", "RGBA"):
            # Convert to RGB/RGBA — retain alpha if present
            if img.mode in ("LA", "PA"):
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")

        # Resize if too large
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIMENSION:
            ratio = MAX_IMAGE_DIMENSION / max(w, h)
            new_w = int(w * ratio)
            new_h = int(h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            w, h = img.size

        # Save as WebP
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=4)
        processed = buf.getvalue()

    new_name = _generate_unique_name(filename, ".webp")
    meta = ImageMetadata(
        original_filename=filename,
        stored_filename=new_name,
        mime_type="image/webp",
        width=w,
        height=h,
        file_size=len(processed),
    )
    return new_name, processed, meta
