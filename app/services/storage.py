import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from filelock import FileLock

from app.schemas import Note, NoteDocument


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
                base_name = getattr(note, "name", None) or self._derive_name(note.title)
                name = self._ensure_unique_name(base_name)
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
                base_name = raw.get("name") or self._derive_name(title)
                name = self._ensure_unique_name(base_name)

                # Write new format file
                target_dir = self._note_dir(name)
                if not target_dir.exists():
                    target_dir.mkdir(parents=True, exist_ok=True)
                target_file = self._note_file(name)
                # Update payload to include name
                raw["name"] = name
                raw["title"] = self._name_to_title(name)
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
                if not entry.is_dir():
                    continue
                # Look for <name>.json inside folder named <name>
                nfile = None
                try:
                    # Prefer file matching folder name
                    candidate = entry / f"{entry.name}.json"
                    nfile = candidate if candidate.exists() else None
                    if nfile is None:
                        # Fallback: any single *.json
                        json_files = list(entry.glob("*.json"))
                        if json_files:
                            nfile = json_files[0]
                except Exception:
                    nfile = None
                if not nfile.exists():
                    continue
                try:
                    with nfile.open("r", encoding="utf-8") as f:
                        raw = json.load(f)
                    # Backward compatibility: map slug->name if needed
                    if "name" not in raw and "slug" in raw:
                        raw["name"] = raw["slug"]
                    # Ensure title is the display form (spaces)
                    if raw.get("name"):
                        raw["title"] = self._name_to_title(raw["name"])  # type: ignore[arg-type]
                    note = Note.model_validate(raw)
                    notes.append(note)
                except Exception:
                    continue
        # Sort by created_at ascending
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
                if old_dir.exists():
                    if not new_dir.exists():
                        old_dir.rename(new_dir)
                    else:
                        # If target exists, fallback to writing into new_dir
                        pass

            # Ensure directory exists
            ndir = self._note_dir(note.name)
            ndir.mkdir(parents=True, exist_ok=True)
            nfile = self._note_file(note.name)
            with nfile.open("w", encoding="utf-8") as f:
                json.dump(json.loads(note.model_dump_json()), f, ensure_ascii=False, indent=2)
        return note

    def delete_note(self, note_id: str) -> None:
        with self._lock:
            target: Optional[Path] = None
            for note in self.list_notes():
                if note.id == note_id:
                    target = self._note_dir(note.name)
                    break
            if target and target.exists():
                # Remove note.json and folder
                try:
                    nfile = target / f"{target.name}.json"
                    if nfile.exists():
                        nfile.unlink()
                    # Remove folder (should be empty)
                    target.rmdir()
                except Exception:
                    # Best-effort delete: ignore failures
                    pass

    def export_document(self) -> NoteDocument:
        return NoteDocument(version="1.0.0", exported_at=datetime.utcnow(), notes=self.list_notes())

    def import_document(self, document: NoteDocument) -> NoteDocument:
        # Import each note; ensure name uniqueness
        with self._lock:
            for note in document.notes:
                base_name = getattr(note, "name", None) or self._derive_name(note.title)
                name = self._ensure_unique_name(base_name)
                note = note.model_copy(update={"name": name, "title": self._name_to_title(name), "updated_at": datetime.utcnow()})
                ndir = self._note_dir(name)
                ndir.mkdir(parents=True, exist_ok=True)
                with (self._note_file(name)).open("w", encoding="utf-8") as f:
                    json.dump(json.loads(note.model_dump_json()), f, ensure_ascii=False, indent=2)
        document.exported_at = datetime.utcnow()
        return document

    # --- helpers for slug management ---
    @staticmethod
    def _derive_name(title: str) -> str:
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

    def _ensure_unique_name(self, base_name: str) -> str:
        name = base_name
        i = 2
        while self._note_dir(name).exists() or self._note_file(name).exists():
            name = f"{base_name}-{i}"
            i += 1
        return name

    @staticmethod
    def _name_to_title(name: str) -> str:
        # Convert dashes to single spaces and trim
        title = name.replace('-', ' ')
        # Collapse multiple spaces
        title = ' '.join(title.split())
        return title
