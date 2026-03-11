import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from filelock import FileLock

from app.schemas import Note, NoteDocument

logger = logging.getLogger(__name__)


class JsonNoteRepository:
    """
    Folder-based storage:
    - Each note is stored in data_dir/<name>/<name>.json
    - A directory-level lock is used for list/upsert/delete operations
    - On first run, if legacy notes.json exists, migrate notes into per-folder files
    - If prior slug-based storage (folder/note.json) is detected, upgrade to name-based
    """

    def __init__(self, legacy_data_path: Path) -> None:
        self._legacy_path = legacy_data_path
        self._root_dir = legacy_data_path.parent
        self._root_dir.mkdir(parents=True, exist_ok=True)
        # Single lock file for directory operations
        self._lock = FileLock(str(self._root_dir / ".notes.lock"))
        # Perform one-time migration from legacy monolith file
        self._maybe_migrate_from_legacy()

    def _note_dir(self, name: str) -> Path:
        return self._root_dir / name

    def _note_file(self, name: str) -> Path:
        return self._note_dir(name) / f"{name}.json"

    def _media_dir(self, name: str) -> Path:
        """Get media folder for a note.

        Uses the media block's ``data_folder`` declaration so the folder
        name is owned by the block, not hard-coded here.
        """
        from app.blocks import get_block
        media_block = get_block("media")
        return self._block_note_data_dir(name, media_block.name)

    def _ensure_media_dir(self, name: str) -> Path:
        """Lazily create media folder via the media block's data management."""
        from app.blocks import get_block
        media_block = get_block("media")
        return self.ensure_block_note_data_dir(name, media_block.name)

    def _block_note_data_dir(self, note_name: str, block_name: str) -> Path:
        """Return a block-owned per-note data directory without creating it."""
        from app.blocks import get_block

        block = get_block(block_name)
        if not block.data_folder:
            raise ValueError(f"Block '{block_name}' does not declare a data_folder")
        return block.get_note_data_dir(self._root_dir, note_name)

    def ensure_block_note_data_dir(self, note_name: str, block_name: str) -> Path:
        """Create and return a block-owned per-note data directory on demand."""
        from app.blocks import get_block

        block = get_block(block_name)
        if not block.data_folder:
            raise ValueError(f"Block '{block_name}' does not declare a data_folder")
        return block.ensure_note_data_dir(self._root_dir, note_name)

    def get_block_profile_dir(self, block_name: str) -> Path:
        """Return a block-owned hidden profile directory at the data root."""
        from app.blocks import get_block

        block = get_block(block_name)
        if not block.profile_folder:
            raise ValueError(f"Block '{block_name}' does not declare a profile_folder")
        return block.get_profile_dir(self._root_dir)

    def ensure_block_profile_dir(self, block_name: str) -> Path:
        """Create and return a block-owned hidden profile directory on demand."""
        from app.blocks import get_block

        block = get_block(block_name)
        if not block.profile_folder:
            raise ValueError(f"Block '{block_name}' does not declare a profile_folder")
        return block.ensure_profile_dir(self._root_dir)

    def _maybe_migrate_from_legacy(self) -> None:
        # If no legacy file, nothing to do
        if not self._legacy_path.exists():
            return
        try:
            with self._legacy_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            doc = NoteDocument.model_validate(raw)
        except Exception:
            # If invalid, skip migration
            return

        # Write each note to its own folder using name-based storage
        with self._lock:
            for note in doc.notes:
                base_name = getattr(note, "name", None) or self.derive_name(note.title)
                name = self.ensure_unique_name(base_name)
                # Update note object to include name
                note = note.model_copy(update={"name": name})
                ndir = self._note_dir(name)
                ndir.mkdir(parents=True, exist_ok=True)
                nfile = self._note_file(name)
                with nfile.open("w", encoding="utf-8") as nf:
                    json.dump(json.loads(note.model_dump_json()), nf, ensure_ascii=False, indent=2)
        # Upgrade any existing slug-based storage to name-based
        self._upgrade_slug_storage()

    def _upgrade_slug_storage(self) -> None:
        with self._lock:
            for entry in sorted(self._root_dir.iterdir()):
                if not entry.is_dir():
                    continue
                legacy_file = entry / "note.json"
                if not legacy_file.exists():
                    continue
                try:
                    with legacy_file.open("r", encoding="utf-8") as f:
                        raw = json.load(f)
                except Exception:
                    continue

                # Determine target name from title or slug
                title = raw.get("title") or "Untitled"
                base_name = raw.get("name") or self.derive_name(title)
                name = self.ensure_unique_name(base_name)

                # Write new format file
                target_dir = self._note_dir(name)
                if not target_dir.exists():
                    target_dir.mkdir(parents=True, exist_ok=True)
                target_file = self._note_file(name)
                # Update payload to include name
                raw["name"] = name
                raw["title"] = self.name_to_title(name)
                try:
                    with target_file.open("w", encoding="utf-8") as f:
                        json.dump(raw, f, ensure_ascii=False, indent=2)
                    # Remove legacy file and directory if different
                    try:
                        legacy_file.unlink()
                        if entry != target_dir:
                            # Attempt to remove the old folder if empty
                            entry.rmdir()
                    except Exception:
                        pass
                except Exception:
                    # If write fails, leave legacy as-is
                    pass

        # Optionally keep a backup; do not delete legacy file
        # The repository will ignore it going forward.

    def list_notes(self) -> List[Note]:
        notes: List[Note] = []
        with self._lock:
            for entry in sorted(self._root_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue

                # Prefer <name>.json matching folder name, else any *.json
                nfile = entry / f"{entry.name}.json"
                if not nfile.exists():
                    json_files = list(entry.glob("*.json"))
                    nfile = json_files[0] if json_files else None
                if not nfile or not nfile.exists():
                    continue

                try:
                    with nfile.open("r", encoding="utf-8") as f:
                        raw = json.load(f)

                    if "name" not in raw and "slug" in raw:
                        raw["name"] = raw["slug"]
                    if raw.get("name"):
                        raw["title"] = self.name_to_title(raw["name"])

                    notes.append(Note.model_validate(raw))

                except (json.JSONDecodeError, Exception) as e:
                    logger.error("Failed to read note from %s: %s", nfile, e)
                    continue

        notes.sort(key=lambda n: n.created_at)
        return notes

    def get_note(self, note_id: str) -> Optional[Note]:
        for note in self.list_notes():
            if note.id == note_id:
                return note
        return None

    def upsert_note(self, note: Note, old_name: Optional[str] = None) -> Note:
        """Create or update a note file; optionally rename its folder/file if name changed."""
        with self._lock:
            # Rename folder if needed
            if old_name and old_name != note.name:
                old_dir = self._note_dir(old_name)
                new_dir = self._note_dir(note.name)
                # Attempt to preserve any existing payload from the old note file
                existing_payload_from_old: dict[str, Any] = {}
                try:
                    old_file = old_dir / f"{old_name}.json"
                    if old_file.exists():
                        with old_file.open("r", encoding="utf-8") as f:
                            existing_payload_from_old = json.load(f)
                except Exception:
                    existing_payload_from_old = {}

                if old_dir.exists():
                    if not new_dir.exists():
                        # Move the whole folder atomically
                        old_dir.rename(new_dir)
                        # If the moved folder still contains the JSON named with the old name,
                        # rename it to match the new note name so we don't create duplicate files.
                        moved_old_file = new_dir / f"{old_name}.json"
                        moved_new_file = new_dir / f"{note.name}.json"
                        try:
                            if moved_old_file.exists() and not moved_new_file.exists():
                                moved_old_file.replace(moved_new_file)
                        except Exception:
                            # Best-effort; if this fails, we'll still write the new file below.
                            pass
                    else:
                        # Target exists: attempt to merge media/meta if possible by no-op here.
                        # We avoid deleting the old folder automatically to be conservative.
                        pass

            ndir = self._note_dir(note.name)
            ndir.mkdir(parents=True, exist_ok=True)
            nfile = self._note_file(note.name)

            try:
                note_data = json.loads(note.model_dump_json())

                # Preserve module/media metadata stored outside the Note model
                existing_payload: dict[str, Any] = {}
                if nfile.exists():
                    try:
                        with nfile.open("r", encoding="utf-8") as ef:
                            existing_payload = json.load(ef)
                    except Exception:
                        existing_payload = {}
                elif 'existing_payload_from_old' in locals() and existing_payload_from_old:
                    existing_payload = existing_payload_from_old

                for key in ("_module_meta", "_media_meta"):
                    if key in existing_payload and key not in note_data:
                        note_data[key] = existing_payload[key]
                
                chapter_ids = [ch["id"] for ch in note_data.get("chapters", [])]
                if len(chapter_ids) != len(set(chapter_ids)):
                    raise ValueError(f"Duplicate chapter IDs detected in note {note.id}")

                temp_file = nfile.with_suffix(".tmp")
                with temp_file.open("w", encoding="utf-8") as f:
                    json.dump(note_data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                temp_file.replace(nfile)

            except Exception:
                logger.error("Failed to write note %s", note.id, exc_info=True)
                raise
        return note

    def delete_note(self, note_id: str) -> None:
        with self._lock:
            target: Optional[Path] = None
            for note in self.list_notes():
                if note.id == note_id:
                    target = self._note_dir(note.name)
                    break
            if target and target.exists():
                try:
                    shutil.rmtree(target)
                except Exception:
                    pass

    def export_document(self) -> NoteDocument:
        return NoteDocument(version="1.0.0", exported_at=datetime.utcnow(), notes=self.list_notes())

    def import_document(self, document: NoteDocument) -> NoteDocument:
        # Import each note; ensure name uniqueness
        with self._lock:
            for note in document.notes:
                base_name = getattr(note, "name", None) or self.derive_name(note.title)
                name = self.ensure_unique_name(base_name)
                note = note.model_copy(update={"name": name, "title": self.name_to_title(name), "updated_at": datetime.utcnow()})
                ndir = self._note_dir(name)
                ndir.mkdir(parents=True, exist_ok=True)
                with (self._note_file(name)).open("w", encoding="utf-8") as f:
                    json.dump(json.loads(note.model_dump_json()), f, ensure_ascii=False, indent=2)
        document.exported_at = datetime.utcnow()
        return document

    @staticmethod
    def derive_name(title: str) -> str:
        # Sanitize: keep letters, numbers, dashes, underscores; spaces -> '-'; drop specials; collapse dashes
        out = []
        prev_dash = False
        for ch in title.strip():
            if ch.isalnum() or ch in ['-', '_']:
                out.append(ch)
                prev_dash = False
            elif ch.isspace():
                if not prev_dash:
                    out.append('-')
                    prev_dash = True
            else:
                # drop special chars; treat as dash separator
                if not prev_dash:
                    out.append('-')
                    prev_dash = True
        # Collapse multiple dashes and trim
        name = ''.join(out)
        while '--' in name:
            name = name.replace('--', '-')
        name = name.strip('-')
        return name or 'Untitled-note'

    def ensure_unique_name(self, base_name: str) -> str:
        name = base_name
        i = 2
        while self._note_dir(name).exists() or self._note_file(name).exists():
            name = f"{base_name}-{i}"
            i += 1
        return name

    @staticmethod
    def name_to_title(name: str) -> str:
        # Convert dashes to single spaces and trim
        title = name.replace('-', ' ')
        # Collapse multiple spaces
        title = ' '.join(title.split())
        return title

    def save_media(self, note_name: str, filename: str, content: bytes) -> str:
        """Save media file to note's media folder. Returns relative path."""
        media_dir = self._ensure_media_dir(note_name)
        # Sanitize filename to prevent path traversal
        filename = Path(filename).name
        filepath = media_dir / filename
        with open(filepath, "wb") as f:
            f.write(content)
        # Return relative path for storage in chapter content
        return f"media/{filename}"

    def list_media(self, note_name: str) -> List[str]:
        """List all media filenames in a note's media folder."""
        media_dir = self._media_dir(note_name)
        if not media_dir.exists():
            return []
        return [f.name for f in sorted(media_dir.iterdir()) if f.is_file()]

    def delete_media(self, note_name: str, filename: str) -> bool:
        """Delete a media file. Returns True if deleted, False if not found."""
        # Sanitize filename
        filename = Path(filename).name
        filepath = self._media_dir(note_name) / filename
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def get_media_path(self, note_name: str, filename: str) -> Optional[Path]:
        """Get full path to a media file if it exists."""
        # Sanitize filename
        filename = Path(filename).name
        filepath = self._media_dir(note_name) / filename
        if filepath.exists():
            return filepath
        return None

    def upsert_module_metadata(self, note_name: str, module_name: str, key: str, payload: dict[str, Any]) -> None:
        """Persist module metadata in a note JSON under ``_module_meta``."""
        with self._lock:
            nfile = self._note_file(note_name)
            if not nfile.exists():
                return

            with nfile.open("r", encoding="utf-8") as f:
                raw = json.load(f)

            raw.setdefault("_module_meta", {})
            raw["_module_meta"].setdefault(module_name, {})
            raw["_module_meta"][module_name][key] = payload

            temp_file = nfile.with_suffix(".tmp")
            with temp_file.open("w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            temp_file.replace(nfile)

    def get_module_metadata(self, note_name: str, module_name: str) -> dict[str, Any]:
        """Read module metadata map for a note (empty if missing)."""
        nfile = self._note_file(note_name)
        if not nfile.exists():
            return {}

        try:
            with nfile.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            module_meta = raw.get("_module_meta", {})
            if not isinstance(module_meta, dict):
                return {}
            scoped = module_meta.get(module_name, {})
            return scoped if isinstance(scoped, dict) else {}
        except Exception:
            return {}

