"""Tests for the block catalogue."""

from app.blocks import BLOCKS, get_all_blocks, get_block


def test_known_block():
    assert get_block("code").name == "code"


def test_unknown_falls_back_to_text():
    assert get_block("nonexistent").name == "text"


def test_catalogue_has_the_types_the_templates_branch_on():
    assert {"chapter", "paragraph", "code", "math", "media", "text"} <= set(get_all_blocks())


def test_only_text_is_hidden_from_picker():
    hidden = {name for name, b in BLOCKS.items() if not b.show_in_picker}
    assert hidden == {"text"}
