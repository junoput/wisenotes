from app.plugins.base import Plugin
from app.schemas import Note, NoteDocument


class WordCountPlugin(Plugin):
    def on_note_saved(self, note: Note) -> None:
        return None

    def on_export(self, document: NoteDocument) -> None:
        return None

    def on_import(self, document: NoteDocument) -> None:
        return None
