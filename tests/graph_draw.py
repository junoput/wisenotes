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
from itertools import pairwise
from pathlib import Path
from urllib.parse import parse_qs

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
PLAY = "view 2d  x -4..4  y -3..3\na = slider(0, 5, value 1, play)\nf(x) = a*sin(x)\n"
# play beside enough other blocks that the page scrolls and the board can be off the screen
PLAY_TALL = [PLAY, *[CHEAP] * 30]
# a board that is slow to redraw: 24 curves that all move with the playing slider
PLAY_HEAVY = "a = slider(0, 6, value 0, play)\n" + "".join(
    f"f{i}(x) = sin(a*x + {i})\n" for i in range(24)
)
# a slider that ends at 2*pi, and lines with their own spacing that a save must not touch
IRRATIONAL = (
    "view 2d  x -4..4   y -3..3\n"
    "  a  =  slider(0, 2*pi, play)\n"
    "  b = slider( 0 , 5 , value 2 )\n"
    "f(x) = a*sin(x) + b\n"
)
GEOMETRY = (
    "view 2d  x -6..6  y -4..4\n"
    "r = slider(0.5, 6, value 2)\n"
    "P = (-1, 0)\nQ = (3, 1)\nR = (0, 3)\n"
    "s = segment(P, Q)\nc = circle(P, r)\nX = intersection(s, c)\nM = midpoint(P, Q)\n"
    "polygon(P, Q, R)\nl = line(Q, R)\nd = circle(P, Q)\n"
)
# The most a definition may hold (200 statements, 800 polygon corners between them), every
# point moving with the slider: 32 points, 25 polygons of 32 corners, 175 segments.
BIGGEST_GEOMETRY = (
    "a = slider(0, 3, value 1)\n"
    + "".join(f"p{i} = (3*cos({i}) + a*0.1, 3*sin({i}))\n" for i in range(32))
    + "".join(f"polygon({', '.join(f'p{(j + k) % 32}' for j in range(32))})\n" for k in range(25))
    + "".join(f"segment(p{k % 32}, p{(k + 7) % 32})\n" for k in range(175))
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


def board_box(page):
    return page.evaluate("() => Object.values(window.JXG.boards)[0].getBoundingBox()")


def close(got, want, tol=1e-3):
    return all(abs(g - w) <= tol * max(1, abs(w)) for g, w in zip(got, want, strict=True))


def check_the_default_view(browser, base, note, ctx_for_api):
    """Pan, set a slider, save: the page comes back drawn from the new default. Reset goes there."""
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    try:
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=15000)
        page.wait_for_timeout(500)
        first = board_box(page)
        box = page.locator(".graph-board").bounding_box()

        def pan():
            page.mouse.move(box["x"] + 150, box["y"] + 150)
            page.mouse.down()
            page.mouse.move(box["x"] + 230, box["y"] + 190, steps=8)
            page.mouse.up()
            page.wait_for_timeout(400)

        pan()
        panned = board_box(page)
        page.locator(".graph-slider input[type=range]").fill("3")
        page.locator(".graph-save").click()
        page.wait_for_function(
            "() => document.querySelector('.graph-board') && !document.querySelector('.graph-status')?.textContent",
            timeout=10000,
        )
        page.wait_for_timeout(1000)
        saved_box = board_box(page)
        saved_value = page.locator(".graph-slider output").inner_text()
        stored = ctx_for_api.request.get(
            f"{base}/notes/{note}/chapters/g0/edit", headers={"HX-Request": "true"}
        ).text()
        # a reload draws the saved view too
        page.reload()
        page.wait_for_selector(".graph-board svg", timeout=15000)
        page.wait_for_timeout(500)
        reloaded = board_box(page)
        reloaded_value = page.locator(".graph-slider output").inner_text()
        # move away, then reset
        pan()
        page.locator(".graph-slider input[type=range]").fill("1")
        away = board_box(page)
        page.locator(".graph-reset").click()
        page.wait_for_timeout(300)
        back = board_box(page)
        back_value = page.locator(".graph-slider output").inner_text()
    finally:
        ctx.close()
    return {
        "view: panning moved the box": not close(panned, first),
        "view: Save view draws the page again from the saved box": close(saved_box, panned, 1e-3),
        "view: the saved slider value is shown": saved_value == "3",
        "view: the definition now holds the view line": "view 2d  x " in stored,
        "view: a reload draws the saved box": close(reloaded, panned, 1e-3),
        "view: a reload shows the saved slider value": reloaded_value == "3",
        "view: Reset view goes back to the saved box": close(back, panned, 1e-3)
        and not close(away, panned),
        "view: Reset view goes back to the saved slider value": back_value == "3",
    }


def check_a_refused_save_says_so(browser, base, note):
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    try:
        page.route(
            "**/graph-view",
            lambda route: route.fulfill(
                status=400, content_type="text/plain", body="the x range must be finite"
            ),
        )
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=15000)
        page.locator(".graph-save").click()
        page.wait_for_function(
            "() => /Not saved/.test(document.querySelector('.graph-status').textContent)",
            timeout=5000,
        )
        said = page.locator(".graph-status").inner_text()
        still_drawn = page.locator(".graph-board svg").count() == 1
    finally:
        ctx.close()
    return {
        "view: a refused save says why and leaves the board": "x range must be finite" in said
        and still_drawn
    }


def check_play(browser, base, note):
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    reduced = browser.new_context(viewport={"width": 900, "height": 900}, reduced_motion="reduce")
    rpage = reduced.new_page()
    try:
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=15000)
        out = lambda: float(page.locator(".graph-slider output").inner_text())  # noqa: E731
        start = out()
        page.locator(".graph-play").click()
        page.wait_for_timeout(1200)
        playing = out()
        pressed = page.locator(".graph-play").get_attribute("aria-pressed")
        page.locator(".graph-play").click()
        page.wait_for_timeout(300)
        paused_at = out()
        page.wait_for_timeout(500)
        still = out()
        # it bounces: over 9 s of play the value has been seen going up and down
        page.locator(".graph-play").click()
        seen = []
        for _ in range(20):
            page.wait_for_timeout(450)
            seen.append(out())
        page.locator(".graph-play").click()
        ups = sum(1 for a, b in pairwise(seen) if b > a)
        downs = sum(1 for a, b in pairwise(seen) if b < a)
        # touching the slider takes over
        page.locator(".graph-play").click()
        page.wait_for_timeout(300)
        page.locator(".graph-slider input[type=range]").focus()
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(200)
        taken = out()
        page.wait_for_timeout(500)
        taken_later = out()
        rpage.goto(f"{base}/notes/{note}")
        rpage.wait_for_selector(".graph-board svg", timeout=15000)
        offered = rpage.locator(".graph-play").count()
        slider_there = rpage.locator(".graph-slider input[type=range]").count()
    finally:
        ctx.close()
        reduced.close()
    return {
        "play: the slider moves and the button says it is pressed": playing != start
        and pressed == "true",
        "play: pausing holds the value": paused_at == still,
        "play: it bounces": ups > 0 and downs > 0,
        "play: touching the slider takes over": taken == taken_later,
        "play: reduced motion offers no play button, and keeps the slider": offered == 0
        and slider_there == 1,
    }


def check_play_waits_when_it_cannot_be_seen(browser, base, note):
    ctx = browser.new_context(viewport={"width": 900, "height": 700})
    page = ctx.new_page()
    try:
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=15000)
        page.wait_for_timeout(500)
        out = lambda: float(page.locator(".graph-slider output").inner_text())  # noqa: E731
        pressed = lambda: page.locator(".graph-play").get_attribute("aria-pressed")  # noqa: E731
        start = out()
        page.locator(".graph-play").click()
        page.wait_for_timeout(700)
        on_screen = out()
        # scroll the last block into view: the board is off the screen
        page.evaluate(
            "() => [...document.querySelectorAll('section.chapter-section')].at(-1).scrollIntoView()"
        )
        page.wait_for_timeout(600)
        really_away = page.evaluate(
            "() => document.querySelector('.graph-board').getBoundingClientRect().bottom < 0"
        )
        away_1 = out()
        page.wait_for_timeout(700)
        away_2 = out()
        still_wanted = pressed() == "true"
        page.evaluate("() => document.querySelector('.graph-board').scrollIntoView()")
        page.wait_for_timeout(700)
        back = out()
        # a tab that is hidden: the page says so
        page.evaluate(
            "() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });"
            " document.dispatchEvent(new Event('visibilitychange')); }"
        )
        page.wait_for_timeout(500)
        hidden_1 = out()
        page.wait_for_timeout(700)
        hidden_2 = out()
        page.evaluate(
            "() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); }"
        )
        page.wait_for_timeout(700)
        shown_again = out()
        page.locator(".graph-play").click()
    finally:
        ctx.close()
    return {
        "play: it moves while the board is on the screen": on_screen != start,
        "play: the board is really off the screen (the premise)": really_away,
        "play: it stops drawing while the board is off the screen": away_1 == away_2,
        "play: off the screen it is still wanted (the button stays pressed)": still_wanted,
        "play: it goes on when the board is back": back != away_2,
        "play: it stops drawing while the tab is hidden": hidden_1 == hidden_2,
        "play: it goes on when the tab is shown again": shown_again != hidden_2,
    }


def check_play_leaves_the_page_usable(browser, base, note):
    """A board that is slow to redraw is redrawn at its own pace: the pacing aims at half of
    the main thread's time (49% measured here on a quiet machine, 56% on a loaded one), the
    layout and paint after each redraw included. The limit is 70%: back to back it is 99%.

    The probe is the share of wall time the page's main thread spends in tasks while the
    play runs (CDP TaskDuration over Timestamp). It is a ratio, so a loaded machine slows
    the redraws and the pacing together; a count of timer ticks was not (it passed one run
    by 2 ticks)."""
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    try:
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=15000)
        page.wait_for_timeout(500)
        cost = page.evaluate(
            "() => { const b = Object.values(window.JXG.boards)[0]; b.fullUpdate();"
            " const t = performance.now(); for (let i = 0; i < 5; i++) b.fullUpdate();"
            " return (performance.now() - t) / 5; }"
        )
        page.evaluate(
            "() => { window.__updates = 0;"
            " Object.values(window.JXG.boards)[0].on('update', () => { window.__updates++; }); }"
        )
        cdp = ctx.new_cdp_session(page)
        cdp.send("Performance.enable")

        def busy(ms):
            """(share of the time the main thread was busy, redraws) over the next `ms`."""

            def read():
                m = {x["name"]: x["value"] for x in cdp.send("Performance.getMetrics")["metrics"]}
                return m["TaskDuration"], m["Timestamp"], page.evaluate("() => window.__updates")

            t0, w0, u0 = read()
            page.wait_for_timeout(ms)
            t1, w1, u1 = read()
            return (t1 - t0) / (w1 - w0), u1 - u0

        idle, _ = busy(1500)
        page.locator(".graph-play").click()
        page.wait_for_timeout(300)
        moved_1 = page.locator(".graph-slider output").inner_text()
        playing, redraws = busy(3000)
        moved_2 = page.locator(".graph-slider output").inner_text()
        page.locator(".graph-play").click()
    finally:
        ctx.close()
    return {
        # the premise: one redraw is slow enough that back-to-back frames would starve the page,
        # and the instrument sees the page idle when nothing plays
        f"play: the heavy board takes real work per redraw ({cost:.0f} ms)": cost >= 15,
        f"play: the page is idle when nothing plays ({idle:.0%} busy)": idle < 0.1,
        "play: the heavy board still plays": moved_1 != moved_2 and redraws >= 5,
        f"play: the page is not pinned ({playing:.0%} busy, {redraws} redraws in 3 s)": playing
        <= 0.7,
    }


WATCH_OBSERVERS = """
window.__watch = { made: 0, gone: 0, listeners: 0 };
const IO = window.IntersectionObserver;
window.IntersectionObserver = class extends IO {  // only those that watch a graph board
  observe(target) {
    if (target.classList && target.classList.contains('graph-board')) { this.board = true; window.__watch.made++; }
    return super.observe(target);
  }
  disconnect() { if (this.board) window.__watch.gone++; super.disconnect(); }
};
const addListener = document.addEventListener.bind(document);
const removeListener = document.removeEventListener.bind(document);
document.addEventListener = (type, ...rest) => {
  if (type === 'visibilitychange') window.__watch.listeners++;
  return addListener(type, ...rest);
};
document.removeEventListener = (type, ...rest) => {
  if (type === 'visibilitychange') window.__watch.listeners--;
  return removeListener(type, ...rest);
};
"""


def check_a_board_that_fails_to_draw_leaves_nothing_watching(browser, base, note):
    """The board watches whether it can be seen from before it is drawn. If drawing then
    fails (here: the library throws when it makes the board), the observer and the document
    listener must go with the board that never was."""
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    page.add_init_script(WATCH_OBSERVERS)
    warnings = []
    page.on("console", lambda m: warnings.append(m.text) if m.type == "warning" else None)

    def break_the_library(route):
        response = route.fetch()
        route.fulfill(
            response=response,
            body=response.text()
            + "\n;window.JXG.JSXGraph.initBoard = () => { throw new Error('the library fails'); };",
        )

    try:
        page.goto(f"{base}/")  # a page with no board: the listeners the page has of its own
        page.wait_for_load_state("networkidle")
        baseline = page.evaluate("() => window.__watch.listeners")
        page.route("**/jsxgraphcore.js", break_the_library)
        page.goto(f"{base}/notes/{note}")
        page.wait_for_function(
            "() => window.__watch.made >= 1 && window.JXG && document.querySelector('.graph-block-display')",
            timeout=15000,
        )
        page.wait_for_timeout(800)
        watch = page.evaluate("() => window.__watch")
        broke = page.evaluate("() => window.JXG.JSXGraph.initBoard.toString()")
        shown = page.locator("pre.graph-spec").is_visible()
        live = page.locator(".graph-live, .graph-board").count()
    finally:
        ctx.close()
    return {
        "failed draw: the library was broken as intended (the premise)": "the library fails"
        in broke
        and any("graph block not drawn" in w for w in warnings),
        f"failed draw: a board was being watched ({watch['made']} observer made)": watch["made"]
        >= 1,
        f"failed draw: every observer was disconnected ({watch['gone']} of {watch['made']})": watch[
            "gone"
        ]
        == watch["made"],
        "failed draw: no visibilitychange listener is left behind": watch["listeners"] == baseline,
        "failed draw: nothing of the board stays, the definition is shown": live == 0 and shown,
    }


def check_saving_at_an_irrational_end(browser, base, note, ctx_for_api):
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    sent = []
    try:
        page.route(
            "**/graph-view",
            lambda route: (sent.append(route.request.post_data), route.continue_())[1],
        )
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=15000)
        page.wait_for_timeout(500)
        # drag the thumb of a to the right end, as a person does
        slider = page.locator(".graph-slider input[type=range]").first
        box = slider.bounding_box()
        page.mouse.move(box["x"] + 5, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] + 40, box["y"] + box["height"] / 2, steps=6)
        page.mouse.up()
        value = slider.input_value()
        page.locator(".graph-save").click()
        page.wait_for_timeout(1500)
        status = (
            page.locator(".graph-status").inner_text()
            if page.locator(".graph-status").count()
            else ""
        )
        stored = ctx_for_api.request.get(
            f"{base}/notes/{note}/chapters/g0/edit", headers={"HX-Request": "true"}
        ).text()
    finally:
        ctx.close()
    body = sent[0] if sent else ""
    return {
        f"save: the thumb is at the right end, 2*pi ({value}) (the premise)": abs(
            float(value) - 2 * 3.141592653589793
        )
        < 1e-6,
        "save: a slider dragged to an irrational end saves": bool(sent)
        and "Not saved" not in status
        and "a  =  slider(0, 2*pi, play, value 6.28318530717" in stored.replace("&#39;", "'"),
        "save: only the slider that changed is sent": "slider=a%3D" in body
        and "slider=b" not in body,
        "save: the lines that did not change keep their spacing": "  b = slider( 0 , 5 , value 2 )"
        in stored,
    }


ELEMENTS = """() => {
  const board = Object.values(JXG.boards)[0];
  const live = (e) => e.isReal && e.visPropCalc.visible;
  const kinds = {};
  for (const e of board.objectsList) if (live(e) && !['text', 'label', 'axis', 'ticks', 'grid', 'sketchcurve', 'curve'].includes(e.elType)) {
    kinds[e.elType] = (kinds[e.elType] ?? 0) + 1;
  }
  const named = {};
  for (const e of board.objectsList) if (e.elType === 'point' && ['X', 'M', 'P', 'Q', 'R'].includes(e.name)) {
    named[e.name] = live(e) ? [e.X(), e.Y()] : null;
  }
  const circles = board.objectsList.filter((e) => e.elType === 'circle' && live(e)).map((c) => [c.Radius(), Number(c.rendNode?.getAttribute('rx') ?? 0), Number(c.rendNode?.getAttribute('ry') ?? -1)]);
  return { kinds, named, circles };
}"""


def check_geometry(browser, base, note):
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
        first = page.evaluate(ELEMENTS)
        page.locator(".graph-slider input[type=range]").fill(
            "5.5"
        )  # the circle swallows the segment
        page.wait_for_timeout(500)
        wide = page.evaluate(ELEMENTS)
        page.locator(".graph-slider input[type=range]").fill("3")
        page.wait_for_timeout(500)
        back = page.evaluate(ELEMENTS)
        label = page.locator(".graph-board").get_attribute("aria-label") or ""
    finally:
        ctx.close()
    x = first["named"].get("X")
    px, py = first["named"]["P"]
    on_circle = x is not None and abs(((x[0] - px) ** 2 + (x[1] - py) ** 2) ** 0.5 - 2) < 1e-6
    # on the segment P -> Q = (4, 1) from P: (x - P) is a multiple of it, inside it
    along = x is not None and abs((x[0] - px) * 1 - (x[1] - py) * 4) < 1e-6 and x[0] > px
    return {
        "geometry is drawn: a segment, a line, two circles, a polygon": all(
            first["kinds"].get(k, 0) >= n
            for k, n in (("segment", 1), ("line", 1), ("circle", 2), ("polygon", 1))
        ),
        # P, Q, R, M, X and nothing else: the points a segment or a polygon is built on are not shown
        "geometry: the points of midpoint and intersection are drawn": first["kinds"].get("point")
        == 5
        and first["named"].get("M") is not None
        and x is not None,
        "geometry: a midpoint is halfway": first["named"].get("M") is not None
        and abs(first["named"]["M"][0] - 1) < 1e-9
        and abs(first["named"]["M"][1] - 0.5) < 1e-9,
        "geometry: an intersection is on both the circle and the segment": on_circle and along,
        "geometry: a circle has its radius from the slider": sorted(
            round(r, 6) for r, _, _ in first["circles"]
        )
        == [2.0, round(17**0.5, 6)],
        "geometry: a circle is on the page, and round": len(first["circles"]) == 2
        and all(rx > 5 and abs(rx - ry) < 1 for _, rx, ry in first["circles"]),
        "geometry: a point that no longer exists is not drawn": wide["named"].get("X") is None
        and wide["named"].get("M") is not None,
        "geometry: the circle follows the slider": sorted(
            round(r, 6) for r, _, _ in wide["circles"]
        )
        == [round(17**0.5, 6), 5.5],
        "geometry: the point comes back": back["named"].get("X") is not None,
        "geometry: a construction's name is in the board's label": "M" in label and "X" in label,
        "geometry: no console error": not problems,
    }


ROUND = """() => Object.values(JXG.boards)[0].objectsList
  .filter((e) => e.elType === 'circle' && e.rendNode)
  .map((c) => [Number(c.rendNode.getAttribute('rx')), Number(c.rendNode.getAttribute('ry'))])"""


def round_circles(page):
    """Every circle drawn has one radius on the screen on both axes (and there is one to see)."""
    got = page.evaluate(ROUND)
    return bool(got) and all(rx > 5 and abs(rx - ry) < 0.5 for rx, ry in got)


def check_geometry_view(browser, base, note):
    """Reset view keeps circles round (JSXGraph drops the lock when told `false`), and Save
    view gives back the written box at any width: the box on the screen is wider than the
    written one, and must not be what is written (20261029-051, review)."""
    got = {}
    for width in (900, 600):
        ctx = browser.new_context(viewport={"width": width, "height": 900})
        page = ctx.new_page()
        sent = []

        def keep(route, _request, sent=sent):
            sent.append(parse_qs(route.request.post_data or ""))
            route.fulfill(status=200, content_type="text/plain", body="")

        page.route("**/graph-view", keep)
        try:
            page.goto(f"{base}/notes/{note}")
            page.wait_for_selector(".graph-board svg", timeout=15000)
            page.wait_for_timeout(600)
            page.locator(".graph-save").click()
            page.wait_for_timeout(500)
            at = page.locator(".graph-board").bounding_box()
            page.mouse.move(at["x"] + 150, at["y"] + 100)
            page.mouse.down()
            page.mouse.move(at["x"] + 230, at["y"] + 150, steps=6)
            page.mouse.up()
            page.locator(".graph-reset").click()
            page.wait_for_timeout(500)
            after_reset = round_circles(page)
            page.set_viewport_size({"width": width - 150, "height": 900})
            page.wait_for_timeout(800)
            after_resize = round_circles(page)
            page.locator(".graph-save").click()
            page.wait_for_timeout(500)
            # a zoom, then a save: the box is the written shape, not the screen's
            page.mouse.move(at["x"] + 150, at["y"] + 100)
            page.keyboard.down("Shift")
            page.mouse.wheel(0, -300)
            page.keyboard.up("Shift")
            page.wait_for_timeout(500)
            page.locator(".graph-save").click()
            page.wait_for_timeout(500)
            zoomed_round = round_circles(page)
        finally:
            ctx.close()
        got[width] = (sent, after_reset, after_resize, zoomed_round)

    def box(q):
        return [float(q[k][0]) for k in ("x0", "x1", "y0", "y1")]

    def writes_the_written_box(q):
        return all(abs(a - b) < 0.01 for a, b in zip(box(q), (-6, 6, -4, 4), strict=True))

    saved = {w: [box(q) for q in v[0] if "x0" in q] for w, v in got.items()}
    zoomed = [b for w in saved for b in saved[w][2:3]]
    return {
        "geometry view: Save view without a pan or zoom writes the written box, at 900 and 600 px": all(
            len(got[w][0]) == 3 and writes_the_written_box(got[w][0][0]) for w in (900, 600)
        ),
        "geometry view: a zoomed save keeps the written shape (12 by 8) and has moved the box": len(
            zoomed
        )
        == 2
        and all(
            abs((b[1] - b[0]) / (b[3] - b[2]) - 1.5) < 0.01
            and (b[1] - b[0]) < 11.9
            and abs(b[0] + b[1]) + abs(b[2] + b[3]) > 0.1  # zoomed about a point off the middle
            for b in zoomed
        ),
        "geometry view: circles are round after Reset view": all(got[w][1] for w in got),
        "geometry view: circles are round after a resize": all(got[w][2] for w in got),
        "geometry view: circles are round after a zoom": all(got[w][3] for w in got),
    }


def check_the_biggest_geometry_is_bounded(browser, base, note):
    """The most the parsers admit: it draws, and it does not freeze the page (it took
    7 s of long tasks before the polygon corners were capped in all)."""
    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    page.add_init_script(LONG_TASKS)
    try:
        page.goto(f"{base}/")
        unit = unit_ms(page)
        page.goto(f"{base}/notes/{note}")
        page.wait_for_selector(".graph-board svg", timeout=60000)
        page.wait_for_timeout(1500)
        drawn = page.evaluate("() => window.__long")
        page.locator(".graph-slider input[type=range]").fill("2")
        page.wait_for_timeout(1500)
        total = page.evaluate("() => window.__long")
        count = page.evaluate("() => Object.values(JXG.boards)[0].objectsList.length")
    finally:
        ctx.close()
    print(
        f"  (biggest geometry: {count} elements, {drawn:.0f} ms drawing, {total:.0f} ms with a slider move;"
        f" unit {unit:.0f} ms, ratio {total / unit:.1f})"
    )
    return {
        "geometry: the biggest definition is drawn (the premise)": count > 1500,
        f"geometry: the biggest definition keeps long tasks under {LONG_TASK_LIMIT_UNITS} units of work": total
        < LONG_TASK_LIMIT_UNITS * unit,
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
        drawn_at_flip = page.evaluate(
            "() => { const n = document.querySelectorAll('.graph-board svg').length;"
            " document.documentElement.dataset.theme = 'light'; return n; }"
        )
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
        f"theme: the flip came while drawing, not after ({drawn_at_flip} of 40 drawn)": 1
        <= drawn_at_flip
        < 40,
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
        and "functions first, then curves" in named_hint[0],
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
    view = make_note(ctx, base, f"Graph view {stamp}", PLAY)
    played = make_note(ctx, base, f"Graph play {stamp}", PLAY)
    refused = make_note(ctx, base, f"Graph refused {stamp}", PLAY)
    tall = make_note(ctx, base, f"Graph play tall {stamp}", PLAY_TALL)
    heavy_play = make_note(ctx, base, f"Graph play heavy {stamp}", PLAY_HEAVY)
    irrational = make_note(ctx, base, f"Graph irrational {stamp}", IRRATIONAL)
    geometry = make_note(ctx, base, f"Graph geometry {stamp}", GEOMETRY)
    biggest = make_note(ctx, base, f"Graph biggest geometry {stamp}", BIGGEST_GEOMETRY)
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
            checks.update(check_the_default_view(browser, base, view, ctx))
            checks.update(check_a_refused_save_says_so(browser, base, refused))
            checks.update(check_play(browser, base, played))
            checks.update(check_play_waits_when_it_cannot_be_seen(browser, base, tall))
            checks.update(check_play_leaves_the_page_usable(browser, base, heavy_play))
            checks.update(check_saving_at_an_irrational_end(browser, base, irrational, ctx))
            checks.update(check_geometry(browser, base, geometry))
            checks.update(check_geometry_view(browser, base, geometry))
            checks.update(check_the_biggest_geometry_is_bounded(browser, base, biggest))
            checks.update(check_each_board_says_its_own_limits(browser, base, many, mixed))
            checks.update(check_a_theme_change_while_drawing(browser, base, many))
            checks.update(check_the_curve_cap_and_its_hint(browser, base, circles, named))
            checks.update(
                check_a_board_that_fails_to_draw_leaves_nothing_watching(browser, base, played)
            )
            checks.update(check_one_finger_scrolls(browser, base, good))
            checks.update(check_a_swap_during_the_load(browser, base, good))
    finally:
        for nid in (
            good,
            hostile,
            broken,
            slow,
            many,
            mixed,
            curve,
            circles,
            named,
            view,
            played,
            refused,
            tall,
            heavy_play,
            irrational,
            geometry,
            biggest,
        ):
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
