"""The light palette in style.css: written twice, so it must stay one palette, and readable.

It is declared under :root[data-theme="light"] (chosen in the top bar) and again
under prefers-color-scheme: light (no choice made). CSS cannot share one block
between a selector and a media query, so nothing but this test keeps the two equal.
"""

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "app/static/css/style.css").read_text()


def block(after: str) -> dict[str, str]:
    """The custom properties of the first {...} that follows `after`."""
    start = CSS.index(after)
    body = CSS[CSS.index("{", start) + 1 : CSS.index("}", start)]
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))


def light_chosen() -> dict[str, str]:
    return block(':root[data-theme="light"]')


def light_system() -> dict[str, str]:
    return block(":root:not([data-theme])")


def contrast(fg: str, bg: str) -> float:
    def lum(hex_: str) -> float:
        rgb = [int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_both_light_blocks_are_found_and_carry_the_palette():
    # premise: the parser sees two real palettes, not two empty dicts that compare equal
    assert len(light_chosen()) >= 15 and "--bg" in light_chosen() and "--danger" in light_chosen()
    assert len(light_system()) >= 15


def test_chosen_light_and_system_light_are_the_same_palette():
    assert light_chosen() == light_system()


def test_light_text_meets_wcag_aa_on_the_page_surfaces():
    p = light_chosen()
    low = [
        (fg, bg, round(contrast(p[fg], p[bg]), 2))
        for fg in ("--text", "--muted", "--accent", "--danger")
        for bg in ("--bg", "--panel", "--card", "--field")
        if contrast(p[fg], p[bg]) < 4.5
    ]
    assert not low, low
    assert contrast(p["--code-fg"], p["--code-bg"]) >= 4.5


def test_the_formula_source_caption_is_readable_in_both_themes():
    # .math-source-caption draws --muted on a math block: --field, or --card on hover.
    dark, light = block(":root"), light_chosen()
    for p in (dark, light):
        for bg in ("--field", "--card"):
            assert contrast(p["--muted"], p[bg]) >= 4.5, (bg, p[bg])


def test_light_delete_button_is_readable():
    # .btn.danger draws --danger text on a .btn, whose light background is --raised.
    # With #dc2626 that pair was 3.92:1, measured in the browser (20261019).
    p = light_chosen()
    assert contrast(p["--danger"], p["--raised"]) >= 4.5
