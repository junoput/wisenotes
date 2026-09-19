from datetime import datetime

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator


class Chapter(BaseModel):
    id: str
    title: str = Field(min_length=0, max_length=120)
    content: str = Field(default="", max_length=20_000)
    order: int = Field(ge=0)
    parent_id: str | None = None  # For nested chapters
    type: str = Field(default="chapter")  # Block type - unknown types fallback to 'text'
    language: str | None = None  # Language for code/math blocks (e.g., 'python', 'latex')
    source: str | None = None  # Optional source/attribution for any block


class Note(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    folder: str | None = Field(default=None, max_length=120)  # Group notes in folders
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    chapters: list[Chapter] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_chapters(self) -> "Note":
        ids = [c.id for c in self.chapters]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate chapter ids in note")

        by_id = {c.id: c for c in self.chapters}
        sanitized: list[Chapter] = []
        for ch in self.chapters:
            if ch.parent_id is None:
                sanitized.append(ch)
                continue

            if ch.parent_id == ch.id:
                sanitized.append(ch.model_copy(update={"parent_id": None}))
                continue

            if ch.parent_id not in by_id:
                sanitized.append(ch.model_copy(update={"parent_id": None}))
                continue

            sanitized.append(ch)

        self.chapters = sanitized

        return self


class NoteDocument(BaseModel):
    version: str = Field(default="1.0.0")
    exported_at: datetime
    notes: list[Note] = Field(default_factory=list)

    @field_validator("notes")
    @classmethod
    def ensure_ids_unique(cls, notes: list[Note]) -> list[Note]:
        ids = {note.id for note in notes}
        if len(ids) != len(notes):
            raise ValueError("Duplicate note ids in document")
        return notes


class NoteCreate(BaseModel):
    title: str
    tags: list[str] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)


class NoteUpdate(BaseModel):
    title: str | None = None
    folder: str | None = None
    tags: list[str] | None = None
    chapters: list[Chapter] | None = None
