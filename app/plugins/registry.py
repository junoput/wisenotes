from typing import Iterable, List

from app.plugins.base import Plugin
from app.schemas import Note, NoteDocument


class PluginRegistry:
    def __init__(self, plugins: Iterable[Plugin] | None = None) -> None:
        self._plugins: List[Plugin] = list(plugins or [])

    def register(self, plugin: Plugin) -> None:
        self._plugins.append(plugin)

    def notify_note_saved(self, note: Note) -> None:
        for plugin in self._plugins:
            plugin.on_note_saved(note)

    def notify_export(self, document: NoteDocument) -> None:
        for plugin in self._plugins:
            plugin.on_export(document)

    def notify_import(self, document: NoteDocument) -> None:
        for plugin in self._plugins:
            plugin.on_import(document)
