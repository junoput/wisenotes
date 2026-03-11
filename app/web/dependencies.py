from fastapi import Depends

from app.config import get_settings
from app.plugins.registry import PluginRegistry
from app.services.notes import NoteService
from app.services.storage import JsonNoteRepository


def get_repo():
    settings = get_settings()
    return JsonNoteRepository(settings.data_path)


def get_plugins():
    return PluginRegistry()


def get_note_service(repo=Depends(get_repo), plugins=Depends(get_plugins)) -> NoteService:
    return NoteService(repo=repo, plugins=plugins)
