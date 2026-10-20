"""Static guards for the narrow (<= 960 px) notes pane; the layout itself is checked in a browser.

20261014-187: the home-page exception keyed on a class nothing set. 20261019-019:
the fixed dropdown applied without scripts, over the note.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = re.sub(r"/\*.*?\*/", "", (ROOT / "app/static/css/style.css").read_text(), flags=re.S)


def _narrow_block() -> str:
    start = CSS.index("@media (max-width: 960px)")
    depth, i = 0, CSS.index("{", start)
    for j in range(i, len(CSS)):
        depth += {"{": 1, "}": -1}.get(CSS[j], 0)
        if depth == 0:
            return CSS[i : j + 1]
    raise AssertionError("unterminated media block")


def _rules(block: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", block)]


def test_the_fixed_notes_dropdown_needs_scripts():
    fixed = [
        sel
        for sel, body in _rules(_narrow_block())
        if "#note-list" in sel and "position: fixed" in body
    ]
    assert fixed, "premise: the narrow block still makes the notes pane a fixed dropdown"
    assert all(sel.startswith(".js ") for sel in fixed), fixed


def test_without_scripts_the_pane_is_in_the_flow():
    rules = dict(_rules(_narrow_block()))
    assert "position: static" in rules["html:not(.js) #note-list"]


def test_the_scripts_class_is_set_before_paint():
    init = (ROOT / "app/static/js/init-layout.js").read_text()
    base = (ROOT / "app/templates/base.html").read_text()
    assert "classList.add('js')" in init
    assert base.index("init-layout.js") < base.index("</head>")
    assert (
        "defer" not in base[base.index("init-layout.js") - 40 : base.index("init-layout.js") + 20]
    )


def test_the_home_page_exception_keys_on_markup_not_on_an_unset_class():
    assert "no-note-open" not in CSS
    home = [sel for sel, _ in _rules(_narrow_block()) if "#editor:not([data-note-id])" in sel]
    assert home, "the narrow block must exempt the home page from the dropdown"
    editor = (ROOT / "app/templates/index.html").read_text()
    assert (
        '{% if active %}data-note-id="{{ active.id }}"{% endif %}' in editor
    )  # the premise of :has()
