"""Tests for Pydantic schemas."""

import pytest
from datetime import datetime

from app.schemas import Chapter, Note, NoteCreate, NoteUpdate


class TestChapter:
    def test_minimal_chapter(self):
        ch = Chapter(id="c1", title="Test", order=0)
        assert ch.content == ""
        assert ch.type == "chapter"
        assert ch.language is None

    def test_chapter_with_all_fields(self):
        ch = Chapter(
            id="c1", title="Code", order=1,
            content="print('hi')", type="code", language="python",
            parent_id="p1", source="example.py",
        )
        assert ch.language == "python"
        assert ch.parent_id == "p1"


class TestNote:
    def test_duplicate_chapter_ids_rejected(self):
        with pytest.raises(ValueError, match="Duplicate chapter ids"):
            Note(
                id="n1", name="test", title="Test",
                created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
                chapters=[
                    Chapter(id="c1", title="A", order=0),
                    Chapter(id="c1", title="B", order=1),
                ],
            )

    def test_self_referencing_parent_fixed(self):
        note = Note(
            id="n1", name="test", title="Test",
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            chapters=[Chapter(id="c1", title="A", order=0, parent_id="c1")],
        )
        # Self-reference should be cleared
        assert note.chapters[0].parent_id is None

    def test_missing_parent_cleared(self):
        note = Note(
            id="n1", name="test", title="Test",
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            chapters=[Chapter(id="c1", title="A", order=0, parent_id="nonexistent")],
        )
        assert note.chapters[0].parent_id is None


class TestNoteCreate:
    def test_from_title(self):
        nc = NoteCreate(title="My Note")
        assert nc.title == "My Note"


class TestNoteUpdate:
    def test_partial_update(self):
        nu = NoteUpdate(title="New Title")
        assert nu.title == "New Title"
        assert nu.tags is None
