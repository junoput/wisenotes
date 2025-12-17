from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator


class Chapter(BaseModel):
    id: str
    title: str = Field(min_length=0, max_length=120)
    content: str = Field(default="", max_length=20_000)
    order: int = Field(ge=0)
    parent_id: Optional[str] = None  # For nested chapters
    type: Literal["chapter", "paragraph", "code", "math"] = Field(default="chapter")
    language: Optional[str] = None  # Language for code/math blocks (e.g., 'python', 'latex')


class Note(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=200)
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    chapters: List[Chapter] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_chapters(self) -> "Note":
        ids = [c.id for c in self.chapters]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate chapter ids in note")

        by_id = {c.id: c for c in self.chapters}
        sanitized: List[Chapter] = []
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
    notes: List[Note] = Field(default_factory=list)

    @field_validator("notes")
    @classmethod
    def ensure_ids_unique(cls, notes: List[Note]) -> List[Note]:
        ids = {note.id for note in notes}
        if len(ids) != len(notes):
            raise ValueError("Duplicate note ids in document")
        return notes


class NoteCreate(BaseModel):
    title: str
    tags: List[str] = Field(default_factory=list)
    chapters: List[Chapter] = Field(default_factory=list)


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    tags: Optional[List[str]] = None
    chapters: Optional[List[Chapter]] = None
