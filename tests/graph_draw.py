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

from playwright.sync_api import TimeoutError as PlaywrightTimeout
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
# short, valid, and a second of work per depth level for JSXGraph's adaptive sampling
SLOW = "view 2d  x -5..5  y -3..3\nf(x) = sin(1000000*x)\ng(x) = sin(1/(x^3))\n"
# 40 blocks that are each cheap; and one block with eight hundred functions beside a cheap one
CHEAP = "f(x) = sin(x)\n"
MANY = [CHEAP] * 40
HEAVY = "".join(f"f{i}(x) = sin(x + {i})\n" for i in range(800))
HEAVY_AND_CHEAP = [HEAVY, "a = slider(0, 3, value 1)\ng(x) = a*sin(x)\n"]
CURVE = "a = slider(1, 4, value 2)\nc(t) = (2*cos(a*t), 2*sin(t)), t in 0..2*pi\nP = (2, 0)\n"
# 24 parametric circles: they all fit one update's allowance, and all are drawn; the slider
# moves them, and each move is an update (a redraw of every curve)
CIRCLES = "a = slider(0.5, 2, step 0.1, value 1)\n" + "".join(
    f"c{i}(t) = (cos(t) + a*{i / 10}, sin(t)), t in 0..2*pi\n" for i in range(24)
)
# 12 functions and 14 circles: 26 curves, the first 24 in the order of the definition
NAMED = "".join(f"f{i}(x) = sin(x + {i})\n" for i in range(12)) + "".join(
    f"c{i}(t) = (cos(t) + {i / 10}, sin(t)), t in 0..2*pi\n" for i in range(14)
)
LONG_TASKS = (
    "window.__long = 0; new PerformanceObserver((l) => l.getEntries().forEach("
    "(e) => { window.__long += e.duration; })).observe({ type: 'longtask', buffered: true });"
)
# The limit is in units of UNIT_JS, timed in the same page: how long the box takes for a fixed
# piece of plain work, so a loaded box and an idle one are judged alike (an absolute 3000 ms
# failed once at CPU PSI 55-73). Measured here (unit about 500 ms, PSI 40): bounded, the
# sampling definition is 0.4-0.6 units and 800 functions 1.7-2.5; with the bound removed they
# are 14.6 and 14.0 (8 to 12 s and 5 s before the bounds). 8 is between.
LONG_TASK_LIMIT_UNITS = 8


def make_note(ctx, base, title, spec, unchecked=False):
    """Create a note holding one graph block. The API refuses a definition with errors;
    an import does not check (a stored one gets in that way), which is how a broken
    one is made here."""
    specs = [spec] if isinstance(spec, str) else spec
    chapters = [{"id": "ch", "title": "Top", "order": 0, "type": "chapter"}] + [
        {
            "id": f"g{i}",
            "title": "",
            "order": i,
            "type": "graph",
            "parent_id": "ch",
            "content": text,
        }
        for i, text in enumerate(specs)
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


# A fixed piece of plain work, timed in the page being judged: how fast this box is right
# now. A limit in units of it holds on a loaded box and on an idle one (20261028-084 1b).
UNIT_JS = (
    "() => { const t = performance.now(); let s = 0;"
    " for (let i = 0; i < 2e7; i++) s += Math.sin(i); return performance.now() - t + (s > 1e9 ? 1 : 0); }"
)


def unit_ms(page):
    """The median of three timings of UNIT_JS."""
    return sorted(page.evaluate(UNIT_JS) for _ in range(3))[1]


def check_sampling_is_bounded(browser, base, note):
    """Two short definitions that took JSXGraph 8 to 12 s of long tasks each."""
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    page.add_init_script(LONG_TASKS)
    try:
        page.goto(f"{base}/")
        unit = unit_ms(page)
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=30000)
        page.wait_for_timeout(1500)
        drawn = page.evaluate("() => window.__long")
        # a pan is a redraw of the same curves
        box = page.locator(".graph-board").bounding_box()
        page.mouse.move(box["x"] + 100, box["y"] + 100)
        page.mouse.down()
        page.mouse.move(box["x"] + 160, box["y"] + 130, steps=6)
        page.mouse.up()
        page.wait_for_timeout(1000)
        total = page.evaluate("() => window.__long")
    finally:
        ctx.close()
    print(
        f"  (long tasks: {drawn:.0f} ms drawing, {total:.0f} ms with a pan; unit {unit:.0f} ms, ratio {total / unit:.1f})"
    )
    return {
        f"sampling is bounded: long tasks under {LONG_TASK_LIMIT_UNITS} units of work": total
        < LONG_TASK_LIMIT_UNITS * unit
    }


def check_a_parametric_curve(browser, base, note):
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    problems = []
    page.on(
        "console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None
    )
    page.on("pageerror", lambda e: problems.append(str(e)))
    try:
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=15000)
        page.wait_for_timeout(800)
        before = curve_d(page)
        page.locator(".graph-slider input[type=range]").fill("3")
        page.wait_for_timeout(500)
        after = curve_d(page)
        label = page.locator(".graph-board").get_attribute("aria-label") or ""
    finally:
        ctx.close()
    return {
        "a parametric curve is drawn": len(before) > 200,
        "moving the slider changes the parametric curve": bool(before) and after != before,
        "a parametric curve: no console error": not problems,
        "a parametric curve is named in the board's label": label.startswith("Graph of c"),
    }


def hints(page):
    return page.evaluate(
        "() => [...document.querySelectorAll('.graph-hint')].map((h) => h.textContent)"
    )


def left_out(texts):
    return [t for t in texts if "left out" in t or "Only the first" in t]


def check_each_board_says_its_own_limits(browser, base, many, mixed):
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    page.add_init_script(LONG_TASKS)
    try:
        page.goto(f"{base}/")
        unit = unit_ms(page)
        page.goto(f"{base}/notes/{many}")
        page.wait_for_function(
            "() => document.querySelectorAll('.graph-board svg').length === 40", timeout=30000
        )
        page.wait_for_timeout(1000)
        many_said = left_out(hints(page))
        many_drawn = page.evaluate(
            "() => [...document.querySelectorAll('.graph-board')]"
            ".filter((b) => b.querySelectorAll('svg path').length > 4).length"
        )

        page.goto(f"{base}/notes/{mixed}")
        page.wait_for_function(
            "() => document.querySelectorAll('.graph-board svg').length === 2", timeout=30000
        )
        page.wait_for_timeout(1000)
        loaded = page.evaluate("() => window.__long")
        first = hints(page)
        # pan the heavy board, then move the cheap board's slider
        box = page.locator(".graph-board").first.bounding_box()
        page.mouse.move(box["x"] + 100, box["y"] + 100)
        page.mouse.down()
        page.mouse.move(box["x"] + 160, box["y"] + 130, steps=6)
        page.mouse.up()
        page.wait_for_timeout(800)
        page.locator(".graph-slider input[type=range]").fill("2")
        page.wait_for_timeout(800)
        after = hints(page)
        total = page.evaluate("() => window.__long")
    finally:
        ctx.close()
    print(
        f"  (heavy block: long tasks {loaded:.0f} ms on load, {total:.0f} ms with a pan; unit {unit:.0f} ms, ratio {total / unit:.1f})"
    )
    return {
        "40 cheap blocks: no board says it left something out": many_said == []
        and many_drawn == 40,
        "800 functions: only that board says so, and how many": len(left_out(first)) == 1
        and "first 24 of 800" in first[0]
        and left_out(after) == left_out(first)
        and "first 24 of 800" in after[0],
        f"800 functions: long tasks under {LONG_TASK_LIMIT_UNITS} units of work": total
        < LONG_TASK_LIMIT_UNITS * unit,
    }


# the colour of a path, as the browser computes it, so a hex and an rgb() compare (this text
# is put in front of a script: the page's policy forbids eval)
NORM = (
    "const norm = (c) => { const e = document.createElement('i'); e.style.color = c;"
    " document.body.append(e); const v = getComputedStyle(e).color; e.remove(); return v; };"
)


def stroke_colors(page):
    """Per board: the set of its path strokes, normalised."""
    return page.evaluate(
        "() => { " + NORM + " return [...document.querySelectorAll('.graph-board')]"
        ".map((b) => [...new Set([...b.querySelectorAll('svg path')]"
        ".map((p) => p.getAttribute('stroke')).filter(Boolean).map(norm))]); }"
    )


def check_a_theme_change_while_drawing(browser, base, many):
    """The palette is read for each board, not once before the drawing loop yields."""
    ctx = browser.new_context(viewport={"width": 900, "height": 900}, color_scheme="dark")
    page = ctx.new_page()
    try:
        # the premise, on a page with no board (flipping the theme redraws every board): the
        # two themes have different accents, so a board drawn with the old palette is seen
        page.goto(f"{base}/")
        accents = page.evaluate(
            "() => { " + NORM + " const r = document.documentElement; const out = {};"
            " for (const t of ['light', 'dark']) { r.dataset.theme = t;"
            " out[t] = norm(getComputedStyle(r).getPropertyValue('--accent').trim() || 'rgb(0,0,0)'); }"
            " return out; }"
        )
        page.goto(f"{base}/notes/{many}")
        page.wait_for_function(
            "() => document.querySelectorAll('.graph-board svg').length >= 1", timeout=30000
        )
        page.evaluate("() => { document.documentElement.dataset.theme = 'light'; }")
        page.wait_for_function(
            "() => document.querySelectorAll('.graph-board svg').length === 40", timeout=30000
        )
        page.wait_for_timeout(1500)
        light = page.evaluate(
            "() => { " + NORM + " return norm(getComputedStyle(document.documentElement)"
            ".getPropertyValue('--accent').trim()); }"
        )
        colors = stroke_colors(page)
    finally:
        ctx.close()
    with_light = sum(1 for c in colors if light in c)
    return {
        "theme: the light and dark accents differ (the premise)": accents["light"]
        != accents["dark"],
        f"theme: all 40 boards use the new theme's accent ({with_light} of {len(colors)})": len(
            colors
        )
        == 40
        and with_light == 40,
    }


def check_the_curve_cap_and_its_hint(browser, base, circles, named):
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    try:
        page.goto(f"{base}/notes/{circles}")
        page.wait_for_selector(".graph-board svg", timeout=30000)
        page.wait_for_timeout(1500)
        circles_hint = hints(page)
        circle_paths = page.evaluate(
            "() => { const b = document.querySelector('.graph-board');"
            " const w = [...b.querySelectorAll('svg path')].filter((p) => p.getAttribute('stroke-width') === '2px');"
            " return w.length; }"
        )
        # every slider move is an update with a fresh allowance: after six of them (24,600
        # evaluations each, 147,600 in all) the circles are still drawn, and nothing says "too
        # much work" (without the 'update' settle the allowance runs out at the third)
        last_d = (
            "() => { const ps = [...document.querySelectorAll('.graph-board svg path')]"
            ".filter((p) => p.getAttribute('stroke-width') === '2px'); return ps.at(-1).getAttribute('d'); }"
        )
        first_d = page.evaluate(last_d)
        for value in ("0.6", "0.8", "1.1", "1.4", "1.7", "2"):
            page.locator(".graph-slider input[type=range]").fill(value)
            page.wait_for_timeout(400)
        after_moves = hints(page)
        moved_d = page.evaluate(last_d)
        still_drawn = page.evaluate(
            "() => [...document.querySelectorAll('.graph-board svg path')]"
            ".filter((p) => p.getAttribute('stroke-width') === '2px' && (p.getAttribute('d') || '').length > 100).length"
        )
        page.goto(f"{base}/notes/{named}")
        page.wait_for_selector(".graph-board svg", timeout=30000)
        page.wait_for_timeout(1500)
        named_hint = hints(page)
    finally:
        ctx.close()
    return {
        "curves: 24 parametric circles are all drawn, and the hint says nothing": circles_hint
        and left_out(circles_hint) == []
        and circle_paths >= 24,
        "curves: 26 curves say which two are left out, in the order of the definition": len(
            left_out(named_hint)
        )
        == 1
        and "first 24 of 26" in named_hint[0]
        and "left out: c12, c13." in named_hint[0]
        and "functions, then curves" in named_hint[0],
        "update: after six slider moves the 24 circles are still drawn and nothing is left out": still_drawn
        >= 24
        and left_out(after_moves) == []
        and moved_d != first_d,  # the last circle followed the slider: it was redrawn, not frozen
    }


def check_one_finger_scrolls(browser, base, note):
    """On a phone one finger on a board scrolls the page. JSXGraph writes touch-action: none
    into the element's style on init and on every pointerdown; the stylesheet must win."""
    ctx = browser.new_context(
        viewport={"width": 390, "height": 760}, has_touch=True, is_mobile=True, color_scheme="dark"
    )
    page = ctx.new_page()
    try:
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=15000)
        page.wait_for_timeout(500)
        # The scrolling box is the nearest ancestor that scrolls (the page may keep its own
        # panes); make it long enough to scroll whatever else is on it.
        page.evaluate(
            """() => {
              let n = document.querySelector('.graph-board').parentElement;
              while (n && !/auto|scroll/.test(getComputedStyle(n).overflowY)) n = n.parentElement;
              window.__scroller = n || document.scrollingElement;
              const d = document.createElement('div');
              d.style.height = '3000px';
              (n || document.body).append(d);
              window.__scroller.scrollTop = 0;
            }"""
        )

        def touch():
            return page.evaluate(
                "() => getComputedStyle(document.querySelector('.graph-board')).touchAction"
            )

        def scroll_top():
            return page.evaluate("() => window.__scroller.scrollTop")

        before = touch()
        board = page.locator(".graph-board")
        board.scroll_into_view_if_needed()
        box = board.bounding_box()
        cdp = ctx.new_cdp_session(page)

        def swipe(x, y, dy=-250, steps=10):
            """One finger, moving up: it starts at (x, y) and the page should follow it."""
            start = scroll_top()
            touch_at = lambda kind, ys: cdp.send(  # noqa: E731
                "Input.dispatchTouchEvent",
                {"type": kind, "touchPoints": [{"x": x, "y": ys}] if ys is not None else []},
            )
            touch_at("touchStart", y)
            for i in range(1, steps + 1):
                touch_at("touchMove", y + dy * i / steps)
                page.wait_for_timeout(16)
            touch_at("touchEnd", None)
            page.wait_for_timeout(600)
            return scroll_top() - start

        scrolled = swipe(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 + 60)
        after = touch()
        wide = box["width"]
        page.evaluate("() => { window.__scroller.scrollTop = 0; }")
        beside = swipe(200, 100)  # on the heading above the board: the swipe itself can scroll
    finally:
        ctx.close()
    print(
        f"  (phone: touch-action {before} -> {after} after a touch; scrolled {scrolled:.0f} px from the board; board {wide:.0f} px wide)"
    )
    return {
        "phone: the board's touch-action stays pan-y after a touch": before == after == "pan-y",
        "phone: harness control, a swipe beside the board scrolls the page": beside > 100,
        "phone: one finger on the board scrolls the page": scrolled > 100,
    }


def check_a_swap_during_the_load(browser, base, note):
    """A graph that arrives (an htmx swap) while JSXGraph is still loading is drawn when it has loaded."""
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    held = []
    warned = []

    def hold(route):
        held.append(route)

    page.route("**/jsxgraphcore.js", hold)
    page.on("console", lambda m: warned.append(m.text) if m.type == "warning" else None)
    try:
        page.goto(f"{base}/notes/{note}", wait_until="domcontentloaded")
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(100)
        page.evaluate(
            "() => { const f = document.querySelector('.graph-block-display');"
            " f.insertAdjacentHTML('afterend', f.outerHTML);"
            " htmx.trigger(document.body, 'htmx:afterSwap', {});"
            # a third graph that arrives and is swapped away again before the library is here
            " f.insertAdjacentHTML('afterend', f.outerHTML);"
            " htmx.trigger(document.body, 'htmx:afterSwap', {});"
            " f.nextElementSibling.remove(); }"
        )
        page.wait_for_timeout(500)
        held_script = bool(held)
        if held:
            held[0].continue_()
        page.wait_for_timeout(2500)
        boards = page.locator(".graph-board svg").count()
        known = page.evaluate("() => Object.keys(window.JXG.boards).length")
    finally:
        ctx.close()
    return {
        "a swap during the library load: both graphs are drawn": held_script
        and boards == 2
        and known == 2  # none drawn into a figure that had left the page
        and not warned,
    }


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
    slow = make_note(ctx, base, f"Graph slow {stamp}", SLOW)
    many = make_note(ctx, base, f"Graph many {stamp}", MANY)
    mixed = make_note(ctx, base, f"Graph mixed {stamp}", HEAVY_AND_CHEAP)
    curve = make_note(ctx, base, f"Graph curve {stamp}", CURVE)
    circles = make_note(ctx, base, f"Graph circles {stamp}", CIRCLES)
    named = make_note(ctx, base, f"Graph named {stamp}", NAMED)
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
                and page.locator(".graph-board div.JXGtext").count() == 0
            )
            checks["the board takes the page's palette (--field, --border)"] = page.evaluate(
                """() => {
                  const probe = document.createElement('div');
                  probe.style.cssText = 'background-color: var(--field); border: 1px solid var(--border)';
                  document.body.append(probe);
                  const want = getComputedStyle(probe);
                  const got = getComputedStyle(document.querySelector('.graph-board'));
                  const same = want.backgroundColor === got.backgroundColor
                    && want.borderTopColor === got.borderTopColor;
                  probe.remove();
                  return same;
                }"""
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
            opened = page.locator("form.chapter-edit-form").count() != 0
            checks["clicking the board does not open the editor"] = not opened
            if opened:  # a failed check must not stop the run: back to the page
                page.goto(f"{base}/notes/{good}")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)
            if shots:
                page.screenshot(path=str(Path(shots) / "graph-dark.png"), full_page=False)
            page.locator(".graph-source-caption").click()
            try:
                page.wait_for_selector("form.chapter-edit-form", timeout=4000)
            except PlaywrightTimeout:
                pass
            checks["clicking beside the board opens the editor"] = (
                page.locator("form.chapter-edit-form").count() == 1
            )
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
            # the server sends a list too; the one the script made carries data-drawn
            checks["broken definition: errors by line (made by the script)"] = (
                len(errs) == 2
                and errs[0].startswith("line 1:")
                and page.locator('.graph-errors[data-drawn="script"] li').count() == 2
                and page.locator(".graph-errors").count() == 1
            )
            checks["broken definition: nothing drawn"] = page.locator(".graph-board").count() == 0
            checks["broken definition: its text stays"] = page.locator(
                "pre.graph-spec"
            ).is_visible()
            checks.update(check_sampling_is_bounded(browser, base, slow))
            checks.update(check_a_parametric_curve(browser, base, curve))
            checks.update(check_each_board_says_its_own_limits(browser, base, many, mixed))
            checks.update(check_a_theme_change_while_drawing(browser, base, many))
            checks.update(check_the_curve_cap_and_its_hint(browser, base, circles, named))
            checks.update(check_one_finger_scrolls(browser, base, good))
            checks.update(check_a_swap_during_the_load(browser, base, good))
    finally:
        for nid in (good, hostile, broken, slow, many, mixed, curve, circles, named):
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
            if r["scripts_ran"] != js or not drew or len(r["checks"]) < (2 if not js else 20):
                print("  VERDICT: VACUOUS; no pass or fail is reported for this arm")
                worst = max(worst, 2)
                continue
            failed = [n for n, ok in r["checks"].items() if not ok]
            print(f"  VERDICT: {'FAIL ' + ', '.join(failed) if failed else 'PASS'}")
            worst = max(worst, 1 if failed else 0)
    return worst


if __name__ == "__main__":
    sys.exit(main())
