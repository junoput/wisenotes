"""Chapter block - special container that can hold child blocks."""

from dataclasses import dataclass
from dataclasses import field

from app.blocks.base import BaseBlock


@dataclass
class ChapterBlock(BaseBlock):
    """Chapter block - structural container for other blocks.

    This is a special block type that:
    - Can contain nested child blocks
    - Is the only block type allowed at root level
    - Has a required title
    """

    name: str = "chapter"
    display_name: str = "Chapter"
    emoji: str = "📄"
    color: str = "#22d3ee"

    can_nest: bool = True
    is_container: bool = True

    editor: str = "textarea"
    default_language: str | None = None
    language_options: list[str] = field(default_factory=list)

    display_template: str = "display.html"
    edit_template: str = "edit.html"

    js_modules: list[str] = field(default_factory=list)
    css_modules: list[str] = field(default_factory=list)

    def get_default_title(self, is_root: bool = False) -> str:
        """Chapters always get a default title."""
        return "New chapter"


# Export singleton instance for registry discovery
block = ChapterBlock()
