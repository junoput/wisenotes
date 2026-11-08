"""Drive the picture of a graph block's default view in a real browser (20261022-064, slice 5).

    python tests/graph_snapshot.py http://127.0.0.1:8000

Against a running server, so the Content-Security-Policy is the one the app sends. Exit 0:
every check passed in both arms. Exit 1: a check failed. Exit 2: VACUOUS, an arm saw nothing
to judge (its scripts did not run as the arm says, the scripts-on arm sent no picture, or the
scripts-off arm had no picture to look at).

Scripts on (run first; it makes the pictures the other arm looks at):
  - a graph that has no picture sends one, once, and the page then says it has one;
  - the picture is the default view in the light palette on white (the page is dark), at
    1280x800, not blank, and it follows the slider's declared value (a control: the same
    definition with another value gives another picture);
  - two blocks with one definition send one picture; a reload sends none;
  - no CSP violation, no console error;
  - print puts the board at the default view and the sliders at their values, then returns
    it to where the person had it (the print media query and the beforeprint event both);
  - on paper the controls are gone and the board is the figure;
  - a board that cannot be drawn (its library blocked) shows the picture and the text.
Scripts off:
  - the block shows the picture, which the server serves as WebP, and the definition text;
  - on paper it is the picture without the text; a graph with no picture is its text.
"""

import argparse
import io
import json
import sys
import time

from PIL import Image
from PIL import ImageChops
from playwright.sync_api import sync_playwright

SPEC = (
    "view 2d  x -6..6  y -4..4\n"
    "a = slider(0, 3, step 0.5, value {value})\n"
    "f(x) = a*sin(x)\n"
    "P = (1, f(1))\n"
)
DEFAULT_BOX = [-6, 4, 6, -4]
CURVE = (14, 116, 144)  # --accent of the light theme, the first curve's colour
STATE: dict = {}  # what the scripts-on arm made, for the scripts-off arm


def make_note(ctx, base, title, specs):
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
    r = ctx.request.post(
        base + "/api/notes",
        data=json.dumps({"title": title, "chapters": chapters}),
        headers={"content-type": "application/json"},
    )
    return r.json()["id"]


def pictures(ctx, base, note):
    names = ctx.request.get(f"{base}/api/notes/{note}/media/list").json()["media"]
    return [n for n in names if n.startswith("graph-")]


def picture(ctx, base, note, name):
    r = ctx.request.get(f"{base}/api/notes/{note}/media/{name}")
    return r.headers.get("content-type"), Image.open(io.BytesIO(r.body())).convert("RGB")


def pixels(img):
    raw = img.convert("RGB").tobytes()
    return zip(raw[0::3], raw[1::3], raw[2::3], strict=True)


def ink(img, near, tol=40):
    """How many pixels are near a colour."""
    return sum(
        1 for px in pixels(img) if all(abs(a - b) <= tol for a, b in zip(px, near, strict=True))
    )


def not_white(img):
    return sum(1 for px in pixels(img) if px != (255, 255, 255))


def box_of(page):
    return page.evaluate("() => Object.values(window.JXG.boards)[0].getBoundingBox()")


def close(got, want, tol=1e-3):
    return all(abs(g - w) <= tol * max(1, abs(w)) for g, w in zip(got, want, strict=True))


def slider_text(page):
    return page.locator(".graph-slider output").first.inner_text()


def drive(p, base, js, shots):
    result = {"js": js, "checks": {}, "scripts_ran": None}
    checks = result["checks"]
    browser = p.chromium.launch()
    # dark: the picture must not follow the page's theme
    ctx = browser.new_context(
        java_script_enabled=js, viewport={"width": 900, "height": 900}, color_scheme="dark"
    )
    page = ctx.new_page()
    problems = []
    posts = []
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
    page.on(
        "request",
        lambda r: posts.append(r.url) if r.method == "POST" and "graph-snapshot" in r.url else None,
    )
    try:
        if js:
            drive_scripts_on(ctx, page, base, checks, problems, posts, result, shots)
        else:
            drive_scripts_off(ctx, page, base, checks, result)
    finally:
        browser.close()
    return result


def drive_scripts_on(ctx, page, base, checks, problems, posts, result, shots):
    stamp = int(time.time())
    a = make_note(ctx, base, f"Graph snapshot A {stamp}", [SPEC.format(value=1)])
    b = make_note(ctx, base, f"Graph snapshot B {stamp}", [SPEC.format(value=3)])
    twin = make_note(ctx, base, f"Graph snapshot twin {stamp}", [SPEC.format(value=2)] * 2)
    STATE.update(a=a, b=b)

    page.goto(f"{base}/notes/{a}")
    result["scripts_ran"] = page.evaluate("() => typeof window.htmx !== 'undefined'")
    checks["board drawn"] = bool(page.wait_for_selector(".graph-board svg", timeout=20000))
    checks["a graph with no picture starts without one"] = (
        page.locator("figure.graph-block-display[data-has-snapshot]").count() == 0
        and page.locator("img.graph-snapshot").count() == 0
    )
    stored = False
    try:
        page.wait_for_selector(
            "figure.graph-block-display[data-has-snapshot]", state="attached", timeout=20000
        )
        stored = True
    except Exception:
        pass
    checks["the page sent a picture and the server stored it"] = stored and len(posts) == 1
    names = pictures(ctx, base, a)
    checks["one picture is stored, named after the definition"] = names == [
        f"graph-{page.locator('figure.graph-block-display').get_attribute('data-spec-hash')}.webp"
    ]
    if names:
        kind, img = picture(ctx, base, a, names[0])
        STATE["image_a"] = img
        checks["the server serves it as WebP"] = kind == "image/webp"
        checks["it is 1280x800 (twice the board)"] = img.size == (1280, 800)
        checks["it is on white although the page is dark"] = img.getpixel((2, 2)) == (255, 255, 255)
        checks["it shows ink: more than the axes alone"] = not_white(img) > 4000
        checks["the curve is in the light palette's colour"] = ink(img, CURVE) > 300
    else:
        for name in (
            "the server serves it as WebP",
            "it is 1280x800 (twice the board)",
            "it is on white although the page is dark",
            "it shows ink: more than the axes alone",
            "the curve is in the light palette's colour",
        ):
            checks[name] = False
    checks["a picture is not blank: it differs from a white one (control)"] = bool(names) and (
        ImageChops.difference(STATE["image_a"], Image.new("RGB", (1280, 800), "white")).getbbox()
        is not None
    )

    # the same definition with another slider value is another picture
    page.goto(f"{base}/notes/{b}")
    try:
        page.wait_for_selector(
            "figure.graph-block-display[data-has-snapshot]", state="attached", timeout=20000
        )
    except Exception:
        pass
    names_b = pictures(ctx, base, b)
    if names and names_b:
        _, img_b = picture(ctx, base, b, names_b[0])
        checks["the picture follows the slider's declared value"] = (
            ImageChops.difference(STATE["image_a"], img_b).getbbox() is not None
        )
    else:
        checks["the picture follows the slider's declared value"] = False

    # two blocks, one definition: one picture
    before = len(posts)
    page.goto(f"{base}/notes/{twin}")
    page.wait_for_selector(".graph-board svg", timeout=20000)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('figure.graph-block-display[data-has-snapshot]').length >= 1",
            timeout=20000,
        )
    except Exception:
        pass
    page.wait_for_timeout(800)
    checks["two blocks with one definition send one picture"] = (
        len(posts) - before == 1 and len(pictures(ctx, base, twin)) == 1
    )

    # a reload sends nothing, and the page already says it has the picture
    before = len(posts)
    page.goto(f"{base}/notes/{a}")
    page.wait_for_selector(".graph-board svg", timeout=20000)
    page.wait_for_timeout(1000)
    checks["a reload sends no picture"] = len(posts) == before
    checks["the picture is in the page, hidden behind the drawn board"] = (
        page.locator("figure.graph-block-display.graph-has-snapshot img.graph-snapshot").count()
        == 1
        and not page.locator("img.graph-snapshot").is_visible()
    )

    # print: the default view, then back
    board = page.locator(".graph-board")
    box = board.bounding_box()
    page.mouse.move(box["x"] + 150, box["y"] + 150)
    page.mouse.down()
    page.mouse.move(box["x"] + 230, box["y"] + 190, steps=8)
    page.mouse.up()
    page.locator(".graph-slider input[type=range]").fill("3")
    page.wait_for_timeout(400)
    panned = box_of(page)
    checks["premise: the board is panned and the slider moved"] = (
        not close(panned, DEFAULT_BOX) and slider_text(page) == "3"
    )
    page.emulate_media(media="print")
    page.wait_for_timeout(300)
    checks["print (media query): the board is at the default view"] = close(
        box_of(page), DEFAULT_BOX
    )
    checks["print (media query): the slider is at its declared value"] = slider_text(page) == "1"
    checks["print: the controls and the hint are not on the page"] = not any(
        page.locator(sel).first.is_visible()
        for sel in (".graph-controls", ".graph-hint", ".graph-source-caption")
    )
    checks["print: the drawn board is the figure; no picture beside it, no text"] = (
        page.locator(".graph-board").is_visible()
        and not page.locator("img.graph-snapshot").is_visible()
        and not page.locator("pre.graph-spec").is_visible()
    )
    page.emulate_media(media="screen")
    page.wait_for_timeout(300)
    checks["after print the board is where the person had it"] = close(box_of(page), panned)
    checks["after print the slider is where the person had it"] = slider_text(page) == "3"
    page.evaluate("() => window.dispatchEvent(new Event('beforeprint'))")
    checks["beforeprint puts the board at the default view too"] = (
        close(box_of(page), DEFAULT_BOX) and slider_text(page) == "1"
    )
    page.evaluate("() => window.dispatchEvent(new Event('afterprint'))")
    checks["afterprint returns it"] = close(box_of(page), panned) and slider_text(page) == "3"
    if shots:
        page.screenshot(path=f"{shots}/graph-snapshot-board.png")

    # the library cannot load: the picture and the text stay
    blocked = ctx.new_page()
    blocked.route("**/jsxgraphcore.js", lambda route: route.abort())
    blocked.goto(f"{base}/notes/{a}")
    blocked.wait_for_timeout(1500)
    checks["a board that cannot be drawn shows its picture"] = blocked.locator(
        "img.graph-snapshot"
    ).is_visible()
    checks["a board that cannot be drawn shows its text"] = (
        "a*sin(x)" in blocked.locator("pre.graph-spec").inner_text()
    )
    blocked.close()

    csp = page.evaluate("() => window.__csp")
    checks["no CSP violation"] = csp == []
    checks["no console error or uncaught error"] = not [
        p for p in problems if "Failed to load resource" not in p or "jsxgraphcore" not in p
    ]
    if csp or problems:
        print("   ", csp, problems[:5])


def drive_scripts_off(ctx, page, base, checks, result):
    a = STATE.get("a")
    stamp = int(time.time())
    bare = make_note(ctx, base, f"Graph snapshot bare {stamp}", [SPEC.format(value=1)])
    if not a:  # the scripts-on arm made nothing: nothing to look at
        return
    page.goto(f"{base}/notes/{a}")
    page.wait_for_load_state("networkidle")
    result["scripts_ran"] = page.evaluate("() => typeof window.htmx !== 'undefined'")
    img = page.locator("img.graph-snapshot")
    checks["the block shows the picture"] = img.count() == 1 and img.is_visible()
    src = img.get_attribute("src") if img.count() else ""
    served = ctx.request.get(base + src) if src else None
    checks["the picture is served as WebP"] = bool(served) and (
        served.status == 200 and served.headers.get("content-type") == "image/webp"
    )
    checks["it is the picture the scripts-on arm sent"] = bool(served) and (
        Image.open(io.BytesIO(served.body())).size == (1280, 800)
        and ImageChops.difference(
            STATE["image_a"], Image.open(io.BytesIO(served.body())).convert("RGB")
        ).getbbox()
        is None
    )
    checks["it has a text alternative"] = bool(img.get_attribute("alt"))
    checks["the definition text is still there"] = (
        "a*sin(x)" in page.locator("pre.graph-spec").inner_text()
    )
    checks["nothing was drawn"] = page.locator(".graph-board").count() == 0
    page.emulate_media(media="print")
    checks["print: the picture is shown"] = img.is_visible()
    checks["print: its text and caption are not"] = not (
        page.locator("pre.graph-spec").is_visible()
        or page.locator(".graph-source-caption").is_visible()
    )
    page.emulate_media(media="screen")
    page.goto(f"{base}/notes/{bare}")
    checks["a graph with no picture shows its text and no picture"] = (
        page.locator("img.graph-snapshot").count() == 0
        and "a*sin(x)" in page.locator("pre.graph-spec").inner_text()
    )
    page.emulate_media(media="print")
    checks["print: a graph with no picture prints its text"] = page.locator(
        "pre.graph-spec"
    ).is_visible()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", help="directory for a screenshot of the drawn board")
    args = ap.parse_args()
    worst = 0
    with sync_playwright() as p:
        for js in (True, False):
            r = drive(p, args.base, js, args.shots)
            print(
                f"\n== arm: {'JS on ' if js else 'JS off'}  (page scripts ran: {r['scripts_ran']})"
            )
            for name, ok in r["checks"].items():
                print(f"  {name:70s} {'OK' if ok else 'FAIL'}")
            sent = r["checks"].get("the page sent a picture and the server stored it", not js)
            enough = len(r["checks"]) >= (20 if js else 8)
            if r["scripts_ran"] != js or not sent or not enough:
                print("  VERDICT: VACUOUS; no pass or fail is reported for this arm")
                worst = max(worst, 2)
                continue
            failed = [n for n, ok in r["checks"].items() if not ok]
            print(f"  VERDICT: {'FAIL ' + ', '.join(failed) if failed else 'PASS'}")
            worst = max(worst, 1 if failed else 0)
    return worst


if __name__ == "__main__":
    sys.exit(main())
