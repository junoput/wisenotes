from fastapi import Depends

from app.config import get_settings
from app.plugins.registry import PluginRegistry
from app.plugins.word_count import WordCountPlugin
from app.services.notes import NoteService
from app.services.storage import JsonNoteRepository


def get_repo():
    settings = get_settings()
    return JsonNoteRepository(settings.data_path)


def get_plugins(settings=Depends(get_settings)):
    registry = PluginRegistry()
    if settings.enable_sample_plugins:
        registry.register(WordCountPlugin())
    return registry


def get_note_service(repo=Depends(get_repo), plugins=Depends(get_plugins)) -> NoteService:
    return NoteService(repo=repo, plugins=plugins)
