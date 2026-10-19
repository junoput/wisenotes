"""Drive the fourteen user journeys in a real browser, once with JavaScript
disabled and once with it enabled, against a running server.

    python tests/journeys.py http://127.0.0.1:8000            # both arms
    python tests/journeys.py http://127.0.0.1:8000 --arm nojs # one arm

    python tests/journeys.py http://127.0.0.1:8000 --block-cdn # no third-party hosts

Exit 0: every journey OK in every arm.  Exit 1: a journey failed.
Exit 2: VACUOUS, an arm observed fewer than the fourteen journeys, or its
apparatus check could not tell the arms apart, so no verdict is reported.

Needs `pip install -e '.[e2e]'` and a Playwright chromium (`playwright
install chromium`). The JS-on arm is the control: it proves the driver can
see a journey succeed, so a red in the JS-off arm is a fallback missing,
not a broken driver. The server must have a writable data dir; the driver
creates its own notes and deletes what it can.
"""

import argparse
import json
import struct
import sys
import time
import zlib

from playwright.sync_api import sync_playwright

JOURNEYS = [
    "home",
    "create note",
    "open note",
    "open block editor",
    "save block",
    "add block",
    "reorder block",
    "open settings",
    "rename note",
    "delete note",
    "upload image",
    "pick image",
    "delete image",
    "export",
]


def png_bytes() -> bytes:
    """A valid 4x4 red PNG built by hand, so the driver needs no Pillow."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * 4 for _ in range(4))
    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class Arm:
    def __init__(self, base: str, js: bool, block_cdn: bool = False):
        self.base, self.js, self.block_cdn, self.rows = base, js, block_cdn, {}
        self.mark = f"marker {'js' if js else 'nojs'} {int(time.time())}"

    def rec(self, journey: str, ok: bool, detail: str = ""):
        assert journey in JOURNEYS, journey
        self.rows[journey] = ("OK" if ok else "FAIL", detail)

    def full_page(self, page) -> bool:
        return (
            page.locator("link[rel=stylesheet]").count() > 0
            and page.locator("header.topbar").count() > 0
        )

    def wait(self, page, ms):
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(ms if self.js else 0)

    def api(self, ctx, path):
        return ctx.request.get(self.base + path).json()

    def run(self, p):
        b = p.chromium.launch()
        ctx = b.new_context(java_script_enabled=self.js)
        page = ctx.new_page()
        if self.block_cdn:  # the app must stay usable when only its own host answers
            ctx.route(lambda url: not url.startswith(self.base), lambda route: route.abort())
        errors: list[str] = []
        page.on(
            "response",
            lambda r: (
                errors.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None
            ),
        )
        page.on("dialog", lambda d: d.accept())
        try:
            self._journeys(ctx, page)
        except Exception as e:
            self.crash = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
        else:
            self.crash = None
        self.errors = errors
        # apparatus: page scripts must have run in the JS arm and not in the other
        self.scripts_ran = page.evaluate("() => typeof window.htmx !== 'undefined'")
        b.close()

    def _journeys(self, ctx, page):
        B = self.base
        page.goto(B + "/")
        self.rec("home", page.locator(".pane.list").count() == 1 and self.full_page(page))

        before = page.locator("a.item").count()
        page.locator("a.add-note-btn").first.click()  # the chooser: overlay with JS, page without
        self.wait(page, 1000)
        page.locator("#note-new form.new-note-form button[type=submit]").click()
        self.wait(page, 1500)
        created = page.locator("a.item").count() == before + 1 and self.full_page(page)
        self.rec("create note", created, page.url.replace(B, ""))
        note = [n for n in self.api(ctx, "/api/notes") if n["chapters"]][-1]
        nid, url = note["id"], f"/notes/{note['id']}"

        page.goto(B + "/")
        page.locator(f'a.item[href="{url}"]').first.click()
        self.wait(page, 800)
        self.rec(
            "open note",
            page.locator("section.chapter-section").count() >= 1 and self.full_page(page),
        )

        page.locator("section.chapter-section .chapter-view").first.click()
        self.wait(page, 1200)
        self.rec(
            "open block editor",
            page.locator("form.chapter-edit-form").count() == 1 and self.full_page(page),
        )

        page.locator("form.chapter-edit-form textarea[name=content_text]").fill(self.mark)
        page.locator("form.chapter-edit-form button[type=submit]").click()
        self.wait(page, 1000)
        page.goto(B + url)
        self.rec("save block", self.mark in page.content())

        s0 = page.locator("section.chapter-section").count()
        page.locator("section.chapter-section").first.hover()
        page.locator(
            "section.chapter-section .add-block-menu form button[type=submit]"
        ).first.dispatch_event("click")
        self.wait(page, 1000)
        page.goto(B + url)
        s1 = page.locator("section.chapter-section").count()
        self.rec("add block", s1 == s0 + 1, f"sections {s0}->{s1}")

        ids0 = page.locator("section.chapter-section").evaluate_all(
            "els => els.map(e => e.dataset.chapterId)"
        )
        page.locator("section.chapter-section").first.hover()
        page.locator(
            "section.chapter-section > form.reorder button[value=down]"
        ).first.dispatch_event("click")
        self.wait(page, 1000)
        page.goto(B + url)
        ids1 = page.locator("section.chapter-section").evaluate_all(
            "els => els.map(e => e.dataset.chapterId)"
        )
        self.rec(
            "reorder block", len(ids0) >= 2 and ids1[0] == ids0[1], f"{ids0[:2]} -> {ids1[:2]}"
        )

        page.locator("#editor a.settings-btn").click()
        self.wait(page, 1000)
        self.rec("open settings", page.locator("#note-settings").count() == 1)

        page.locator("#note-settings input[name=title]").fill("Renamed " + self.mark)
        page.locator("#note-settings input[name=title]").press("Enter")
        self.wait(page, 1000)
        title = self.api(ctx, f"/api/notes/{nid}")["title"]
        self.rec(
            "rename note",
            title == "Renamed " + self.mark,
            f"title now {title!r}; page {page.url.replace(B, '')}",
        )

        page.goto(B + url + "/settings")
        page.locator('#note-settings form[action$="/delete"] button').dispatch_event("click")
        self.wait(page, 1500)
        self.rec("delete note", ctx.request.get(f"{B}/api/notes/{nid}").status == 404)

        r = ctx.request.post(
            B + "/api/notes",
            data=json.dumps({"title": "Media " + self.mark}),
            headers={"content-type": "application/json"},
        )
        mid = r.json()["id"]
        ctx.request.post(f"{B}/notes/{mid}/chapters", form={"block_type": "chapter"})
        ch = self.api(ctx, f"/api/notes/{mid}")["chapters"][0]["id"]
        ctx.request.post(
            f"{B}/notes/{mid}/chapters",
            form={"ref_id": ch, "position": "child", "block_type": "media"},
        )
        mcid = self.api(ctx, f"/api/notes/{mid}")["chapters"][1]["id"]
        edit = f"/notes/{mid}/chapters/{mcid}/edit"
        page.goto(B + edit)
        page.locator("form.media-upload input[type=file]").set_input_files(
            {"name": "red.png", "mimeType": "image/png", "buffer": png_bytes()}
        )
        if not self.js:
            page.locator("form.media-upload button[type=submit]").click()
        self.wait(page, 1500)
        files = self.api(ctx, f"/api/notes/{mid}/media/list")["media"]
        self.rec("upload image", len(files) == 1, str(files))

        page.goto(B + edit)
        page.locator(".media-gallery button.media-pick").first.click()
        self.wait(page, 1000)
        content = self.api(ctx, f"/api/notes/{mid}")["chapters"][1]["content"]
        self.rec("pick image", bool(files) and content.endswith(files[0]), content)

        page.goto(B + edit)
        page.locator(".media-gallery-thumb").first.hover()
        page.locator(".media-gallery button.media-delete-btn").first.dispatch_event("click")
        self.wait(page, 1000)
        self.rec("delete image", self.api(ctx, f"/api/notes/{mid}/media/list")["media"] == [])
        ctx.request.delete(f"{B}/api/notes/{mid}")

        r = ctx.request.get(B + "/api/export")
        self.rec("export", r.status == 200 and "notes" in r.text())


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("base", help="server URL, e.g. http://127.0.0.1:8000")
    ap.add_argument("--arm", choices=["nojs", "js", "both"], default="both")
    ap.add_argument(
        "--block-cdn",
        action="store_true",
        help="abort every request to a host other than the server",
    )
    args = ap.parse_args()
    arms = [
        Arm(args.base, js, args.block_cdn)
        for js in (
            (False,) if args.arm == "nojs" else (True,) if args.arm == "js" else (False, True)
        )
    ]
    with sync_playwright() as p:
        for arm in arms:
            arm.run(p)
    worst = 0
    for arm in arms:
        label = ("JS on " if arm.js else "JS off") + (", CDN blocked" if arm.block_cdn else "")
        print(f"\n== arm: {label}  (page scripts ran: {arm.scripts_ran})")
        for j in JOURNEYS:
            verdict, detail = arm.rows.get(j, ("NOT RUN", ""))
            print(f"  {j:18s} {verdict:8s} {detail}")
        if arm.crash:
            print(f"  driver crashed: {arm.crash}")
        if arm.errors:
            print("  4xx/5xx seen:", *arm.errors, sep="\n    ")
        seen = len(arm.rows)
        if seen < len(JOURNEYS) or arm.scripts_ran != arm.js:
            why = (
                f"observed {seen}/{len(JOURNEYS)} journeys"
                if seen < len(JOURNEYS)
                else "apparatus check failed: arm cannot tell scripts on from off"
            )
            print(f"  VERDICT: VACUOUS ({why}); no pass or fail is reported for this arm")
            worst = max(worst, 2)
            continue
        failed = [j for j, (v, _) in arm.rows.items() if v != "OK"]
        print(
            f"  VERDICT: {'FAIL ' + ', '.join(failed) if failed else 'PASS'} ({seen}/{len(JOURNEYS)} journeys observed)"
        )
        worst = max(worst, 1 if failed else 0)
    return worst


if __name__ == "__main__":
    sys.exit(main())
