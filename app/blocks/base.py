"""Base block class that all block types extend."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
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
