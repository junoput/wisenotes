"""Media block for images and other media files."""

from dataclasses import dataclass
from dataclasses import field

from app.blocks.base import BaseBlock


@dataclass
class MediaBlock(BaseBlock):
    """Media block for images, with gallery picker."""

    name: str = "media"
    display_name: str = "Media"
    emoji: str = "🖼️"
    color: str = "#ec4899"

    can_nest: bool = False
    is_container: bool = False

    editor: str = "media"
    default_language: str | None = None
    language_options: list[str] = field(default_factory=list)

    display_template: str = "display.html"
    edit_template: str = "edit.html"

    js_modules: list[str] = field(default_factory=list)
    css_modules: list[str] = field(default_factory=list)

    # The media block owns the "media" folder inside each note directory.
    # Created lazily when a file is first uploaded — never pre-created.
    data_folder: str | None = "media"


# Export singleton instance for registry discovery
block = MediaBlock()
