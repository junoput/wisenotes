"""Paragraph block for plain text content."""

from dataclasses import dataclass
from dataclasses import field

from app.blocks.base import BaseBlock


@dataclass
class ParagraphBlock(BaseBlock):
    """Paragraph block - simple text content within chapters."""

    name: str = "paragraph"
    display_name: str = "Paragraph"
    emoji: str = "¶"
    color: str = "#64748b"

    can_nest: bool = False
    is_container: bool = False

    editor: str = "textarea"
    default_language: str | None = None
    language_options: list[str] = field(default_factory=list)

    display_template: str = "display.html"
    edit_template: str = "edit.html"

    js_modules: list[str] = field(default_factory=list)
    css_modules: list[str] = field(default_factory=list)


# Export singleton instance for registry discovery
block = ParagraphBlock()
