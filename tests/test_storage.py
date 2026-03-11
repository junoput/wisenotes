"""Tests for JsonNoteRepository storage layer."""

import json

from app.schemas import Note, NoteCreate
from app.services.storage import JsonNoteRepository


class TestDeriveNames:
    def test_derive_name_basic(self, repo):
        assert repo.derive_name("Hello World") == "Hello-World"

    def test_derive_name_special_chars(self, repo):
        name = repo.derive_name("Test! @#$ Note")
        assert all(c.isalnum() or c in ("_", "-") for c in name)

    def test_ensure_unique_name(self, repo):
        name = repo.ensure_unique_name("Test")
        assert name == "Test"

    def test_name_to_title(self, repo):
        assert repo.name_to_title("Hello-World") == "Hello World"


class TestNoteStorage:
    def test_list_empty(self, repo):
        assert repo.list_notes() == []

    def test_upsert_and_get(self, repo, service):
        note = service.create_note(NoteCreate(title="Stored"))
        fetched = repo.get_note(note.id)
        assert fetched is not None
        assert fetched.id == note.id

    def test_delete(self, repo, service):
        note = service.create_note(NoteCreate(title="Delete"))
        repo.delete_note(note.id)
        assert repo.get_note(note.id) is None

    def test_file_on_disk(self, repo, service, data_dir):
        note = service.create_note(NoteCreate(title="Disk"))
        note_file = data_dir / note.name / f"{note.name}.json"
        assert note_file.exists()
        data = json.loads(note_file.read_text())
        assert data["id"] == note.id
