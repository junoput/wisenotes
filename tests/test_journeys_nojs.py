"""The fourteen journeys of tests/journeys.py, driven without a browser.

Each step finds a real <form> or <a> in the rendered HTML and submits it the
way a browser with scripts off would: the form's own action and method, its
own fields, no hx-* attribute read. So this fails the day a journey depends
on JavaScript again, and it runs in CI where no browser does. The browser
driver remains the instrument for the htmx/CodeMirror/KaTeX side.

Vacuity floor: every journey name in JOURNEYS must be recorded exactly once
or the module fails, whatever the individual steps said.
"""

import re
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin

import pytest
from PIL import Image

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


class Page(HTMLParser):
    """Forms with their fields and links, as a JS-less browser sees them."""

    def __init__(self, html: str, url: str):
        super().__init__()
        self.url, self.forms, self.links, self._cur = url, [], [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._cur = {"attrs": a, "fields": {}, "buttons": [], "files": []}
            self.forms.append(self._cur)
        elif self._cur is not None and tag in ("input", "textarea", "select"):
            if a.get("type") == "file":
                self._cur["files"].append(a.get("name"))
            elif a.get("type") in ("submit", "button"):
                pass
            elif a.get("name"):
                self._cur["fields"][a["name"]] = a.get("value", "")
        elif self._cur is not None and tag == "button" and a.get("name"):
            self._cur["buttons"].append((a["name"], a.get("value", "")))
        elif tag == "a" and a.get("href"):
            self.links.append(a)

    def handle_endtag(self, tag):
        if tag == "form":
            self._cur = None

    def form(self, **match):
        """The single form whose attrs contain every given substring."""
        hits = [
            f for f in self.forms if all(v in (f["attrs"].get(k) or "") for k, v in match.items())
        ]
        assert len(hits) >= 1, (match, [f["attrs"] for f in self.forms])
        return hits[0]


def submit(client, form, page_url, override=None, files=None, button=None):
    """Exactly what the browser does on submit: action (default current URL),
    method (default GET), the form's fields, plus one named button."""
    a = form["attrs"]
    assert "action" in a and a.get("method", "").lower() == "post", (
        f"form is not a real POST form: {a}"
    )
    data = dict(form["fields"])
    if button:
        data[button[0]] = button[1]
    data.update(override or {})
    action = urljoin(page_url, a["action"])
    resp = client.post(action, data=data, files=files, follow_redirects=False)
    assert resp.status_code == 303, (action, resp.status_code, resp.text[:200])
    return resp.headers["location"]


def check_floor(seen: list[str]) -> None:
    missing = [j for j in JOURNEYS if j not in seen]
    assert not missing, f"VACUOUS: journeys not observed: {missing}"


@pytest.fixture()
def journeys(client):
    seen: list[str] = []

    def rec(name):
        assert name in JOURNEYS and name not in seen, name
        seen.append(name)

    yield client, rec
    check_floor(seen)


def is_page(resp):
    return resp.status_code == 200 and resp.text.lstrip().lower().startswith("<!doctype html>")


def test_fourteen_journeys_without_scripts(journeys):
    client, rec = journeys

    home = client.get("/")
    assert is_page(home)
    rec("home")

    p = Page(home.text, "/")
    loc = submit(client, p.form(**{"class": "add-note-form"}), "/")
    note_url = loc
    note_id = loc.rsplit("/", 1)[-1]
    assert client.get(f"/api/notes/{note_id}").status_code == 200
    rec("create note")

    home = Page(client.get("/").text, "/")
    assert any(a["href"] == note_url for a in home.links)
    note_page = client.get(note_url)
    assert is_page(note_page) and 'class="chapter-section' in note_page.text
    rec("open note")

    p = Page(note_page.text, note_url)
    edit_link = next(a["href"] for a in p.links if "chapter-view" in a.get("class", ""))
    edit_page = client.get(edit_link)
    assert is_page(edit_page)
    rec("open block editor")

    p = Page(edit_page.text, edit_link)
    submit(
        client,
        p.form(**{"class": "chapter-edit-form"}),
        edit_link,
        {"content_text": "no script here"},
    )
    assert "no script here" in client.get(note_url).text
    rec("save block")

    p = Page(client.get(note_url).text, note_url)
    menu = [
        f
        for f in p.forms
        if f["fields"].get("position") == "after" and f["fields"].get("block_type") == "chapter"
    ]
    submit(client, menu[0], note_url)
    chapters = client.get(f"/api/notes/{note_id}").json()["chapters"]
    assert len(chapters) == 2
    rec("add block")

    p = Page(client.get(note_url).text, note_url)
    first_id = re.search(r'data-chapter-id="([^"]+)"', client.get(note_url).text).group(1)
    reorder = p.form(**{"class": "reorder", "action": f"/chapters/{first_id}/reorder"})
    submit(client, reorder, note_url, button=("op", "down"))
    order = {c["id"]: c["order"] for c in client.get(f"/api/notes/{note_id}").json()["chapters"]}
    assert order[first_id] == 1
    rec("reorder block")

    p = Page(client.get(note_url).text, note_url)
    settings_link = next(a["href"] for a in p.links if "settings-btn" in a.get("class", ""))
    settings = client.get(settings_link)
    assert is_page(settings) and 'id="note-settings"' in settings.text
    rec("open settings")

    p = Page(settings.text, settings_link)
    submit(client, p.form(action="/title"), settings_link, {"title": "Renamed plainly"})
    assert client.get(f"/api/notes/{note_id}").json()["title"] == "Renamed plainly"
    rec("rename note")

    p = Page(client.get(settings_link).text, settings_link)
    assert submit(client, p.form(action=f"/notes/{note_id}/delete"), settings_link) == "/"
    assert client.get(f"/api/notes/{note_id}").status_code == 404
    rec("delete note")

    mid = client.post("/api/notes", json={"title": "Media journey"}).json()["id"]
    client.post(f"/notes/{mid}/chapters", data={"block_type": "chapter"})
    root = client.get(f"/api/notes/{mid}").json()["chapters"][0]["id"]
    client.post(
        f"/notes/{mid}/chapters", data={"block_type": "media", "position": "child", "ref_id": root}
    )
    mcid = client.get(f"/api/notes/{mid}").json()["chapters"][1]["id"]
    edit_link = f"/notes/{mid}/chapters/{mcid}/edit"
    p = Page(client.get(edit_link).text, edit_link)
    upload = p.form(**{"class": "media-upload"})
    assert upload["files"] == ["file"] and "enctype" in upload["attrs"]
    buf = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    assert (
        submit(client, upload, edit_link, files={"file": ("red.png", buf.getvalue(), "image/png")})
        == edit_link
    )
    [filename] = client.get(f"/api/notes/{mid}/media/list").json()["media"]
    rec("upload image")

    p = Page(client.get(edit_link).text, edit_link)
    submit(client, p.form(action="/media/select"), edit_link)
    assert client.get(f"/api/notes/{mid}").json()["chapters"][1]["content"].endswith(filename)
    rec("pick image")

    p = Page(client.get(edit_link).text, edit_link)
    submit(client, p.form(action=f"/media/{filename}/delete"), edit_link)
    assert client.get(f"/api/notes/{mid}/media/list").json()["media"] == []
    rec("delete image")

    p = Page(client.get(settings_link.replace(note_id, mid)).text, "/")
    export = next(a["href"] for a in p.links if a["href"] == "/api/export")
    resp = client.get(export)
    assert resp.status_code == 200 and "notes" in resp.json()
    rec("export")


def test_vacuity_floor_fires():
    """A run that records fewer journeys must fail, whatever the steps saw."""
    check_floor(list(JOURNEYS))
    with pytest.raises(AssertionError, match="VACUOUS"):
        check_floor(["home"])
