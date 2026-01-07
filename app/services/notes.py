import logging
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from app.plugins.registry import PluginRegistry
from app.schemas import Chapter, Note, NoteCreate, NoteDocument, NoteUpdate
from app.services.storage import JsonNoteRepository

logger = logging.getLogger(__name__)


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

    def move_chapter(self, note_id: str, chapter_id: str, target_id: str, parent_id: Optional[str] = None) -> Optional[Note]:
        """Move a chapter before ``target_id`` and optionally change parent.

        - ``target_id`` empty → append to end of the destination group
        - ``parent_id`` sets the destination parent (``None`` = root)
        - Non-chapter blocks cannot be placed at root
        - Destination parent (when provided) must be a chapter
        """
        logger.info(
            "move_chapter START: note=%s chapter=%s target=%s parent=%s",
            note_id,
            chapter_id,
            target_id or "(append)",
            parent_id or "(root)",
        )

        note = self.repo.get_note(note_id)
        if not note:
            logger.error("move_chapter: NOTE NOT FOUND: %s", note_id)
            return None

        moved_chapter = next((ch for ch in note.chapters if ch.id == chapter_id), None)
        if not moved_chapter:
            logger.error("move_chapter: CHAPTER NOT FOUND in note: note=%s chapter=%s", note_id, chapter_id)
            logger.debug("move_chapter: available chapters: %s", [c.id for c in note.chapters[:10]])
            return note

        if chapter_id == target_id:
            logger.debug("move_chapter: no-op (same chapter and target)")
            return note

        logger.debug("move_chapter: moved chapter type=%s parent=%s order=%s", moved_chapter.type, moved_chapter.parent_id, moved_chapter.order)

        new_parent_id = parent_id if parent_id else None
        if new_parent_id is None and moved_chapter.type != "chapter":
            logger.error("move_chapter: VALIDATION FAILED - non-chapter %s cannot be at root", moved_chapter.type)
            raise ValueError(f"Block type '{moved_chapter.type}' cannot be placed at root level. Must be inside a chapter.")
        
        if new_parent_id is not None:
            parent_chapter = next((c for c in note.chapters if c.id == new_parent_id), None)
            if not parent_chapter:
                logger.error("move_chapter: VALIDATION FAILED - destination parent not found: %s", new_parent_id)
                raise ValueError(f"Destination parent chapter not found: {new_parent_id}")
            if parent_chapter.type != "chapter":
                logger.error("move_chapter: VALIDATION FAILED - destination parent is not a chapter: type=%s", parent_chapter.type)
                raise ValueError(f"Destination parent must be a chapter, got '{parent_chapter.type}'")

        old_parent_id = moved_chapter.parent_id
        logger.debug("move_chapter: moving from parent=%s to parent=%s", old_parent_id, new_parent_id)
        
        remaining = [c for c in note.chapters if c.id != chapter_id]
        logger.debug("move_chapter: chapters remaining after removing moved: %d", len(remaining))

        old_siblings = [c for c in remaining if c.parent_id == old_parent_id]
        old_siblings_sorted = sorted(old_siblings, key=lambda c: c.order)
        logger.debug("move_chapter: old parent %s has %d siblings before renumber", old_parent_id, len(old_siblings_sorted))
        for idx, sib in enumerate(old_siblings_sorted):
            sib.order = idx
        logger.debug("move_chapter: renumbered old parent siblings to orders 0-%d", len(old_siblings_sorted) - 1)

        new_siblings = [c for c in remaining if c.parent_id == new_parent_id]
        new_siblings_sorted = sorted(new_siblings, key=lambda c: c.order)
        logger.debug("move_chapter: new parent %s has %d siblings before insertion", new_parent_id, len(new_siblings_sorted))

        moved_updated = moved_chapter.model_copy(update={"parent_id": new_parent_id})
        
        if target_id:
            target_chapter = next((ch for ch in note.chapters if ch.id == target_id), None)
            if not target_chapter:
                logger.error("move_chapter: VALIDATION FAILED - target chapter not found: %s", target_id)
                raise ValueError(f"Target chapter not found: {target_id}")
            if target_chapter.parent_id != new_parent_id:
                logger.error(
                    "move_chapter: VALIDATION FAILED - target parent mismatch: target.parent=%s dest.parent=%s",
                    target_chapter.parent_id,
                    new_parent_id,
                )
                raise ValueError(f"Target chapter is in wrong parent group: {target_chapter.parent_id} vs {new_parent_id}")
            insert_idx = next((i for i, ch in enumerate(new_siblings_sorted) if ch.id == target_id), len(new_siblings_sorted))
            logger.debug("move_chapter: inserting before target at index %d", insert_idx)
            new_siblings_sorted.insert(insert_idx, moved_updated)
        else:
            logger.debug("move_chapter: appending to end of new parent siblings")
            new_siblings_sorted.append(moved_updated)

        for idx, sib in enumerate(new_siblings_sorted):
            sib.order = idx
        logger.debug("move_chapter: renumbered new parent siblings to orders 0-%d", len(new_siblings_sorted) - 1)

        # When moving within same parent, old_siblings and new_siblings are the same chapters
        # So only include them once
        if old_parent_id == new_parent_id:
            untouched = [c for c in remaining if c.parent_id != old_parent_id]
            updated_chapters = untouched + new_siblings_sorted
        else:
            untouched = [c for c in remaining if c.parent_id not in {old_parent_id, new_parent_id}]
            updated_chapters = untouched + old_siblings_sorted + new_siblings_sorted
        logger.debug(
            "move_chapter: final structure - untouched=%d old_siblings=%d new_siblings=%d total=%d",
            len(untouched),
            (len(old_siblings_sorted) if old_parent_id != new_parent_id else 0),
            len(new_siblings_sorted),
            len(updated_chapters),
        )

        # Validate chapter integrity before saving
        chapter_ids = [ch.id for ch in updated_chapters]
        unique_ids = set(chapter_ids)
        if len(unique_ids) != len(chapter_ids):
            logger.error("move_chapter: DUPLICATE IDs detected in result! total=%d unique=%d", len(chapter_ids), len(unique_ids))
            # Find the duplicates
            seen = {}
            for cid in chapter_ids:
                seen[cid] = seen.get(cid, 0) + 1
            duplicates = [cid for cid, count in seen.items() if count > 1]
            logger.error("move_chapter: duplicate IDs: %s", duplicates)
            return note  # Abort to prevent corruption

        updated = note.model_copy(update={
            "chapters": updated_chapters,
            "updated_at": datetime.utcnow(),
        })
        
        try:
            logger.debug("move_chapter: saving note to repository")
            saved = self.repo.upsert_note(updated)
            self.plugins.notify_note_saved(saved)
            logger.info("move_chapter SUCCESS: moved chapter=%s before=%s in note=%s", chapter_id, target_id or "(end)", note_id)
            return saved
        except Exception as e:
            logger.error(
                "move_chapter: FAILED to save note: %s %s",
                note_id,
                str(e),
                exc_info=True,
            )
            raise  # Re-raise so HTTP endpoint can handle it

    def move_chapter_up(self, note_id: str, chapter_id: str) -> Optional[Note]:
        """Move a chapter up within its siblings (decrease order)."""
        note = self.repo.get_note(note_id)
        if not note:
            return None
        
        chapter = next((ch for ch in note.chapters if ch.id == chapter_id), None)
        if not chapter:
            return note
        
        parent_id = chapter.parent_id
        siblings = sorted(
            [ch for ch in note.chapters if ch.parent_id == parent_id],
            key=lambda c: c.order
        )
        
        idx = next((i for i, ch in enumerate(siblings) if ch.id == chapter_id), -1)
        if idx <= 0:
            return note  # Already at top
        
        # Swap with previous sibling
        siblings[idx], siblings[idx - 1] = siblings[idx - 1], siblings[idx]
        
        # Reassign orders
        for i, sib in enumerate(siblings):
            sib.order = i
        
        # Rebuild chapters list
        others = [ch for ch in note.chapters if ch.parent_id != parent_id]
        updated = note.model_copy(update={
            "chapters": others + siblings,
            "updated_at": datetime.utcnow(),
        })
        return self.repo.upsert_note(updated)

    def move_chapter_down(self, note_id: str, chapter_id: str) -> Optional[Note]:
        """Move a chapter down within its siblings (increase order)."""
        note = self.repo.get_note(note_id)
        if not note:
            return None
        
        chapter = next((ch for ch in note.chapters if ch.id == chapter_id), None)
        if not chapter:
            return note
        
        parent_id = chapter.parent_id
        siblings = sorted(
            [ch for ch in note.chapters if ch.parent_id == parent_id],
            key=lambda c: c.order
        )
        
        idx = next((i for i, ch in enumerate(siblings) if ch.id == chapter_id), -1)
        if idx < 0 or idx >= len(siblings) - 1:
            return note  # Already at bottom
        
        # Swap with next sibling
        siblings[idx], siblings[idx + 1] = siblings[idx + 1], siblings[idx]
        
        # Reassign orders
        for i, sib in enumerate(siblings):
            sib.order = i
        
        # Rebuild chapters list
        others = [ch for ch in note.chapters if ch.parent_id != parent_id]
        updated = note.model_copy(update={
            "chapters": others + siblings,
            "updated_at": datetime.utcnow(),
        })
        return self.repo.upsert_note(updated)

    def indent_chapter(self, note_id: str, chapter_id: str) -> Optional[Note]:
        """Indent a chapter (move it inside the previous sibling, making it a child)."""
        note = self.repo.get_note(note_id)
        if not note:
            return None
        
        chapter = next((ch for ch in note.chapters if ch.id == chapter_id), None)
        if not chapter:
            return note
        
        parent_id = chapter.parent_id
        siblings = sorted(
            [ch for ch in note.chapters if ch.parent_id == parent_id],
            key=lambda c: c.order
        )
        
        idx = next((i for i, ch in enumerate(siblings) if ch.id == chapter_id), -1)
        if idx <= 0:
            return note  # No previous sibling to become parent
        
        new_parent = siblings[idx - 1]
        # Only chapters can have children
        if new_parent.type != "chapter":
            return note
        
        # Get existing children of new parent to determine order
        new_siblings = [ch for ch in note.chapters if ch.parent_id == new_parent.id]
        new_order = max((ch.order for ch in new_siblings), default=-1) + 1
        
        # Update chapter's parent and order
        updated_chapters = []
        for ch in note.chapters:
            if ch.id == chapter_id:
                updated_chapters.append(ch.model_copy(update={
                    "parent_id": new_parent.id,
                    "order": new_order
                }))
            else:
                updated_chapters.append(ch)
        
        # Normalize orders for old siblings
        updated_chapters = self._normalize_sibling_orders(updated_chapters, parent_id)
        
        updated = note.model_copy(update={
            "chapters": updated_chapters,
            "updated_at": datetime.utcnow(),
        })
        return self.repo.upsert_note(updated)

    def outdent_chapter(self, note_id: str, chapter_id: str) -> Optional[Note]:
        """Outdent a chapter (move it out of its parent, making it a sibling of the parent)."""
        note = self.repo.get_note(note_id)
        if not note:
            return None
        
        chapter = next((ch for ch in note.chapters if ch.id == chapter_id), None)
        if not chapter or not chapter.parent_id:
            return note  # Already at root level
        
        # Find parent chapter
        parent = next((ch for ch in note.chapters if ch.id == chapter.parent_id), None)
        if not parent:
            return note
        
        grandparent_id = parent.parent_id
        
        # Get siblings of parent (which will be chapter's new siblings)
        parent_siblings = sorted(
            [ch for ch in note.chapters if ch.parent_id == grandparent_id],
            key=lambda c: c.order
        )
        
        # Find parent's index to insert after it
        parent_idx = next((i for i, ch in enumerate(parent_siblings) if ch.id == parent.id), -1)
        if parent_idx < 0:
            return note
        
        # Update chapter's parent_id and insert after parent
        updated_chapters = []
        for ch in note.chapters:
            if ch.id == chapter_id:
                updated_chapters.append(ch.model_copy(update={
                    "parent_id": grandparent_id,
                    "order": parent.order + 1  # After parent
                }))
            else:
                updated_chapters.append(ch)
        
        # Shift orders of siblings that come after
        final_chapters = []
        for ch in updated_chapters:
            if ch.parent_id == grandparent_id and ch.id != chapter_id and ch.order > parent.order:
                final_chapters.append(ch.model_copy(update={"order": ch.order + 1}))
            else:
                final_chapters.append(ch)
        
        # Normalize old parent's children
        final_chapters = self._normalize_sibling_orders(final_chapters, chapter.parent_id)
        
        updated = note.model_copy(update={
            "chapters": final_chapters,
            "updated_at": datetime.utcnow(),
        })
        return self.repo.upsert_note(updated)

    def export_document(self) -> NoteDocument:
        doc = self.repo.export_document()
        self.plugins.notify_export(doc)
        return doc

    def import_document(self, doc: NoteDocument) -> NoteDocument:
        imported = self.repo.import_document(doc)
        self.plugins.notify_import(imported)
        return imported
