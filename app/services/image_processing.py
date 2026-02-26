"""Image processing pipeline for uploaded media.

Handles:
- Raster images (JPEG, PNG, BMP, TIFF, etc.) → converted to WebP
- SVG files → kept as-is (vector graphics)
- GIF files → kept as-is (animated graphics)
- Automatic resizing of oversized images
- Unique filename generation to avoid conflicts
- Metadata extraction for storage in note JSON
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum dimensions (longest side)
MAX_IMAGE_DIMENSION = 2048
# Maximum file size in bytes (5 MB for processed output)
MAX_OUTPUT_BYTES = 5 * 1024 * 1024
# WebP quality (0-100)
WEBP_QUALITY = 82

# File extensions that are kept as-is
VECTOR_EXTENSIONS = {".svg", ".svgz"}
ANIMATED_EXTENSIONS = {".gif"}
# Raster image extensions that will be converted
RASTER_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif",
    ".webp", ".ico", ".ppm", ".pgm", ".pbm",
}


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


def _classify_file(filename: str) -> str:
    """Classify file as 'vector', 'animated', 'raster', or 'unknown'."""
    ext = Path(filename).suffix.lower()
    if ext in VECTOR_EXTENSIONS:
        return "vector"
    if ext in ANIMATED_EXTENSIONS:
        return "animated"
    if ext in RASTER_EXTENSIONS:
        return "raster"
    return "unknown"


def process_uploaded_image(
    filename: str,
    content: bytes,
) -> tuple[str, bytes, ImageMetadata]:
    """Process an uploaded image file.

    Returns:
        (new_filename, processed_bytes, metadata)
    """
    classification = _classify_file(filename)

    if classification == "vector":
        return _process_vector(filename, content)
    if classification == "animated":
        return _process_animated(filename, content)
    if classification == "raster":
        return _process_raster(filename, content)

    # Unknown type — attempt raster processing, fall back to pass-through
    try:
        return _process_raster(filename, content)
    except Exception:
        logger.warning("Unknown image type for %s, storing as-is", filename)
        new_name = _generate_unique_name(filename, Path(filename).suffix.lower())
        meta = ImageMetadata(
            original_filename=filename,
            stored_filename=new_name,
            mime_type="application/octet-stream",
            file_size=len(content),
        )
        return new_name, content, meta


def _process_vector(filename: str, content: bytes) -> tuple[str, bytes, ImageMetadata]:
    """SVG files are kept as-is."""
    ext = Path(filename).suffix.lower()
    new_name = _generate_unique_name(filename, ext)
    meta = ImageMetadata(
        original_filename=filename,
        stored_filename=new_name,
        mime_type="image/svg+xml",
        file_size=len(content),
        is_vector=True,
    )
    return new_name, content, meta


def _process_animated(filename: str, content: bytes) -> tuple[str, bytes, ImageMetadata]:
    """GIF files are kept as-is to preserve animation."""
    new_name = _generate_unique_name(filename, ".gif")
    # Try to get dimensions
    width, height = None, None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
    except Exception:
        pass
    meta = ImageMetadata(
        original_filename=filename,
        stored_filename=new_name,
        mime_type="image/gif",
        width=width,
        height=height,
        file_size=len(content),
        is_animated=True,
    )
    return new_name, content, meta


def _process_raster(filename: str, content: bytes) -> tuple[str, bytes, ImageMetadata]:
    """Convert raster image to WebP with resizing."""
    from PIL import Image

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
