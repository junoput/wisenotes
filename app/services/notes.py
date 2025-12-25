from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from app.plugins.registry import PluginRegistry
from app.schemas import Chapter, Note, NoteCreate, NoteDocument, NoteUpdate
from app.services.storage import JsonNoteRepository


class NoteService:
    def __init__(self, repo: JsonNoteRepository, plugins: PluginRegistry) -> None:
        self.repo = repo
        self.plugins = plugins

    def list_notes(self) -> List[Note]:
        return self.repo.list_notes()

    def get_note(self, note_id: str) -> Optional[Note]:
        return self.repo.get_note(note_id)

    def create_note(self, payload: NoteCreate) -> Note:
        now = datetime.utcnow()
        # Derive a unique name from title
        base_name = self.repo._derive_name(payload.title)  # type: ignore[attr-defined]
        unique_name = self.repo._ensure_unique_name(base_name)  # type: ignore[attr-defined]
        note = Note(
            id=str(uuid4()),
            name=unique_name,
            title=self.repo._name_to_title(unique_name),  # type: ignore[attr-defined]
            tags=payload.tags,
            created_at=now,
            updated_at=now,
            chapters=payload.chapters,
        )
        saved = self.repo.upsert_note(note)
        self.plugins.notify_note_saved(saved)
        return saved

    def update_note(self, note_id: str, payload: NoteUpdate) -> Optional[Note]:
        existing = self.repo.get_note(note_id)
        if not existing:
            return None
        # Compute new name if title changes
        new_title_input = payload.title or existing.title
        base_name = self.repo._derive_name(new_title_input)  # type: ignore[attr-defined]
        # If title unchanged, keep existing name; otherwise ensure uniqueness
        if new_title_input == existing.title:
            new_name = existing.name
        else:
            new_name = self.repo._ensure_unique_name(base_name)  # type: ignore[attr-defined]
        updated = existing.model_copy(update={
            "name": new_name,
            "title": self.repo._name_to_title(new_name),  # type: ignore[attr-defined]
            "tags": payload.tags if payload.tags is not None else existing.tags,
            "chapters": payload.chapters if payload.chapters is not None else existing.chapters,
            "updated_at": datetime.utcnow(),
        })
        # Pass old name to allow repo to rename folder/file if needed
        saved = self.repo.upsert_note(updated, old_name=existing.name)
        self.plugins.notify_note_saved(saved)
        return saved

    def delete_note(self, note_id: str) -> bool:
        if not self.repo.get_note(note_id):
            return False
        self.repo.delete_note(note_id)
        return True

    def delete_chapter(self, note_id: str, chapter_id: str) -> Optional[Note]:
        """Delete a chapter (and its descendants) from a note."""
        note = self.repo.get_note(note_id)
        if not note:
            return None

        if not any(ch.id == chapter_id for ch in note.chapters):
            return note

        to_delete = self._collect_descendant_ids(note.chapters, chapter_id)
        to_delete.add(chapter_id)
        updated_chapters = [ch for ch in note.chapters if ch.id not in to_delete]
        updated = note.model_copy(update={
            "chapters": updated_chapters,
            "updated_at": datetime.utcnow(),
        })
        saved = self.repo.upsert_note(updated)
        self.plugins.notify_note_saved(saved)
        return saved

    @staticmethod
    def _collect_descendant_ids(chapters: List[Chapter], parent_id: str) -> set[str]:
        children = [c for c in chapters if c.parent_id == parent_id]
        ids: set[str] = set()
        for child in children:
            ids.add(child.id)
            ids.update(NoteService._collect_descendant_ids(chapters, child.id))
        return ids

    @staticmethod
    def _new_chapter_id(existing_ids: set[str]) -> str:
        while True:
            cid = str(uuid4())
            if cid not in existing_ids:
                return cid

    @staticmethod
    def _normalize_sibling_orders(chapters: List[Chapter], parent_id: Optional[str]) -> List[Chapter]:
        siblings = [c for c in chapters if c.parent_id == parent_id]
        others = [c for c in chapters if c.parent_id != parent_id]
        normalized_siblings = [
            ch.model_copy(update={"order": idx})
            for idx, ch in enumerate(sorted(siblings, key=lambda c: (c.order, c.id)))
        ]
        return others + normalized_siblings

    def add_chapter(self, note_id: str, title: Optional[str] = None, parent_id: Optional[str] = None, block_type: str = "chapter") -> Optional[Note]:
        note = self.repo.get_note(note_id)
        if not note:
            return None
        
        # Enforce rule: only chapters allowed at root level
        if parent_id is None and block_type != "chapter":
            return None
        
        # Enforce rule: parent must be a chapter to have children
        if parent_id is not None:
            parent = next((c for c in note.chapters if c.id == parent_id), None)
            if not parent or parent.type != "chapter":
                return None
        
        # Get the next order among siblings (chapters with the same parent)
        siblings = [c for c in note.chapters if c.parent_id == parent_id]
        next_sibling_order = max((c.order for c in siblings), default=-1) + 1
        
        existing_ids = {c.id for c in note.chapters}
        new_id = self._new_chapter_id(existing_ids)
        
        # Set default title and language based on block type
        if title is None:
            # Root chapters get a default title; nested chapters can be empty
            title = "New chapter" if (block_type == "chapter" and parent_id is None) else ""
        
        language = None
        if block_type == "code":
            language = "python"
        elif block_type == "math":
            language = "latex"
        
        now = datetime.utcnow()
        new_chapter = Chapter(
            id=new_id,
            title=title,
            content="",
            order=next_sibling_order,
            parent_id=parent_id,
            type=block_type,
            language=language,
        )
        updated = note.model_copy(update={
            "chapters": self._normalize_sibling_orders(note.chapters + [new_chapter], parent_id),
            "updated_at": now,
        })
        saved = self.repo.upsert_note(updated)
        self.plugins.notify_note_saved(saved)
        return saved

    def add_chapter_after(self, note_id: str, prev_id: str, title: Optional[str] = None, block_type: str = "chapter") -> Optional[Note]:
        note = self.repo.get_note(note_id)
        if not note:
            return None
        prev = next((c for c in note.chapters if c.id == prev_id), None)
        if not prev:
            return None
        parent_id = prev.parent_id
        
        # Enforce rule: only chapters allowed at root level
        if parent_id is None and block_type != "chapter":
            return None
        
        # Enforce rule: parent must be a chapter to have children
        if parent_id is not None:
            parent = next((c for c in note.chapters if c.id == parent_id), None)
            if not parent or parent.type != "chapter":
                return None
        
        insert_index = prev.order + 1

        shifted: List[Chapter] = []
        for ch in note.chapters:
            if ch.parent_id == parent_id and ch.order >= insert_index:
                shifted.append(ch.model_copy(update={"order": ch.order + 1}))
            else:
                shifted.append(ch)

        existing_ids = {c.id for c in note.chapters}
        new_id = self._new_chapter_id(existing_ids)
        
        # Set default title and language based on block type
        if title is None:
            # Root chapters get a default title; nested chapters can be empty
            title = "New chapter" if (block_type == "chapter" and parent_id is None) else ""
        
        language = None
        if block_type == "code":
            language = "python"
        elif block_type == "math":
            language = "latex"
        
        new_chapter = Chapter(
            id=new_id,
            title=title,
            content="",
            order=insert_index,
            parent_id=parent_id,
            type=block_type,
            language=language,
        )

        updated_chapters = self._normalize_sibling_orders(shifted + [new_chapter], parent_id)
        updated = note.model_copy(update={"chapters": updated_chapters, "updated_at": datetime.utcnow()})
        saved = self.repo.upsert_note(updated)
        self.plugins.notify_note_saved(saved)
        return saved

    def move_chapter(self, note_id: str, chapter_id: str, parent_id: Optional[str] = None) -> Optional[Note]:
        note = self.repo.get_note(note_id)
        if not note:
            return None
        # Find and update the chapter's parent_id
        updated_chapters = []
        for ch in note.chapters:
            if ch.id == chapter_id:
                updated_chapters.append(ch.model_copy(update={"parent_id": parent_id}))
            else:
                updated_chapters.append(ch)
        updated = note.model_copy(update={
            "chapters": updated_chapters,
            "updated_at": datetime.utcnow(),
        })
        saved = self.repo.upsert_note(updated)
        self.plugins.notify_note_saved(saved)
        return saved

    def update_chapter(self, note_id: str, chapter_id: str, title: str, content: str, language: Optional[str] = None, source: Optional[str] = None) -> Optional[Note]:
        note = self.repo.get_note(note_id)
        if not note:
            return None
        # Find and update the chapter
        updated_chapters = []
        for ch in note.chapters:
            if ch.id == chapter_id:
                updated_chapters.append(
                    ch.model_copy(
                        update={
                            "title": title,
                            "content": content,
                            "language": language if language is not None else ch.language,
                            "source": source if source is not None else ch.source,
                        }
                    )
                )
            else:
                updated_chapters.append(ch)
        updated = note.model_copy(update={
            "chapters": updated_chapters,
            "updated_at": datetime.utcnow(),
        })
        saved = self.repo.upsert_note(updated)
        self.plugins.notify_note_saved(saved)
        return saved

    def add_chapter_before(self, note_id: str, next_id: str, title: Optional[str] = None, block_type: str = "chapter") -> Optional[Note]:
        note = self.repo.get_note(note_id)
        if not note:
            return None
        nxt = next((c for c in note.chapters if c.id == next_id), None)
        if not nxt:
            return None
        parent_id = nxt.parent_id
        
        # Enforce rule: only chapters allowed at root level
        if parent_id is None and block_type != "chapter":
            return None
        
        # Enforce rule: parent must be a chapter to have children
        if parent_id is not None:
            parent = next((c for c in note.chapters if c.id == parent_id), None)
            if not parent or parent.type != "chapter":
                return None
        
        insert_index = nxt.order

        shifted: List[Chapter] = []
        for ch in note.chapters:
            if ch.parent_id == parent_id and ch.order >= insert_index:
                shifted.append(ch.model_copy(update={"order": ch.order + 1}))
            else:
                shifted.append(ch)

        existing_ids = {c.id for c in note.chapters}
        new_id = self._new_chapter_id(existing_ids)
        
        # Set default title and language based on block type
        if title is None:
            # Root chapters get a default title; nested chapters can be empty
            title = "New chapter" if (block_type == "chapter" and parent_id is None) else ""
        
        language = None
        if block_type == "code":
            language = "python"
        elif block_type == "math":
            language = "latex"
        
        new_chapter = Chapter(
            id=new_id,
            title=title,
            content="",
            order=insert_index,
            parent_id=parent_id,
            type=block_type,
            language=language,
        )

        updated_chapters = self._normalize_sibling_orders(shifted + [new_chapter], parent_id)
        updated = note.model_copy(update={"chapters": updated_chapters, "updated_at": datetime.utcnow()})
        saved = self.repo.upsert_note(updated)
        self.plugins.notify_note_saved(saved)
        return saved

    def add_chapter_child(self, note_id: str, parent_id: str, title: Optional[str] = None, block_type: str = "chapter") -> Optional[Note]:
        note = self.repo.get_note(note_id)
        if not note:
            return None
        
        # Enforce rule: parent must exist and be a chapter type
        parent = next((c for c in note.chapters if c.id == parent_id), None)
        if not parent or parent.type != "chapter":
            return None
        
        # Get the next order among siblings (children of the same parent)
        siblings = [c for c in note.chapters if c.parent_id == parent_id]
        next_sibling_order = max((c.order for c in siblings), default=-1) + 1
        
        existing_ids = {c.id for c in note.chapters}
        new_id = self._new_chapter_id(existing_ids)
        if new_id == parent_id:
            new_id = self._new_chapter_id(existing_ids | {parent_id})
        
        # Set default title and language based on block type
        if title is None:
            # For child chapters, allow empty title
            title = "New chapter" if block_type == "chapter" else ""
        
        language = None
        if block_type == "code":
            language = "python"
        elif block_type == "math":
            language = "latex"
        
        new_chapter = Chapter(
            id=new_id,
            title=title,
            content="",
            order=next_sibling_order,
            parent_id=parent_id,
            type=block_type,
            language=language,
        )
        updated = note.model_copy(update={
            "chapters": self._normalize_sibling_orders(note.chapters + [new_chapter], parent_id),
            "updated_at": datetime.utcnow(),
        })
        saved = self.repo.upsert_note(updated)
        self.plugins.notify_note_saved(saved)
        return saved

    def export_document(self) -> NoteDocument:
        doc = self.repo.export_document()
        self.plugins.notify_export(doc)
        return doc

    def import_document(self, doc: NoteDocument) -> NoteDocument:
        imported = self.repo.import_document(doc)
        self.plugins.notify_import(imported)
        return imported
