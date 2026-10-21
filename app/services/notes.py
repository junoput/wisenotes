import logging
from datetime import datetime
from typing import Any
from urllib.parse import unquote
from urllib.parse import urlsplit
from uuid import uuid4

from app.config import get_settings
from app.schemas import Chapter
from app.schemas import Note
from app.schemas import NoteCreate
from app.schemas import NoteDocument
from app.schemas import NoteUpdate
from app.services.storage import JsonNoteRepository

logger = logging.getLogger(__name__)

_DEFAULT_LANGUAGES: dict[str, str] = {
    "code": "python",
    "math": "latex",
}


def _shows(content: str | None, path: str) -> bool:
    """Whether a media block's URL names this path. The host, query and fragment do
    not change which file the server sends, so a PUT that set
    "/api/...png?v=2" or "http://host/api/...png" still counts as a use."""
    shown = urlsplit((content or "").strip())
    return unquote(shown.path) == path


def media_users(notes: list[Note], note: Note, filename: str) -> list[str]:
    """The media blocks, in any of `notes`, that show this file: "<note> / <chapter>"."""
    path = f"/api/notes/{note.id}/media/{filename}"
    users = []
    for n in notes:
        titles = {c.id: c.title for c in n.chapters}
        for c in n.chapters:
            if c.type == "media" and _shows(c.content, path):
                where = titles.get(c.parent_id or "") or c.title or "untitled"
                users.append(f"{n.title} / {where}")
    return users


def _make_chapter(
    existing_ids: set[str],
    block_type: str,
    order: int,
    parent_id: str | None,
    title: str | None = None,
) -> Chapter:
    """Create a new Chapter with sensible defaults based on block type."""
    chapter_id = str(uuid4())
    while chapter_id in existing_ids:
        chapter_id = str(uuid4())

    if title is None:
        title = "New chapter" if (block_type == "chapter" and parent_id is None) else ""

    return Chapter(
        id=chapter_id,
        title=title,
        content="",
        order=order,
        parent_id=parent_id,
        type=block_type,
        language=_DEFAULT_LANGUAGES.get(block_type),
    )


class NoteService:
    def __init__(self, repo: JsonNoteRepository) -> None:
        self.repo = repo

    def list_notes(self) -> list[Note]:
        return self.repo.list_notes()

    def get_note(self, note_id: str) -> Note | None:
        return self.repo.get_note(note_id)

    def save_media_file(self, note_id: str, filename: str, content: bytes) -> str | None:
        """Save media file into the media block-managed folder. Returns relative path."""
        note = self.get_note(note_id)
        if not note:
            return None
        return self.repo.save_media(note.name, filename, content)

    def save_module_metadata(
        self, note_id: str, module_name: str, key: str, payload: dict[str, Any]
    ) -> bool:
        """Persist module metadata in note JSON."""
        note = self.get_note(note_id)
        if not note:
            return False
        self.repo.upsert_module_metadata(note.name, module_name, key, payload)
        return True

    def create_note(self, payload: NoteCreate) -> Note:
        now = datetime.utcnow()
        title = payload.title.strip() or "Untitled note"
        # The folder name is derived from the title; the title itself is kept as typed.
        unique_name = self.repo.ensure_unique_name(self.repo.derive_name(title))
        note = Note(
            id=str(uuid4()),
            name=unique_name,
            title=title,
            tags=payload.tags,
            created_at=now,
            updated_at=now,
            chapters=payload.chapters,
        )
        saved = self.repo.upsert_note(note)
        return saved

    def update_note(self, note_id: str, payload: NoteUpdate) -> Note | None:
        existing = self.repo.get_note(note_id)
        if not existing:
            return None
        title = (payload.title or "").strip() or existing.title
        base_name = self.repo.derive_name(title)
        # Keep the folder unless the title now derives a different name; the note's own
        # folder never counts as taken, so a rename does not earn a "-2" from itself.
        new_name = (
            existing.name
            if base_name == existing.name
            else self.repo.ensure_unique_name(base_name, keep=existing.name)
        )
        updated = existing.model_copy(
            update={
                "name": new_name,
                "title": title,
                "folder": payload.folder if payload.folder is not None else existing.folder,
                "tags": payload.tags if payload.tags is not None else existing.tags,
                "chapters": payload.chapters if payload.chapters is not None else existing.chapters,
                "updated_at": datetime.utcnow(),
            }
        )
        # Pass old name to allow repo to rename folder/file if needed
        saved = self.repo.upsert_note(updated, old_name=existing.name)
        return saved

    def media_borrowers(self, note: Note) -> list[str]:
        """Blocks in OTHER notes that show one of this note's images, which deleting
        the note would remove with its folder: "<file>: <note> / <chapter>"."""
        others = [n for n in self.list_notes() if n.id != note.id]
        return [
            f"{f}: {user}"
            for f in self.repo.list_media(note.name)
            for user in media_users(others, note, f)
        ]

    def delete_note(self, note_id: str) -> bool:
        if not self.repo.get_note(note_id):
            return False
        self.repo.delete_note(note_id)
        return True

    def delete_chapter(self, note_id: str, chapter_id: str) -> Note | None:
        """Delete a chapter (and its descendants) from a note."""
        note = self.repo.get_note(note_id)
        if not note:
            return None

        if not any(ch.id == chapter_id for ch in note.chapters):
            return note

        to_delete = self._collect_descendant_ids(note.chapters, chapter_id)
        to_delete.add(chapter_id)
        updated_chapters = [ch for ch in note.chapters if ch.id not in to_delete]
        updated = note.model_copy(
            update={
                "chapters": updated_chapters,
                "updated_at": datetime.utcnow(),
            }
        )
        saved = self.repo.upsert_note(updated)
        return saved

    @staticmethod
    def _collect_descendant_ids(chapters: list[Chapter], parent_id: str) -> set[str]:
        children = [c for c in chapters if c.parent_id == parent_id]
        ids: set[str] = set()
        for child in children:
            ids.add(child.id)
            ids.update(NoteService._collect_descendant_ids(chapters, child.id))
        return ids

    @staticmethod
    def _normalize_sibling_orders(chapters: list[Chapter], parent_id: str | None) -> list[Chapter]:
        siblings = [c for c in chapters if c.parent_id == parent_id]
        others = [c for c in chapters if c.parent_id != parent_id]
        normalized_siblings = [
            ch.model_copy(update={"order": idx})
            for idx, ch in enumerate(sorted(siblings, key=lambda c: (c.order, c.id)))
        ]
        return others + normalized_siblings

    def _validate_block_placement(self, note: Note, parent_id: str | None, block_type: str) -> bool:
        """Return True if the block type can be placed under the given parent."""
        if parent_id is None:
            return block_type == "chapter"
        parent = next((c for c in note.chapters if c.id == parent_id), None)
        return parent is not None and parent.type == "chapter"

    def _next_sibling_order(self, chapters: list[Chapter], parent_id: str | None) -> int:
        siblings = [c for c in chapters if c.parent_id == parent_id]
        return max((c.order for c in siblings), default=-1) + 1

    def _save(self, note: Note, **update_fields) -> Note:
        """Apply updates and persist."""
        update_fields.setdefault("updated_at", datetime.utcnow())
        updated = note.model_copy(update=update_fields)
        saved = self.repo.upsert_note(updated)
        return saved

    def add_chapter(
        self,
        note_id: str,
        title: str | None = None,
        parent_id: str | None = None,
        block_type: str = "chapter",
    ) -> Note | None:
        note = self.repo.get_note(note_id)
        if not note or not self._validate_block_placement(note, parent_id, block_type):
            return None

        existing_ids = {c.id for c in note.chapters}
        order = self._next_sibling_order(note.chapters, parent_id)
        new_chapter = _make_chapter(existing_ids, block_type, order, parent_id, title)
        chapters = self._normalize_sibling_orders([*note.chapters, new_chapter], parent_id)
        return self._save(note, chapters=chapters)

    def add_chapter_after(
        self, note_id: str, prev_id: str, title: str | None = None, block_type: str = "chapter"
    ) -> Note | None:
        note = self.repo.get_note(note_id)
        if not note:
            return None
        prev = next((c for c in note.chapters if c.id == prev_id), None)
        if not prev or not self._validate_block_placement(note, prev.parent_id, block_type):
            return None

        insert_order = prev.order + 1
        shifted = [
            ch.model_copy(update={"order": ch.order + 1})
            if ch.parent_id == prev.parent_id and ch.order >= insert_order
            else ch
            for ch in note.chapters
        ]
        existing_ids = {c.id for c in note.chapters}
        new_chapter = _make_chapter(existing_ids, block_type, insert_order, prev.parent_id, title)
        chapters = self._normalize_sibling_orders([*shifted, new_chapter], prev.parent_id)
        return self._save(note, chapters=chapters)

    def update_chapter(
        self,
        note_id: str,
        chapter_id: str,
        title: str,
        content: str,
        language: str | None = None,
        source: str | None = None,
    ) -> Note | None:
        note = self.repo.get_note(note_id)
        if not note:
            return None
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
        return self._save(note, chapters=updated_chapters)

    def add_chapter_before(
        self, note_id: str, next_id: str, title: str | None = None, block_type: str = "chapter"
    ) -> Note | None:
        note = self.repo.get_note(note_id)
        if not note:
            return None
        nxt = next((c for c in note.chapters if c.id == next_id), None)
        if not nxt or not self._validate_block_placement(note, nxt.parent_id, block_type):
            return None

        insert_order = nxt.order
        shifted = [
            ch.model_copy(update={"order": ch.order + 1})
            if ch.parent_id == nxt.parent_id and ch.order >= insert_order
            else ch
            for ch in note.chapters
        ]
        existing_ids = {c.id for c in note.chapters}
        new_chapter = _make_chapter(existing_ids, block_type, insert_order, nxt.parent_id, title)
        chapters = self._normalize_sibling_orders([*shifted, new_chapter], nxt.parent_id)
        return self._save(note, chapters=chapters)

    def add_chapter_child(
        self, note_id: str, parent_id: str, title: str | None = None, block_type: str = "chapter"
    ) -> Note | None:
        note = self.repo.get_note(note_id)
        if not note:
            return None
        parent = next((c for c in note.chapters if c.id == parent_id), None)
        if not parent or parent.type != "chapter":
            return None

        existing_ids = {c.id for c in note.chapters}
        order = self._next_sibling_order(note.chapters, parent_id)
        new_chapter = _make_chapter(existing_ids, block_type, order, parent_id, title)
        chapters = self._normalize_sibling_orders([*note.chapters, new_chapter], parent_id)
        return self._save(note, chapters=chapters)

    def move_chapter(
        self, note_id: str, chapter_id: str, target_id: str, parent_id: str | None = None
    ) -> Note | None:
        """Move a chapter before *target_id* under *parent_id*.

        *target_id* empty → append to end of the destination group.
        """
        note = self.repo.get_note(note_id)
        if not note:
            return None

        moved = next((ch for ch in note.chapters if ch.id == chapter_id), None)
        if not moved:
            return note
        if chapter_id == target_id:
            return note

        new_parent_id = parent_id or None

        # Validate placement rules
        if new_parent_id is None and moved.type != "chapter":
            raise ValueError(f"Block type '{moved.type}' cannot be placed at root level.")
        if new_parent_id is not None:
            dest = next((c for c in note.chapters if c.id == new_parent_id), None)
            if not dest:
                raise ValueError(f"Destination parent not found: {new_parent_id}")
            if dest.type != "chapter":
                raise ValueError(f"Destination parent must be a chapter, got '{dest.type}'")

        old_parent_id = moved.parent_id
        remaining = [c for c in note.chapters if c.id != chapter_id]

        # Re-number old siblings
        old_siblings = sorted(
            [c for c in remaining if c.parent_id == old_parent_id], key=lambda c: c.order
        )
        for idx, sib in enumerate(old_siblings):
            sib.order = idx

        # Build new siblings list and insert
        new_siblings = sorted(
            [c for c in remaining if c.parent_id == new_parent_id], key=lambda c: c.order
        )
        moved_updated = moved.model_copy(update={"parent_id": new_parent_id})

        if target_id:
            target = next((ch for ch in note.chapters if ch.id == target_id), None)
            if not target:
                raise ValueError(f"Target chapter not found: {target_id}")
            if target.parent_id != new_parent_id:
                raise ValueError("Target chapter parent mismatch")
            insert_idx = next(
                (i for i, ch in enumerate(new_siblings) if ch.id == target_id), len(new_siblings)
            )
            new_siblings.insert(insert_idx, moved_updated)
        else:
            new_siblings.append(moved_updated)

        for idx, sib in enumerate(new_siblings):
            sib.order = idx

        if old_parent_id == new_parent_id:
            untouched = [c for c in remaining if c.parent_id != old_parent_id]
            updated_chapters = untouched + new_siblings
        else:
            untouched = [c for c in remaining if c.parent_id not in {old_parent_id, new_parent_id}]
            updated_chapters = untouched + old_siblings + new_siblings

        # Integrity check
        ids = [ch.id for ch in updated_chapters]
        if len(set(ids)) != len(ids):
            logger.error("move_chapter: duplicate IDs detected, aborting")
            return note

        return self._save(note, chapters=updated_chapters)

    def move_chapter_up(self, note_id: str, chapter_id: str) -> Note | None:
        """Move a chapter up within its siblings."""
        note = self.repo.get_note(note_id)
        if not note:
            return None
        chapter = next((ch for ch in note.chapters if ch.id == chapter_id), None)
        if not chapter:
            return note

        siblings = sorted(
            [ch for ch in note.chapters if ch.parent_id == chapter.parent_id], key=lambda c: c.order
        )
        idx = next((i for i, ch in enumerate(siblings) if ch.id == chapter_id), -1)
        if idx <= 0:
            return note

        siblings[idx], siblings[idx - 1] = siblings[idx - 1], siblings[idx]
        for i, sib in enumerate(siblings):
            sib.order = i
        others = [ch for ch in note.chapters if ch.parent_id != chapter.parent_id]
        return self._save(note, chapters=others + siblings)

    def move_chapter_down(self, note_id: str, chapter_id: str) -> Note | None:
        """Move a chapter down within its siblings."""
        note = self.repo.get_note(note_id)
        if not note:
            return None
        chapter = next((ch for ch in note.chapters if ch.id == chapter_id), None)
        if not chapter:
            return note

        siblings = sorted(
            [ch for ch in note.chapters if ch.parent_id == chapter.parent_id], key=lambda c: c.order
        )
        idx = next((i for i, ch in enumerate(siblings) if ch.id == chapter_id), -1)
        if idx < 0 or idx >= len(siblings) - 1:
            return note

        siblings[idx], siblings[idx + 1] = siblings[idx + 1], siblings[idx]
        for i, sib in enumerate(siblings):
            sib.order = i
        others = [ch for ch in note.chapters if ch.parent_id != chapter.parent_id]
        return self._save(note, chapters=others + siblings)

    def indent_chapter(self, note_id: str, chapter_id: str) -> Note | None:
        """Indent a chapter (move it inside the previous sibling, making it a child)."""
        note = self.repo.get_note(note_id)
        if not note:
            return None

        chapter = next((ch for ch in note.chapters if ch.id == chapter_id), None)
        if not chapter:
            return note

        parent_id = chapter.parent_id
        siblings = sorted(
            [ch for ch in note.chapters if ch.parent_id == parent_id], key=lambda c: c.order
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
                updated_chapters.append(
                    ch.model_copy(update={"parent_id": new_parent.id, "order": new_order})
                )
            else:
                updated_chapters.append(ch)

        # Normalize orders for old siblings
        updated_chapters = self._normalize_sibling_orders(updated_chapters, parent_id)

        updated = note.model_copy(
            update={
                "chapters": updated_chapters,
                "updated_at": datetime.utcnow(),
            }
        )
        return self.repo.upsert_note(updated)

    def outdent_chapter(self, note_id: str, chapter_id: str) -> Note | None:
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
            [ch for ch in note.chapters if ch.parent_id == grandparent_id], key=lambda c: c.order
        )

        # Find parent's index to insert after it
        parent_idx = next((i for i, ch in enumerate(parent_siblings) if ch.id == parent.id), -1)
        if parent_idx < 0:
            return note

        # Update chapter's parent_id and insert after parent
        updated_chapters = []
        for ch in note.chapters:
            if ch.id == chapter_id:
                updated_chapters.append(
                    ch.model_copy(
                        update={
                            "parent_id": grandparent_id,
                            "order": parent.order + 1,  # After parent
                        }
                    )
                )
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

        updated = note.model_copy(
            update={
                "chapters": final_chapters,
                "updated_at": datetime.utcnow(),
            }
        )
        return self.repo.upsert_note(updated)

    def export_document(self) -> NoteDocument:
        return self.repo.export_document()

    def import_document(self, doc: NoteDocument) -> NoteDocument:
        return self.repo.import_document(doc)


def get_note_service() -> NoteService:
    """FastAPI dependency: one repository-backed service per request."""
    return NoteService(JsonNoteRepository(get_settings().data_path))
