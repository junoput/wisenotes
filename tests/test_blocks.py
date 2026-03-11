"""Tests for the block registry."""

from app.blocks import get_block, get_all_blocks, get_block_choices
from app.blocks.base import BaseBlock


class TestBlockRegistry:
    def test_get_known_block(self):
        block = get_block("code")
        assert isinstance(block, BaseBlock)
        assert block.name == "code"
        assert block.editor == "code-block"

    def test_unknown_falls_back_to_text(self):
        block = get_block("nonexistent")
        assert block.name == "text"

    def test_get_all_blocks_returns_dict(self):
        blocks = get_all_blocks()
        assert isinstance(blocks, dict)
        assert "chapter" in blocks
        assert "text" in blocks
        assert "code" in blocks

    def test_chapter_block_can_nest(self):
        chapter = get_block("chapter")
        assert chapter.can_nest is True
        assert chapter.is_container is True

    def test_non_container_blocks_cannot_nest(self):
        for name in ("text", "paragraph", "code", "math"):
            block = get_block(name)
            assert block.can_nest is False, f"{name} should not nest"

    def test_get_block_choices(self):
        choices = get_block_choices()
        assert isinstance(choices, list)
        assert len(choices) > 0
        # Each entry is (name, display_name, emoji)
        names = [c[0] for c in choices]
        assert "code" in names
