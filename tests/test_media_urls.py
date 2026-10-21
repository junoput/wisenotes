"""20261021-009: one rule for what a media block points at, read as a browser reads it."""

import pytest

from app.media_urls import media_kind
from app.media_urls import missing_name


@pytest.mark.parametrize(
    "content",
    [
        "https://example.org/a.png",
        "HTTP://example.org/a.png",
        "hTtPs://example.org/a.png",
        "  https://example.org/a.png",
        "\x00https://example.org/a.png",
        "ht\ttps://example.org/a.png",
        "//example.org/a.png",
        "/\\example.org/a.png",
        "\\\\example.org/a.png",
    ],
)
def test_another_host_in_any_spelling_a_browser_accepts_is_external(content):
    assert media_kind(content) == "external"


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        ("/api/notes/n/media/a.png", "image"),
        ("  /api/notes/n/media/a.png  ", "image"),
        ("data:image/png;base64,AAAA", "inline"),
        ("DATA:Image/png;base64,AAAA", "inline"),
        ("data:text/html,<b>x</b>", "other"),
        ("javascript:alert(1)", "other"),
        ("JaVaScRiPt:alert(1)", "other"),
        ("media/Old-Name/pic.png", "other"),
        ("missing:pic.png", "missing"),
        ("", "empty"),
        (None, "empty"),
        ("   ", "empty"),
    ],
)
def test_every_other_kind(content, kind):
    assert media_kind(content) == kind


@pytest.mark.parametrize(
    ("content", "name"),
    [
        ("missing:a.png", "a.png"),
        ("  missing:a.png ", "a.png"),
        ("\x01missing:a.png", "a.png"),
        ("mis\tsing:a.png", "a.png"),
        ("/api/notes/n/media/a.png", ""),
        ("", ""),
    ],
)
def test_missing_name_reads_the_placeholder_as_media_kind_does(content, name):
    # 20261021-013 review: the templates cut content.strip()[8:], which disagreed
    # with media_kind's cleaning.
    assert missing_name(content) == name
    assert (media_kind(content) == "missing") == bool(name)
