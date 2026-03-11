"""Shared test fixtures."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.plugins.registry import PluginRegistry
from app.services.notes import NoteService
from app.services.storage import JsonNoteRepository
from app.web.dependencies import get_note_service


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
    return NoteService(repo=repo, plugins=PluginRegistry())


@pytest.fixture()
def client(service: NoteService) -> TestClient:
    """FastAPI TestClient with overridden NoteService dependency."""

    def _override():
        return service

    app.dependency_overrides[get_note_service] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()
