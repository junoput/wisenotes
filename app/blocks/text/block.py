"""Default text block - fallback for unknown block types."""

from dataclasses import dataclass
from dataclasses import field

from app.blocks.base import BaseBlock


@dataclass
class TextBlock(BaseBlock):
    """Simple text block - the default fallback."""

    name: str = "text"
    display_name: str = "Text"
    emoji: str = "📝"
    color: str = "#64748b"

    can_nest: bool = False
    is_container: bool = False

    # This is the fallback block for unknown types; keep it out of the UI picker.
    show_in_picker: bool = False

    editor: str = "textarea"
    default_language: str | None = None
    language_options: list[str] = field(default_factory=list)

    display_template: str = "display.html"
    edit_template: str = "edit.html"

    js_modules: list[str] = field(default_factory=list)
    css_modules: list[str] = field(default_factory=list)


# Export singleton instance for registry discovery
block = TextBlock()
