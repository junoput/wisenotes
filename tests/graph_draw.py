"""Drive the drawing of a graph block in a real browser, under the app's real policy.

    python tests/graph_draw.py http://127.0.0.1:8000 [--shots DIR]

Against a running server, so the Content-Security-Policy is the one the app sends
(no 'unsafe-eval'). Exit 0: every check passed in both arms. Exit 1: a check failed.
Exit 2: VACUOUS, the scripts-on arm drew nothing (so "no violation" would mean nothing)
or the arms could not be told apart.

What it shows, scripts on:
  - the board is drawn: an SVG with a curve and a point, and a slider per slider;
  - JSXGraph's JessieCode compiler is off (JXG.Options.jc.compile is false);
  - no CSP violation event, no console error, no uncaught error;
  - moving a slider changes the curve;
  - a click on the board does not open the block's editor, a click beside it does;
  - hostile text in a comment (markup, an onerror handler) is not turned into markup
    and runs nothing; a hostile definition shows its errors and draws nothing;
Scripts off: the definition is shown as text, and nothing is drawn.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

SPEC = (
    "view 2d  x -6..6  y -4..4\n"
    "a = slider(0, 3, step 0.5, value 1)\n"
    "f(x) = a*sin(x)\n"
    "P = (1, f(1))\n"
)
HOSTILE = (
    '# <img src=x onerror="window.__pwned = 1"> <script>window.__pwned = 2</script>\n'
    "f(x) = sin(x)\n"
    "P = (0, 0)\n"
)
BROKEN = "f(x) = constructor(x)\nQ = (1, __proto__)\n"


def make_note(ctx, base, title, spec, unchecked=False):
    """Create a note holding one graph block. The API refuses a definition with errors;
    an import does not check (a stored one gets in that way), which is how a broken
    one is made here."""
    chapters = [
        {"id": "ch", "title": "Top", "order": 0, "type": "chapter"},
        {"id": "g", "title": "", "order": 0, "type": "graph", "parent_id": "ch", "content": spec},
    ]
    if unchecked:
        now = "2026-10-27T20:00:00"
        full = [
            {**c, "language": None, "source": None, "parent_id": c.get("parent_id")}
            for c in chapters
        ]
        for c in full:
            c.setdefault("content", "")
        note = {
            "id": str(uuid.uuid4()),
            "name": f"Graph-broken-{int(time.time())}",
            "title": title,
            "folder": None,
            "tags": [],
            "created_at": now,
            "updated_at": now,
            "chapters": full,
        }
        document = {"version": "1.0.0", "exported_at": now, "notes": [note]}
        r = ctx.request.post(
            base + "/api/import",
            multipart={
                "file": {
                    "name": "graph.json",
                    "mimeType": "application/json",
                    "buffer": json.dumps(document).encode(),
                }
            },
        )
        return r.json()["imported"][0]
    r = ctx.request.post(
        base + "/api/notes",
        data=json.dumps({"title": title, "chapters": chapters}),
        headers={"content-type": "application/json"},
    )
    return r.json()["id"]


def curve_d(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('.graph-board svg path')]
             .map((p) => p.getAttribute('d') || '').sort((a, b) => b.length - a.length)[0] || ''"""
    )


def drive(p, base, js, shots):
    result = {"js": js, "checks": {}, "scripts_ran": None}
    checks = result["checks"]
    browser = p.chromium.launch()
    # dark, so the shot shows the dark palette; the light one is the default of the page
    ctx = browser.new_context(
        java_script_enabled=js, viewport={"width": 900, "height": 900}, color_scheme="dark"
    )
    page = ctx.new_page()
    problems = []
    page.add_init_script(
        "window.__csp = []; document.addEventListener('securitypolicyviolation',"
        " (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
    )
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on(
        "console",
        lambda m: (
            problems.append(f"console {m.type}: {m.text[:160]}")
            if m.type in ("error", "warning")
            else None
        ),
    )
    stamp = int(time.time())
    good = make_note(ctx, base, f"Graph draw {stamp}", SPEC)
    hostile = make_note(ctx, base, f"Graph hostile {stamp}", HOSTILE)
    broken = make_note(ctx, base, f"Graph broken {stamp}", BROKEN, unchecked=True)
    try:
        page.goto(f"{base}/notes/{good}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500 if js else 0)
        result["scripts_ran"] = page.evaluate("() => typeof window.htmx !== 'undefined'")
        if not js:
            checks["definition shown as text"] = "a*sin(x)" in (
                page.locator("pre.graph-spec").inner_text()
            )
            checks["nothing drawn"] = page.locator(".graph-board").count() == 0
        else:
            checks["board drawn"] = page.locator(".graph-board svg").count() == 1
            d = curve_d(page)
            checks["a curve is in the board"] = len(d) > 200
            checks["the point is in the board"] = (
                page.locator(".graph-board svg circle, .graph-board svg ellipse").count() >= 1
            )
            checks["one slider, named"] = page.locator(
                ".graph-slider input[type=range]"
            ).count() == 1 and (page.locator(".graph-slider-name").inner_text() == "a")
            checks["definition text hidden while drawn"] = not page.locator(
                "pre.graph-spec"
            ).is_visible()
            checks["the point's name is SVG text, not an HTML label"] = (
                page.locator(".graph-board svg text", has_text="P").count() >= 1
                and page.locator(".graph-board .JXGtext").count() == 0
            )
            checks["JessieCode compile is off"] = page.evaluate(
                "() => window.JXG.Options.jc.compile === false"
            )
            slider = page.locator(".graph-slider input[type=range]")
            slider.fill("3")
            page.wait_for_timeout(300)
            d2 = curve_d(page)
            checks["moving the slider changes the curve"] = bool(d) and d2 != d
            checks["the slider shows its value"] = (
                page.locator(".graph-slider output").inner_text() == "3"
            )
            # a gesture on the board is not a request to edit
            page.locator(".graph-board").click(position={"x": 60, "y": 60})
            page.wait_for_timeout(500)
            checks["clicking the board does not open the editor"] = (
                page.locator("form.chapter-edit-form").count() == 0
            )
            if shots:
                page.screenshot(path=str(Path(shots) / "graph-dark.png"), full_page=False)
            page.locator(".graph-source-caption").click()
            page.wait_for_selector("form.chapter-edit-form", timeout=4000)
            checks["clicking beside the board opens the editor"] = True
            checks["no CSP violation"] = page.evaluate("() => window.__csp.length") == 0
            checks["no console error or uncaught error"] = not problems

            # hostile text: nothing becomes markup, nothing runs
            page.goto(f"{base}/notes/{hostile}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)
            checks["hostile comment: still drawn"] = page.locator(".graph-board svg").count() == 1
            checks["hostile comment: nothing ran"] = page.evaluate(
                "() => window.__pwned === undefined"
            )
            checks["hostile comment: no injected element"] = (
                page.locator(".graph-block-display img, .graph-block-display script").count() == 0
            )
            checks["hostile comment: no CSP violation"] = (
                page.evaluate("() => window.__csp.length") == 0
            )

            # a definition with errors draws nothing and says which lines
            page.goto(f"{base}/notes/{broken}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)
            errs = page.locator(".graph-errors li").all_inner_texts()
            checks["broken definition: errors by line"] = len(errs) == 2 and errs[0].startswith(
                "line 1:"
            )
            checks["broken definition: nothing drawn"] = page.locator(".graph-board").count() == 0
            checks["broken definition: its text stays"] = page.locator(
                "pre.graph-spec"
            ).is_visible()
    finally:
        for nid in (good, hostile, broken):
            ctx.request.delete(f"{base}/api/notes/{nid}")
        browser.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", help="directory for a screenshot of the drawn board")
    args = ap.parse_args()
    worst = 0
    with sync_playwright() as p:
        for js in (False, True):
            r = drive(p, args.base, js, args.shots)
            print(
                f"\n== arm: {'JS on ' if js else 'JS off'}  (page scripts ran: {r['scripts_ran']})"
            )
            for name, ok in r["checks"].items():
                print(f"  {name:48s} {'OK' if ok else 'FAIL'}")
            drew = r["checks"].get("board drawn", not js)
            if r["scripts_ran"] != js or not drew or len(r["checks"]) < (2 if not js else 16):
                print("  VERDICT: VACUOUS; no pass or fail is reported for this arm")
                worst = max(worst, 2)
                continue
            failed = [n for n, ok in r["checks"].items() if not ok]
            print(f"  VERDICT: {'FAIL ' + ', '.join(failed) if failed else 'PASS'}")
            worst = max(worst, 1 if failed else 0)
    return worst


if __name__ == "__main__":
    sys.exit(main())
