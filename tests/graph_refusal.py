"""Drive the refusal of a bad graph definition in a real browser, JavaScript off and on.

    python tests/graph_refusal.py http://127.0.0.1:8000

The server answers a bad definition with a 400 and the edit form with its reasons.
htmx drops a 4xx body unless app.js lets it through (BLOCK_SAVE in app.js), and then
the person sees nothing: no reasons, and the typed text gone. No server-side test
can see that, so this drives it, in the two arms of tests/journeys.py. The scripts-off
arm is the plain-form path; the scripts-on arm is the one that depends on app.js.

Exit 0: both arms showed the reasons, kept the typed text and stored nothing.
Exit 1: an arm failed. Exit 2: VACUOUS, the arms could not be told apart, or a good
definition did not save in an arm (the control: the driver could not see a save).
Needs the e2e setup of CONTRIBUTING.md and a server with a writable data dir.
"""

import json
import sys
import time

from playwright.sync_api import sync_playwright

GOOD = "view 2d  x -5..5\na = slider(0, 5, value 1)\nf(x) = a*sin(x)"
BAD = "a = slider(5, 1)\nf(x) = 2x"
CONTROL = "view 2d  x -2..2\nf(x) = x^2"


def api(ctx, base, path):
    return ctx.request.get(base + path).json()


def drive(p, base: str, js: bool) -> dict:
    result = {"js": js, "checks": {}, "scripts_ran": None}
    browser = p.chromium.launch()
    ctx = browser.new_context(java_script_enabled=js)
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())
    chapters = [
        {"id": "ch", "title": "Top", "order": 0, "type": "chapter"},
        {"id": "g", "title": "", "order": 0, "type": "graph", "parent_id": "ch", "content": GOOD},
    ]
    title = f"Graph refusal {'js' if js else 'nojs'} {int(time.time())}"
    note = ctx.request.post(
        base + "/api/notes",
        data=json.dumps({"title": title, "chapters": chapters}),
        headers={"content-type": "application/json"},
    ).json()
    nid, url = note["id"], f"/notes/{note['id']}"

    def stored() -> dict:
        return next(c for c in api(ctx, base, f"/api/notes/{nid}")["chapters"] if c["id"] == "g")

    def open_editor(text: str):
        page.goto(base + url)
        if js:  # the path that depends on app.js: htmx fetches the form into the page
            page.locator("section.chapter-section .chapter-view").nth(1).click()
            page.wait_for_selector("form.chapter-edit-form")
        else:
            page.goto(base + f"{url}/chapters/g/edit")
        page.locator("form.chapter-edit-form textarea[name=content_text]").fill(text)
        page.locator("form.chapter-edit-form button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500 if js else 0)

    open_editor(BAD)
    body = page.content()
    area = page.locator("form.chapter-edit-form textarea[name=content_text]")
    result["checks"]["reasons shown"] = (
        page.locator("form.chapter-edit-form").count() == 1
        and "Not saved" in body
        and "line 1: the slider must go from low to high" in body
    )
    result["checks"]["typed text kept"] = area.count() == 1 and area.input_value() == BAD
    result["checks"]["nothing stored"] = stored()["content"] == GOOD

    # control: the driver can see a good definition saved, in this arm
    open_editor(CONTROL)
    page.goto(base + url)
    # a plain form posts a textarea with CRLF line ends; the language reads them as blanks
    saved = stored()["content"].replace("\r\n", "\n")
    result["checks"]["control: good definition saved"] = saved == CONTROL
    result["scripts_ran"] = page.evaluate("() => typeof window.htmx !== 'undefined'")
    ctx.request.delete(f"{base}/api/notes/{nid}")
    browser.close()
    return result


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    worst = 0
    with sync_playwright() as p:
        for js in (False, True):
            r = drive(p, base, js)
            print(
                f"\n== arm: {'JS on ' if js else 'JS off'}  (page scripts ran: {r['scripts_ran']})"
            )
            for name, ok in r["checks"].items():
                print(f"  {name:34s} {'OK' if ok else 'FAIL'}")
            control = r["checks"]["control: good definition saved"]
            if r["scripts_ran"] != js or not control:
                print("  VERDICT: VACUOUS; no pass or fail is reported for this arm")
                worst = max(worst, 2)
                continue
            failed = [n for n, ok in r["checks"].items() if not ok]
            print(f"  VERDICT: {'FAIL ' + ', '.join(failed) if failed else 'PASS'}")
            worst = max(worst, 1 if failed else 0)
    return worst


if __name__ == "__main__":
    sys.exit(main())
