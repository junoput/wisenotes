"""Block types a chapter entry can have.

A block is a `Chapter` row whose `type` names one of these. The catalogue only
feeds the "add block" picker and the fallback for unknown types; rendering and
editing live in the templates (components/editor_chapters.html,
partials/chapter_edit_form.html). To add a type: add an entry here, then a
branch in those two templates.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Block:
    name: str
    display_name: str
    emoji: str
    color: str
    show_in_picker: bool = True


BLOCKS: dict[str, Block] = {
    "chapter": Block("chapter", "Chapter", "📄", "#22d3ee"),  # only container, only root type
    "paragraph": Block("paragraph", "Paragraph", "¶", "#64748b"),
    "code": Block("code", "Code", "{}", "#f59e0b"),
    "math": Block("math", "Math", "∑", "#a78bfa"),
    "media": Block("media", "Media", "🖼️", "#ec4899"),
    "text": Block("text", "Text", "📝", "#64748b", show_in_picker=False),  # fallback
}


def get_block(name: str) -> Block:
    """Unknown types render as plain text."""
    return BLOCKS.get(name, BLOCKS["text"])


def get_all_blocks() -> dict[str, Block]:
    return BLOCKS
