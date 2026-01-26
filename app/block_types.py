"""Block type configuration system.

This module provides backward-compatible access to block type configuration.
Block types are now defined modularly in app/blocks/<name>/.

To add a new block type:
1. Create a folder: app/blocks/<name>/
2. Add block.py with a class extending BaseBlock
3. Add templates/ folder with display.html and edit.html
4. The block will be auto-discovered on startup
"""

from dataclasses import dataclass
from typing import Literal

from app.blocks import get_all_blocks
from app.blocks import get_block


# Backward compatibility type hint - actual types come from registry
BlockTypeValue = Literal["chapter", "paragraph", "code", "math", "media", "text"]


@dataclass
class BlockTypeConfig:
    """Configuration for a block type (backward compatibility wrapper)."""

    name: str
    emoji: str
    color: str
    can_nest: bool
    show_in_picker: bool = True
    default_language: str | None = None
    language_options: list[str] | None = None


def _block_to_config(block) -> BlockTypeConfig:
    """Convert a BaseBlock to legacy BlockTypeConfig."""
    return BlockTypeConfig(
        name=block.name,
        emoji=block.emoji,
        color=block.color,
        can_nest=block.can_nest,
        show_in_picker=getattr(block, "show_in_picker", True),
        default_language=block.default_language,
        language_options=block.language_options if block.language_options else None,
    )


def get_block_types() -> dict[str, BlockTypeConfig]:
    """Get all block types as legacy config dict."""
    blocks = get_all_blocks()
    return {name: _block_to_config(b) for name, b in blocks.items()}


# Legacy BLOCK_TYPES dict - populated lazily
BLOCK_TYPES: dict[str, BlockTypeConfig] = {}


def _ensure_block_types() -> None:
    """Populate BLOCK_TYPES if empty."""
    global BLOCK_TYPES
    if not BLOCK_TYPES:
        BLOCK_TYPES.update(get_block_types())


def get_block_type_config(block_type: str) -> BlockTypeConfig:
    """Get configuration for a block type. Falls back to 'text' for unknown types."""
    _ensure_block_types()
    if block_type in BLOCK_TYPES:
        return BLOCK_TYPES[block_type]
    # Fallback to text block
    return _block_to_config(get_block("text"))


def get_default_language(block_type: str) -> str | None:
    """Get default language for a block type."""
    block = get_block(block_type)
    return block.default_language


def can_have_children(block_type: str) -> bool:
    """Check if a block type can have nested children."""
    block = get_block(block_type)
    return block.can_nest
