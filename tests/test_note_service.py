"""Tests for NoteService business logic."""

import pytest

from app.schemas import NoteCreate, NoteUpdate


class TestNoteServiceCRUD:
    def test_create_note(self, service):
        note = service.create_note(NoteCreate(title="Test Note"))
        assert note.title == "Test Note"
        assert note.id
        assert note.name

    def test_list_notes_empty(self, service):
        assert service.list_notes() == []

    def test_list_notes_after_create(self, service):
        service.create_note(NoteCreate(title="A"))
        service.create_note(NoteCreate(title="B"))
        assert len(service.list_notes()) == 2

    def test_get_note(self, service):
        created = service.create_note(NoteCreate(title="Fetched"))
        fetched = service.get_note(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_note_not_found(self, service):
        assert service.get_note("nonexistent") is None

    def test_update_note_title(self, service):
        note = service.create_note(NoteCreate(title="Old Title"))
        updated = service.update_note(note.id, NoteUpdate(title="New Title"))
        assert updated is not None
        assert updated.title == "New Title"

    def test_update_note_tags(self, service):
        note = service.create_note(NoteCreate(title="Tagged"))
        updated = service.update_note(note.id, NoteUpdate(tags=["a", "b"]))
        assert updated is not None
        assert updated.tags == ["a", "b"]

    def test_update_nonexistent_note(self, service):
        assert service.update_note("nope", NoteUpdate(title="X")) is None

    def test_delete_note(self, service):
        note = service.create_note(NoteCreate(title="Doomed"))
        assert service.delete_note(note.id) is True
        assert service.get_note(note.id) is None

    def test_delete_nonexistent_note(self, service):
        assert service.delete_note("nope") is False


class TestChapterOperations:
    def test_add_chapter(self, service):
        note = service.create_note(NoteCreate(title="CH"))
        result = service.add_chapter(note.id, title="Chapter 1")
        assert result is not None
        assert len(result.chapters) == 1
        assert result.chapters[0].title == "Chapter 1"
        assert result.chapters[0].type == "chapter"

    def test_add_child_block(self, service):
        note = service.create_note(NoteCreate(title="CH"))
        note = service.add_chapter(note.id, title="Parent")
        parent_id = note.chapters[0].id
        result = service.add_chapter_child(note.id, parent_id, block_type="paragraph")
        assert result is not None
        children = [c for c in result.chapters if c.parent_id == parent_id]
        assert len(children) == 1
        assert children[0].type == "paragraph"

    def test_add_chapter_after(self, service):
        note = service.create_note(NoteCreate(title="CH"))
        note = service.add_chapter(note.id, title="First")
        first_id = note.chapters[0].id
        result = service.add_chapter_after(note.id, first_id, title="Second")
        assert result is not None
        root_chapters = sorted(
            [c for c in result.chapters if c.parent_id is None],
            key=lambda c: c.order,
        )
        assert len(root_chapters) == 2
        assert root_chapters[1].title == "Second"

    def test_add_chapter_before(self, service):
        note = service.create_note(NoteCreate(title="CH"))
        note = service.add_chapter(note.id, title="Second")
        second_id = note.chapters[0].id
        result = service.add_chapter_before(note.id, second_id, title="First")
        assert result is not None
        root_chapters = sorted(
            [c for c in result.chapters if c.parent_id is None],
            key=lambda c: c.order,
        )
        assert root_chapters[0].title == "First"

    def test_delete_chapter(self, service):
        note = service.create_note(NoteCreate(title="CH"))
        note = service.add_chapter(note.id, title="Gone")
        ch_id = note.chapters[0].id
        result = service.delete_chapter(note.id, ch_id)
        assert result is not None
        assert len(result.chapters) == 0

    def test_delete_chapter_cascades_children(self, service):
        note = service.create_note(NoteCreate(title="CH"))
        note = service.add_chapter(note.id, title="Parent")
        parent_id = note.chapters[0].id
        note = service.add_chapter_child(note.id, parent_id, block_type="text")
        assert len(note.chapters) == 2
        result = service.delete_chapter(note.id, parent_id)
        assert result is not None
        assert len(result.chapters) == 0

    def test_update_chapter(self, service):
        note = service.create_note(NoteCreate(title="CH"))
        note = service.add_chapter(note.id, title="Old")
        ch_id = note.chapters[0].id
        result = service.update_chapter(note.id, ch_id, title="New", content="Hello")
        assert result is not None
        ch = next(c for c in result.chapters if c.id == ch_id)
        assert ch.title == "New"
        assert ch.content == "Hello"


class TestChapterReordering:
    def _create_note_with_chapters(self, service, count=3):
        note = service.create_note(NoteCreate(title="Reorder"))
        for i in range(count):
            note = service.add_chapter(note.id, title=f"Ch {i}")
        return note

    def test_move_chapter_down(self, service):
        note = self._create_note_with_chapters(service)
        chapters = sorted(
            [c for c in note.chapters if c.parent_id is None],
            key=lambda c: c.order,
        )
        first_id = chapters[0].id
        result = service.move_chapter_down(note.id, first_id)
        new_order = sorted(
            [c for c in result.chapters if c.parent_id is None],
            key=lambda c: c.order,
        )
        assert new_order[1].id == first_id

    def test_move_chapter_up(self, service):
        note = self._create_note_with_chapters(service)
        chapters = sorted(
            [c for c in note.chapters if c.parent_id is None],
            key=lambda c: c.order,
        )
        last_id = chapters[-1].id
        result = service.move_chapter_up(note.id, last_id)
        new_order = sorted(
            [c for c in result.chapters if c.parent_id is None],
            key=lambda c: c.order,
        )
        assert new_order[-2].id == last_id

    def test_move_first_chapter_up_is_noop(self, service):
        note = self._create_note_with_chapters(service)
        chapters = sorted(
            [c for c in note.chapters if c.parent_id is None],
            key=lambda c: c.order,
        )
        result = service.move_chapter_up(note.id, chapters[0].id)
        new_order = sorted(
            [c for c in result.chapters if c.parent_id is None],
            key=lambda c: c.order,
        )
        assert new_order[0].id == chapters[0].id


class TestExportImport:
    def test_export_empty(self, service):
        doc = service.export_document()
        assert doc.notes == []

    def test_roundtrip(self, service):
        service.create_note(NoteCreate(title="Note A"))
        service.create_note(NoteCreate(title="Note B"))
        doc = service.export_document()
        assert len(doc.notes) == 2

        # Delete all, then import
        for n in service.list_notes():
            service.delete_note(n.id)
        assert len(service.list_notes()) == 0

        service.import_document(doc)
        assert len(service.list_notes()) == 2
