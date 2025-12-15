import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from filelock import FileLock

from app.schemas import Note, NoteDocument


class JsonNoteRepository:
    def __init__(self, data_path: Path) -> None:
        self._data_path = data_path
        self._lock = FileLock(str(data_path) + ".lock")
        self._data_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_raw(self) -> Dict[str, object]:
        if not self._data_path.exists():
            return {"version": "1.0.0", "exported_at": datetime.utcnow().isoformat(), "notes": []}
        with self._lock:
            with self._data_path.open("r", encoding="utf-8") as f:
                return json.load(f)

    def _persist(self, document: NoteDocument) -> None:
        with self._lock:
            with self._data_path.open("w", encoding="utf-8") as f:
                json.dump(json.loads(document.model_dump_json()), f, ensure_ascii=False, indent=2)

    def export_document(self) -> NoteDocument:
        raw = self._load_raw()
        return NoteDocument.model_validate(raw)

    def list_notes(self) -> List[Note]:
        return self.export_document().notes

    def get_note(self, note_id: str) -> Optional[Note]:
        for note in self.list_notes():
            if note.id == note_id:
                return note
        return None

    def upsert_note(self, note: Note) -> Note:
        doc = self.export_document()
        existing = {n.id: n for n in doc.notes}
        existing[note.id] = note
        doc.notes = sorted(existing.values(), key=lambda n: n.created_at)
        doc.exported_at = datetime.utcnow()
        self._persist(doc)
        return note

    def delete_note(self, note_id: str) -> None:
        doc = self.export_document()
        doc.notes = [n for n in doc.notes if n.id != note_id]
        doc.exported_at = datetime.utcnow()
        self._persist(doc)

    def import_document(self, document: NoteDocument) -> NoteDocument:
        document.exported_at = datetime.utcnow()
        self._persist(document)
        return document
