"""Block registry with auto-discovery.

Scans app/blocks/ for block definitions and registers them automatically.
Unknown block types fall back to the default 'text' block.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.blocks.base import BaseBlock

logger = logging.getLogger(__name__)


class BlockRegistry:
    """Registry of available block types with auto-discovery."""

    _instance: BlockRegistry | None = None
    _blocks: dict[str, "BaseBlock"]
    _default_block_name: str = "text"
    _initialized: bool = False

    def __new__(cls) -> "BlockRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._blocks = {}
            cls._instance._initialized = False
        return cls._instance

    def discover_blocks(self) -> None:
        """Scan blocks directory and register all found blocks."""
        if self._initialized:
            return

        blocks_dir = Path(__file__).parent
        for item in sorted(blocks_dir.iterdir()):
            if not item.is_dir():
                continue
            if item.name.startswith("_"):
                continue

            block_module_path = item / "block.py"
            if not block_module_path.exists():
                continue

            try:
                module = importlib.import_module(f"app.blocks.{item.name}.block")
                if hasattr(module, "block"):
                    block = module.block
                    self.register(block)
                    logger.debug("Registered block: %s", block.name)
            except Exception as e:
                logger.warning("Failed to load block from %s: %s", item.name, e)

        self._initialized = True
        logger.info("Block registry initialized with %d blocks", len(self._blocks))

    def register(self, block: "BaseBlock") -> None:
        """Register a block type."""
        self._blocks[block.name] = block

    def get(self, name: str) -> "BaseBlock":
        """Get a block by name. Returns default block if not found."""
        self.discover_blocks()
        if name in self._blocks:
            return self._blocks[name]
        # Fallback to default
        logger.debug("Unknown block type '%s', using default '%s'", name, self._default_block_name)
        return self._blocks.get(self._default_block_name, self._create_fallback())

    def get_all(self) -> dict[str, "BaseBlock"]:
        """Get all registered blocks."""
        self.discover_blocks()
        return dict(self._blocks)

    def get_choices(self) -> list[tuple[str, str, str]]:
        """Get block choices for menus: [(name, display_name, emoji), ...]."""
        self.discover_blocks()
        return [
            (b.name, b.display_name, b.emoji)
            for b in self._blocks.values()
        ]

    def _create_fallback(self) -> "BaseBlock":
        """Create a minimal fallback block if nothing is registered."""
        from app.blocks.base import BaseBlock
        return BaseBlock()


# Module-level convenience functions
_registry = BlockRegistry()


def get_block(name: str) -> "BaseBlock":
    """Get a block configuration by type name."""
    return _registry.get(name)


def get_all_blocks() -> dict[str, "BaseBlock"]:
    """Get all registered blocks."""
    return _registry.get_all()


def get_block_choices() -> list[tuple[str, str, str]]:
    """Get block choices for UI menus."""
    return _registry.get_choices()
