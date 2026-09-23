"""Note bundles: export notes as a zip, import notes from a JSON or zip file.

Everything that arrives here is untrusted. The rules, in the order they run:

1. Size first. The whole upload is capped before it is parsed; a zip is
   inspected entry by entry (count, per-entry size, total size, compression
   ratio, names) before a single byte is extracted.
2. Names are never used. Note folders, note ids, chapter ids and media
   filenames are all minted here; the archive's paths only say which image
   belongs to which note.
3. JSON only through the models. Note and Chapter are pydantic models with
   length limits; anything else is a 400.
4. Images are re-encoded through Pillow (raster -> webp) or verified as GIF,
   never written as received. SVG and unknown types are dropped and reported.
5. Text is scrubbed of control characters; a media block keeps only a
   reference that resolves inside the bundle or a plain http(s) URL.
6. Nothing is executed and nothing is extracted to a path: entries are read
   into memory one at a time within the caps and handed to the image
   pipeline.

Bundle layout (what export_zip writes and import_bundle reads):

    notes.json                 a NoteDocument; media blocks reference media/<note-name>/<file>
    media/<note-name>/<file>   the images of that note
"""

from __future__ import annotations

import io
import json
import logging
import re
import uuid
import zipfile
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from PIL import Image
from PIL import UnidentifiedImageError
from pydantic import ValidationError

from app.blocks import BLOCKS
from app.schemas import Chapter
from app.schemas import Note
from app.schemas import NoteCreate
from app.schemas import NoteDocument
from app.schemas import NoteUpdate
from app.services.image_processing import process_uploaded_image
from app.services.notes import NoteService

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # whole file, json or zip
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000
MAX_ENTRY_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100  # above this for a large entry, treat as a bomb
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
_MEDIA_ENTRY = re.compile(r"^(?:.*/)?media/([^/]+)/([^/]+)$")
_MEDIA_REF = re.compile(r"^media/([^/]+)/([^/]+)$")
_API_MEDIA_REF = re.compile(r"^/api/notes/([^/]+)/media/([^/]+)$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class BundleError(ValueError):
    """The file cannot be imported; the message is safe to show the user."""


@dataclass
class ImportResult:
    notes: list[Note] = field(default_factory=list)
    images: int = 0
    skipped: list[str] = field(default_factory=list)  # entry names dropped, with the reason


# ---------------------------------------------------------------- export


def export_zip(service: NoteService, note_ids: list[str] | None = None) -> bytes:
    """Zip of the chosen notes (all when None) with their images."""
    notes = service.list_notes()
    if note_ids is not None:
        wanted = set(note_ids)
        notes = [n for n in notes if n.id in wanted]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        out_notes = []
        for note in notes:
            chapters = []
            for ch in note.chapters:
                if ch.type == "media":
                    m = _API_MEDIA_REF.match(ch.content or "")
                    if m and m.group(1) == note.id:
                        ch = ch.model_copy(update={"content": f"media/{note.name}/{m.group(2)}"})
                chapters.append(ch)
            out_notes.append(note.model_copy(update={"chapters": chapters}))
            for filename in service.repo.list_media(note.name):
                path = service.repo.get_media_path(note.name, filename)
                if path:
                    zf.write(path, f"media/{note.name}/{filename}")
        doc = NoteDocument(version="1.0.0", exported_at=datetime.utcnow(), notes=out_notes)
        zf.writestr("notes.json", doc.model_dump_json(indent=2))
    return buf.getvalue()


# ---------------------------------------------------------------- import


def import_bundle(service: NoteService, filename: str, content: bytes) -> ImportResult:
    if not content:
        raise BundleError("Empty file")
    if len(content) > MAX_UPLOAD_BYTES:
        raise BundleError(f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
    if content[:4] == b"PK\x03\x04" or filename.lower().endswith(".zip"):
        return _import_zip(service, content)
    return _import_json(service, content)


def _import_json(service: NoteService, content: bytes) -> ImportResult:
    if len(content) > MAX_JSON_BYTES:
        raise BundleError("JSON too large")
    notes = _parse_notes(content)
    return _create_notes(service, notes, media={})


def _import_zip(service: NoteService, content: bytes) -> ImportResult:
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise BundleError("Not a valid zip file") from e
    with zf:
        json_entry, media_entries, skipped = _inspect_zip(zf)
        if zf.testzip() is not None:
            raise BundleError("Zip file is corrupt")
        notes = _parse_notes(zf.read(json_entry))
        media: dict[tuple[str, str], bytes] = {}
        for info, note_name, fname in media_entries:
            media[(note_name, fname)] = zf.read(info)  # size already bounded by _inspect_zip
    result = _create_notes(service, notes, media)
    result.skipped.extend(skipped)
    return result


def _inspect_zip(zf: zipfile.ZipFile):
    """Decide what will be read, from the central directory alone."""
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise BundleError(f"Too many entries in zip (max {MAX_ZIP_ENTRIES})")
    total = 0
    json_entry: str | None = None
    media_entries: list[tuple[zipfile.ZipInfo, str, str]] = []
    skipped: list[str] = []
    for info in infos:
        name = info.filename
        if info.is_dir():
            continue
        if not _safe_name(name):
            raise BundleError(f"Unsafe path in zip: {name!r}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise BundleError(f"Symlink in zip: {name!r}")
        if info.file_size > MAX_ENTRY_BYTES:
            raise BundleError(f"Entry too large: {name!r}")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise BundleError("Zip expands beyond the size limit")
        if (
            info.file_size > 1024 * 1024
            and info.compress_size
            and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise BundleError(f"Suspicious compression ratio: {name!r}")
        base = PurePosixPath(name).name
        if base == "notes.json" or (
            json_entry is None and base.endswith(".json") and "media/" not in name
        ):
            if json_entry is None or base == "notes.json":
                json_entry = name
            continue
        m = _MEDIA_ENTRY.match(name)
        if m and PurePosixPath(base).suffix.lower() in IMAGE_EXTENSIONS:
            media_entries.append((info, m.group(1), base))
        else:
            skipped.append(f"{name}: not notes.json or an image under media/")
    if json_entry is None:
        raise BundleError("Zip contains no notes.json")
    if zf.getinfo(json_entry).file_size > MAX_JSON_BYTES:
        raise BundleError("notes.json too large")
    return json_entry, media_entries, skipped


def _safe_name(name: str) -> bool:
    if not name or len(name) > 512 or "\\" in name or name.startswith("/") or _CONTROL.search(name):
        return False
    parts = PurePosixPath(name).parts
    return ".." not in parts and not (parts and ":" in parts[0])


def _parse_notes(raw: bytes) -> list[Note]:
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BundleError("Invalid JSON") from e
    try:
        if isinstance(data, dict) and "notes" in data:
            return NoteDocument.model_validate(data).notes
        if isinstance(data, dict):
            return [Note.model_validate(_with_defaults(data))]
        if isinstance(data, list):
            return [Note.model_validate(_with_defaults(d)) for d in data]
    except ValidationError as e:
        raise BundleError(
            f"Invalid note data: {e.errors()[0].get('msg', 'validation error')}"
        ) from e
    raise BundleError("JSON is not a note, a list of notes, or an export document")


def _with_defaults(d: Any) -> Any:
    """A hand-written single note may omit the bookkeeping fields; fill them so the model validates."""
    if not isinstance(d, dict):
        return d
    now = datetime.utcnow().isoformat()
    out = dict(d)
    out.setdefault("id", "imported")
    out.setdefault("name", "imported")
    out.setdefault("created_at", now)
    out.setdefault("updated_at", now)
    return out


def _clean_text(s: str | None, limit: int) -> str:
    return _CONTROL.sub("", s or "")[:limit]


def _create_notes(
    service: NoteService, notes: list[Note], media: dict[tuple[str, str], bytes]
) -> ImportResult:
    result = ImportResult()
    for src in notes:
        title = _clean_text(src.title, 200).strip() or "Imported note"
        created = service.create_note(
            NoteCreate(title=title, tags=[_clean_text(t, 50) for t in src.tags][:50])
        )
        id_map = {ch.id: str(uuid.uuid4()) for ch in src.chapters}
        media_urls: dict[str, str] = {}
        chapters: list[Chapter] = []
        for ch in sorted(src.chapters, key=lambda c: c.order):
            block_type = ch.type if ch.type in BLOCKS else "text"
            content = _clean_text(ch.content, 20_000)
            if block_type == "media":
                content = _import_media_ref(
                    service, created.id, src.name, content, media, media_urls, result
                )
            chapters.append(
                Chapter(
                    id=id_map[ch.id],
                    title=_clean_text(ch.title, 120),
                    content=content,
                    order=ch.order,
                    parent_id=id_map.get(ch.parent_id) if ch.parent_id else None,
                    type=block_type,
                    language=_clean_text(ch.language, 40) or None,
                    source=_clean_text(ch.source, 500) or None,
                )
            )
        note = service.update_note(
            created.id,
            NoteUpdate(folder=_clean_text(src.folder, 120) or None, chapters=chapters),
        )
        result.notes.append(note or created)
    return result


def _import_media_ref(service, note_id, src_name, content, media, media_urls, result) -> str:
    """Resolve a media block's reference to a stored image, importing it once."""
    if content in media_urls:
        return media_urls[content]
    m = _MEDIA_REF.match(content) or _API_MEDIA_REF.match(content)
    if m:
        key = (m.group(1), m.group(2)) if _MEDIA_REF.match(content) else (src_name, m.group(2))
        raw = media.get(key)
        if raw is None:
            result.skipped.append(f"{content}: image not in bundle")
            return ""
        url = _store_image(service, note_id, key[1], raw, result)
        media_urls[content] = url
        return url
    if content.startswith(("http://", "https://")):
        return content  # an external image the note already pointed at; served by its own host
    return ""


def _store_image(service, note_id, filename, raw, result) -> str:
    ext = PurePosixPath(filename).suffix.lower()
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.verify()  # cheap structural check before decoding
        if ext == ".gif":
            with Image.open(io.BytesIO(raw)) as img:
                if img.format != "GIF":
                    raise UnidentifiedImageError("not a GIF")
            new_name, data, meta = process_uploaded_image(
                filename, raw
            )  # kept verbatim, verified above
        else:
            new_name, data, meta = process_uploaded_image(filename, raw)  # re-encoded to webp
    except (UnidentifiedImageError, OSError, ValueError) as e:
        result.skipped.append(f"{filename}: not a readable image ({type(e).__name__})")
        return ""
    service.save_media_file(note_id, new_name, data)
    service.save_module_metadata(note_id, "media", new_name, meta.to_dict())
    result.images += 1
    return f"/api/notes/{note_id}/media/{new_name}"
