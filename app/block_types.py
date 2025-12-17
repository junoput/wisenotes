"""Block type configuration system.

This module defines all available block types and their properties.
To add a new block type, add an entry to BLOCK_TYPES with the required configuration.
"""

from dataclasses import dataclass
from typing import Literal


BlockTypeValue = Literal["chapter", "paragraph", "code", "math"]


@dataclass
class BlockTypeConfig:
    """Configuration for a block type."""

    name: str
    emoji: str
    color: str
    can_nest: bool
    default_language: str | None = None
    language_options: list[str] | None = None


BLOCK_TYPES: dict[str, BlockTypeConfig] = {
    "chapter": BlockTypeConfig(
        name="chapter",
        emoji="📄",
        color="#22d3ee",
        can_nest=True,
    ),
    "paragraph": BlockTypeConfig(
        name="paragraph",
        emoji="¶",
        color="#64748b",
        can_nest=False,
    ),
    "code": BlockTypeConfig(
        name="code",
        emoji="{}",
        color="#f59e0b",
        can_nest=False,
        default_language="python",
        language_options=["python", "javascript", "typescript", "go", "rust"],
    ),
    "math": BlockTypeConfig(
        name="math",
        emoji="∑",
        color="#a78bfa",
        can_nest=False,
        default_language="latex",
        language_options=["latex", "asciimath"],
    ),
}


def get_block_type_config(block_type: str) -> BlockTypeConfig:
    """Get configuration for a block type."""
    return BLOCK_TYPES.get(block_type, BLOCK_TYPES["paragraph"])


def get_default_language(block_type: str) -> str | None:
    """Get default language for a block type."""
    config = get_block_type_config(block_type)
    return config.default_language


def can_have_children(block_type: str) -> bool:
    """Check if a block type can have nested children."""
    config = get_block_type_config(block_type)
    return config.can_nest
