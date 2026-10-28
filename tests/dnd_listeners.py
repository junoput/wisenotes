"""Count the drag-and-drop listeners that survive htmx swaps (20261028-027).

    python tests/dnd_listeners.py http://127.0.0.1:8000

initDragAndDrop runs after every swap. Listeners added with a fresh arrow function each
time pile up on the nodes that outlive a swap (document, .chapters-display): +N per swap,
hundreds after a long editing session. A named function is added once, because the DOM
ignores the same listener added twice. This counts the dragover and drop listeners on those
nodes with CDP (DOMDebugger.getEventListeners) before and after SWAPS swaps.

Exit 0: the count did not grow. Exit 1: it grew. Exit 2: VACUOUS, the swaps did not run
(the control: the number of htmx:afterSwap events seen must equal SWAPS) or the
page had no listeners to count.
"""

import json
import sys
import time

from playwright.sync_api import sync_playwright

SWAPS = 20
TYPES = {"dragover", "drop"}


def count(cdp, expression: str) -> int:
    obj = cdp.send("Runtime.evaluate", {"expression": expression})["result"]
    listeners = cdp.send("DOMDebugger.getEventListeners", {"objectId": obj["objectId"]})
    return sum(1 for item in listeners["listeners"] if item["type"] in TYPES)


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        chapters = [
            {"id": "ch", "title": "Top", "order": 0, "type": "chapter"},
            {"id": "c", "title": "", "order": 0, "type": "code", "parent_id": "ch", "content": "x = 1"},
        ]
        note = ctx.request.post(
            base + "/api/notes",
            data=json.dumps({"title": f"Dnd listeners {int(time.time())}", "chapters": chapters}),
            headers={"content-type": "application/json"},
        ).json()
        nid = note["id"]
        page.goto(f"{base}/notes/{nid}")
        page.wait_for_selector(".chapters-display .drag-handle")
        page.evaluate(
            "() => { window.__swaps = 0;"
            " document.body.addEventListener('htmx:afterSwap', () => { window.__swaps++; }); }"
        )
        cdp = ctx.new_cdp_session(page)

        def counted() -> dict:
            return {
                "document": count(cdp, "document"),
                "chapters-display": count(cdp, "document.querySelector('.chapters-display')"),
            }

        before = counted()
        for _ in range(SWAPS):
            page.evaluate(
                "() => window.htmx.ajax('GET', '/notes/" + nid + "/chapters/ch/edit',"
                " { target: '.chapter-content-wrapper', swap: 'innerHTML' })"
            )
            page.wait_for_timeout(60)
        page.wait_for_timeout(300)
        seen = page.evaluate("() => window.__swaps")
        after = counted()
        ctx.request.delete(f"{base}/api/notes/{nid}")
        browser.close()

    print(f"swaps seen {seen} of {SWAPS}; listeners before {before}, after {after}")
    if seen != SWAPS or not all(before.values()):
        print("VERDICT: VACUOUS; the swaps did not all run, or there was nothing to count")
        return 2
    grew = {k: (before[k], after[k]) for k in before if after[k] > before[k]}
    print(f"VERDICT: {'FAIL grew ' + str(grew) if grew else 'PASS'}")
    return 1 if grew else 0


if __name__ == "__main__":
    sys.exit(main())
