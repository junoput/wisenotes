"""Math block for LaTeX and AsciiMath formulas."""

from dataclasses import dataclass
from dataclasses import field

from app.blocks.base import BaseBlock


@dataclass
class MathBlock(BaseBlock):
    """Math block for mathematical formulas and equations."""

    name: str = "math"
    display_name: str = "Math"
    emoji: str = "∑"
    color: str = "#a78bfa"

    can_nest: bool = False
    is_container: bool = False

    editor: str = "textarea"
    default_language: str | None = "latex"
    language_options: list[str] = field(default_factory=lambda: [
        "latex",
        "asciimath",
    ])

    display_template: str = "display.html"
    edit_template: str = "edit.html"

    js_modules: list[str] = field(default_factory=list)
    css_modules: list[str] = field(default_factory=list)


# Export singleton instance for registry discovery
block = MathBlock()
