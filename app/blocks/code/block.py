"""Code block with syntax highlighting."""

from dataclasses import dataclass
from dataclasses import field

from app.blocks.base import BaseBlock


@dataclass
class CodeBlock(BaseBlock):
    """Code block with CodeMirror editor and syntax highlighting."""

    name: str = "code"
    display_name: str = "Code"
    emoji: str = "{}"
    color: str = "#f59e0b"

    can_nest: bool = False
    is_container: bool = False

    editor: str = "codemirror"
    default_language: str | None = "python"
    language_options: list[str] = field(default_factory=lambda: [
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "rust",
    ])

    display_template: str = "display.html"
    edit_template: str = "edit.html"

    js_modules: list[str] = field(default_factory=lambda: [
        "/static/vendor/codemirror/codemirror.js",
    ])
    css_modules: list[str] = field(default_factory=lambda: [
        "/static/vendor/codemirror/codemirror.css",
        "/static/vendor/codemirror/dracula.css",
    ])

    # CodeMirror mode mapping
    mode_map: dict[str, str] = field(default_factory=lambda: {
        "python": "python",
        "javascript": "javascript",
        "typescript": "javascript",
        "java": "clike",
        "go": "go",
        "rust": "rust",
    })

    def get_codemirror_mode(self, language: str | None) -> str:
        """Get the CodeMirror mode for a language."""
        lang = language or self.default_language or "python"
        return self.mode_map.get(lang, "javascript")


# Export singleton instance for registry discovery
block = CodeBlock()
