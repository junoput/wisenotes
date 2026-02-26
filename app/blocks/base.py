"""Base block class that all block types extend."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import Chapter


@dataclass
class BaseBlock:
    """Base configuration for a block type.

    Subclasses should override class attributes to customize behavior.
    """

    # --- Identity ---
    name: str = "text"  # Unique identifier (folder name)
    display_name: str = "Text"  # Human-readable name
    emoji: str = "📝"  # Icon for UI
    color: str = "#64748b"  # Accent color

    # --- Behavior ---
    can_nest: bool = False  # Can contain child blocks?
    is_container: bool = False  # Is this a structural container (chapter)?

    # --- UI ---
    # If False, the block won't show up in the "add block" picker/menu, but it can
    # still be used for rendering (e.g. the 'text' fallback block).
    show_in_picker: bool = True

    # --- Editor ---
    editor: str = "textarea"  # Editor type: 'textarea', 'codemirror', 'media', etc.
    default_language: str | None = None  # Default language for code/math
    language_options: list[str] = field(default_factory=list)  # Available languages

    # --- Templates ---
    # Paths are relative to app/blocks/<name>/templates/
    display_template: str = "display.html"  # Read-only view
    edit_template: str = "edit.html"  # Edit form
    menu_template: str | None = None  # Custom menu entry (optional)

    # --- Modules (JS/CSS) ---
    js_modules: list[str] = field(default_factory=list)  # JS files to load
    css_modules: list[str] = field(default_factory=list)  # CSS files to load

    # --- Data Management ---
    # Name of the folder this block manages inside each note directory.
    # Set to a non-empty string to opt-in (e.g. "media" for the media block).
    # Folders are created lazily — only when the block actually needs to write.
    data_folder: str | None = None

    # Name of the hidden profile folder at the data root (e.g. ".spice") for
    # block-level dependencies / shared component libraries.  Created lazily.
    profile_folder: str | None = None

    def get_template_path(self, template_type: str = "display") -> str:
        """Get full template path for this block."""
        template_name = getattr(self, f"{template_type}_template", "display.html")
        return f"blocks/{self.name}/templates/{template_name}"

    def get_default_content(self) -> str:
        """Default content for new blocks of this type."""
        return ""

    def get_default_title(self, is_root: bool = False) -> str:
        """Default title for new blocks."""
        if self.is_container and is_root:
            return "New chapter"
        return ""

    def validate_content(self, content: str) -> str:
        """Validate and optionally transform content. Override in subclasses."""
        return content

    def prepare_context(self, chapter: "Chapter", note_id: str) -> dict:
        """Prepare template context for rendering. Override for custom data."""
        return {
            "chapter": chapter,
            "note_id": note_id,
            "block": self,
        }

    # --- Data Management Helpers ---

    def get_note_data_dir(self, data_root: Path, note_name: str) -> Path:
        """Return the path to this block's data folder inside a note directory.

        Does NOT create the folder — call ``ensure_note_data_dir`` when you
        actually need to write.
        """
        if not self.data_folder:
            raise ValueError(f"Block '{self.name}' does not declare a data_folder")
        return data_root / note_name / self.data_folder

    def ensure_note_data_dir(self, data_root: Path, note_name: str) -> Path:
        """Lazily create and return this block's per-note data folder."""
        d = self.get_note_data_dir(data_root, note_name)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_profile_dir(self, data_root: Path) -> Path:
        """Return the hidden profile/dependency folder at the data root.

        Does NOT create the folder — call ``ensure_profile_dir`` when you
        actually need to write.
        """
        if not self.profile_folder:
            raise ValueError(f"Block '{self.name}' does not declare a profile_folder")
        return data_root / self.profile_folder

    def ensure_profile_dir(self, data_root: Path) -> Path:
        """Lazily create and return the hidden profile folder."""
        d = self.get_profile_dir(data_root)
        d.mkdir(parents=True, exist_ok=True)
        return d
