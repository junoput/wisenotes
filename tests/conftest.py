"""Shared test fixtures."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.notes import NoteService
from app.services.notes import get_note_service
from app.services.storage import JsonNoteRepository


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Temporary data directory for tests."""
    return tmp_path / "data"


@pytest.fixture()
def repo(data_dir: Path) -> JsonNoteRepository:
    """JsonNoteRepository backed by a temp directory."""
    legacy_path = data_dir / "notes.json"
    return JsonNoteRepository(legacy_path)


@pytest.fixture()
def service(repo: JsonNoteRepository) -> NoteService:
    """NoteService wired to a temp repo."""
    return NoteService(repo=repo)


@pytest.fixture()
def client(service: NoteService) -> TestClient:
    """FastAPI TestClient with overridden NoteService dependency."""

    def _override():
        return service

    app.dependency_overrides[get_note_service] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()
