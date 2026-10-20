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
4. Images go through the upload pipeline, which decides by content: raster is
   re-encoded to webp, GIF is verified and kept, SVG and anything Pillow cannot
   open are dropped and reported. Nothing is written as received except a
   verified GIF.
5. Text is scrubbed of control characters; a media block keeps only a
   reference that resolves inside the bundle or a plain http(s) URL.
6. Nothing is executed and nothing is extracted to a path: entries are read
   into memory one at a time within the caps and handed to the image
   pipeline.

Bundle layout (what export_zip writes and import_bundle reads):

    notes.json                 a NoteDocument; media blocks reference media/<note-name>/<file>
    media/<note-name>/<file>   the images of that note

import_bundle also reads a note folder zipped straight from the data directory:

    <note-name>/<note-name>.json   one note; media blocks reference /api/notes/<id>/media/<file>
    <note-name>/media/<file>       its images

Entries under __MACOSX/ and dot-files (.DS_Store, ._* AppleDouble forks), which
macOS Finder adds to every zip, are dropped before anything reads them.

A media block whose image cannot be stored (not in the bundle, or not a
readable image) keeps a visible placeholder, MISSING_PREFIX + the file name,
rather than becoming an empty block. The note page lists every such block.
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

from pydantic import ValidationError

from app.blocks import BLOCKS
from app.schemas import Chapter
from app.schemas import Note
from app.schemas import NoteCreate
from app.schemas import NoteDocument
from app.schemas import NoteUpdate
from app.services.image_processing import UnsupportedImage
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
# data-dir layout: group 1 is the note folder's whole path in the zip, so x/Alpha/ and
# y/Alpha/ keep their own images (20261020-045)
_FOLDER_MEDIA_ENTRY = re.compile(r"^((?:.*/)?[^/]+)/media/([^/]+)$")
_MEDIA_REF = re.compile(r"^media/([^/]+)/([^/]+)$")
_API_MEDIA_REF = re.compile(r"^/api/notes/([^/]+)/media/([^/]+)$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MISSING_PREFIX = "missing:"  # media block content for an image the import could not store


class BundleError(ValueError):
    """The file cannot be imported; the message is safe to show the user."""


@dataclass
class ImportResult:
    notes: list[Note] = field(default_factory=list)
    images: int = 0
    skipped: list[str] = field(default_factory=list)  # entry names dropped, with the reason
    missing: list[str] = field(
        default_factory=list
    )  # images media blocks referenced and did not get
    ignored: int = 0  # __MACOSX/ and dot-file entries, dropped unread


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
    return _create_notes(service, [(n, n.name) for n in notes], media={})


def _import_zip(service: NoteService, content: bytes) -> ImportResult:
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise BundleError("Not a valid zip file") from e
    with zf:
        json_entries, media_entries, skipped, ignored = _inspect_zip(zf)
        if zf.testzip() is not None:
            raise BundleError("Zip file is corrupt")
        notes = _notes_in_zip(zf, json_entries)
        media: dict[tuple[str, str], bytes] = {}
        for info, scope, fname in media_entries:
            media[(scope, fname)] = zf.read(info)  # size already bounded by _inspect_zip
    result = _create_notes(service, notes, media)
    result.skipped.extend(skipped)
    result.ignored = ignored
    return result


def _inspect_zip(zf: zipfile.ZipFile):
    """Decide what will be read, from the central directory alone.

    Every .json outside media/ is a candidate; _notes_in_zip decides by content
    whether each is an export or one note.
    """
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise BundleError(f"Too many entries in zip (max {MAX_ZIP_ENTRIES})")
    total = 0
    json_entries: list[str] = []
    media_entries: list[tuple[zipfile.ZipInfo, str, str]] = []
    skipped: list[str] = []
    ignored = 0
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
        if _is_os_junk(name):
            ignored += 1
            continue
        if base.endswith(".json") and "media/" not in name:
            json_entries.append(name)
            continue
        m = _MEDIA_ENTRY.match(name) or _FOLDER_MEDIA_ENTRY.match(name)
        if m and PurePosixPath(base).suffix.lower() in IMAGE_EXTENSIONS:
            media_entries.append((info, m.group(1), base))
        else:
            skipped.append(f"{name}: not notes.json or an image under media/")
    if not json_entries:
        raise BundleError("Zip contains no notes.json")
    if sum(zf.getinfo(e).file_size for e in json_entries) > MAX_JSON_BYTES:
        raise BundleError("Note .json files too large together")
    return sorted(json_entries), media_entries, skipped, ignored


def _notes_in_zip(zf: zipfile.ZipFile, entries: list[str]) -> list[tuple[Note, str]]:
    """Each note with the scope its images are keyed by.

    An export (a document with a "notes" list, whatever its file is called)
    lists every note, and its images are media/<note name>/<file>. A note
    folder holds one note, and its images are <folder path>/media/<file>.
    Deciding by content, not by the name notes.json, lets a note titled
    "notes" (stored as notes/notes.json) import as the note it is. One export,
    or note folders: a zip with both, or two exports, is ambiguous and refused,
    never half-read. Note folders are imported in path order.
    """
    exports: list[tuple[str, bytes]] = []
    folders: list[tuple[str, bytes]] = []
    for entry in entries:
        raw = zf.read(entry)
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise BundleError(f"Invalid JSON in {entry}") from e
        is_export = isinstance(data, dict) and "notes" in data
        (exports if is_export else folders).append((entry, raw))
    if len(exports) > 1:
        names = ", ".join(e for e, _ in exports)
        raise BundleError(f"Zip contains more than one export: {names}")
    if exports and folders:
        others = ", ".join(e for e, _ in folders[:3]) + (" ..." if len(folders) > 3 else "")
        raise BundleError(
            f"Zip contains the export {exports[0][0]} and also {others}; "
            "import an export or note folders, not both"
        )
    if exports:
        return [(n, n.name) for n in _parse_notes(exports[0][1])]
    out = []
    for entry, raw in folders:
        folder = str(PurePosixPath(entry).parent)
        out += [(n, n.name if folder == "." else folder) for n in _parse_notes(raw)]
    return out


def _is_os_junk(name: str) -> bool:
    """macOS Finder metadata: anything under __MACOSX/, and dot-files (.DS_Store, ._<file>)."""
    parts = PurePosixPath(name).parts
    return "__MACOSX" in parts or any(p.startswith(".") for p in parts)


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
    service: NoteService, notes: list[tuple[Note, str]], media: dict[tuple[str, str], bytes]
) -> ImportResult:
    """All or nothing: if anything raises part-way, the notes created so far are deleted.

    Each note comes with the scope its /api/notes/<id>/media/<file> references
    resolve in: its name for an export, its folder's path for a note folder."""
    result = ImportResult()
    created_ids: list[str] = []
    try:
        for src, scope in notes:
            _create_note(service, src, scope, media, result, created_ids)
    except BaseException:
        for note_id in created_ids:
            try:
                service.delete_note(note_id)
            except Exception:
                logger.exception("import rollback could not delete note %s", note_id)
        raise
    return result


def _create_note(
    service, src: Note, scope: str, media, result: ImportResult, created_ids: list[str]
) -> None:
    title = _clean_text(src.title, 200).strip() or "Imported note"
    created = service.create_note(
        NoteCreate(title=title, tags=[_clean_text(t, 50) for t in src.tags][:50])
    )
    created_ids.append(created.id)
    id_map = {ch.id: str(uuid.uuid4()) for ch in src.chapters}
    media_urls: dict[str, str] = {}
    chapters: list[Chapter] = []
    for ch in sorted(src.chapters, key=lambda c: c.order):
        block_type = ch.type if ch.type in BLOCKS else "text"
        content = _clean_text(ch.content, 20_000)
        if block_type == "media":
            content = _import_media_ref(
                service, created.id, scope, content, media, media_urls, result
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


def _import_media_ref(service, note_id, scope, content, media, media_urls, result) -> str:
    """Resolve a media block's reference to a stored image, importing it once."""
    if content in media_urls:
        return media_urls[content]
    if content.startswith(MISSING_PREFIX):
        return content  # already a placeholder (a re-import of an export); keep it visible
    m = _MEDIA_REF.match(content) or _API_MEDIA_REF.match(content)
    if m:
        key = (m.group(1), m.group(2)) if _MEDIA_REF.match(content) else (scope, m.group(2))
        raw = media.get(key)
        if raw is None:
            result.skipped.append(f"{content}: image not in bundle")
            url = _missing(key[1], result)
        else:
            url = _store_image(service, note_id, key[1], raw, result)
        media_urls[content] = url
        return url
    if content.startswith(("http://", "https://")):
        return content  # an external image the note already pointed at; served by its own host
    return ""


def _store_image(service, note_id, filename, raw, result) -> str:
    try:
        new_name, data, meta = process_uploaded_image(
            filename, raw
        )  # content-based; refuses SVG/unknown
    except UnsupportedImage as e:
        result.skipped.append(f"{filename}: {e}")
        return _missing(filename, result)
    service.save_media_file(note_id, new_name, data)
    service.save_module_metadata(note_id, "media", new_name, meta.to_dict())
    result.images += 1
    return f"/api/notes/{note_id}/media/{new_name}"


def _missing(filename: str, result: ImportResult) -> str:
    result.missing.append(filename)
    return MISSING_PREFIX + filename
