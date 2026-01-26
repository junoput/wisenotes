"""Modular block system.

Each block type lives in its own subfolder with:
- block.py: Block class definition extending BaseBlock
- templates/: Jinja2 partials for display and edit
"""

from app.blocks.registry import BlockRegistry
from app.blocks.registry import get_block
from app.blocks.registry import get_all_blocks
from app.blocks.registry import get_block_choices
from app.blocks.base import BaseBlock

__all__ = [
    "BlockRegistry",
    "BaseBlock",
    "get_block",
    "get_all_blocks",
    "get_block_choices",
]
