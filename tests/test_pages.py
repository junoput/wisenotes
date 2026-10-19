"""The HTML routes, driven the way a browser without JavaScript drives them:
plain form POSTs with no HX-Request header must redirect to a full page, and
the same POSTs with the header must return the htmx fragment."""

import asyncio
import json
import re
import zipfile
from io import BytesIO
from urllib.parse import quote

from PIL import Image

from app.routes import api
from app.routes import pages

HX = {"HX-Request": "true"}


def _doc(resp):
    return resp.text.lstrip().lower().startswith("<!doctype html>")


def _create(client, title="Page test"):
    resp = client.post("/notes", data={"title": title}, follow_redirects=False)
    assert resp.status_code == 303
    note = client.get("/api/notes").json()[-1]
    assert resp.headers["location"] == f"/notes/{note['id']}"
    return note


def test_home_is_a_full_document(client):
    resp = client.get("/")
    assert resp.status_code == 200 and _doc(resp)
    assert 'rel="stylesheet"' in resp.text


def test_create_note_plain_post_redirects_to_the_note(client):
    note = _create(client, "Formed")
    assert note["title"] == "Formed" and len(note["chapters"]) == 1
    page = client.get(f"/notes/{note['id']}")
    assert _doc(page) and "Formed" in page.text


def test_create_note_htmx_post_gets_fragment(client):
    resp = client.post("/notes", data={"title": "Swapped"}, headers=HX)
    assert resp.status_code == 200 and not _doc(resp)
    assert "hx-swap-oob" in resp.text and "Swapped" in resp.text


def test_note_page(client):
    note = _create(client, "Deep Link")
    resp = client.get(f"/notes/{note['id']}")
    assert resp.status_code == 200 and _doc(resp)
    assert 'class="chapter-section' in resp.text


def test_every_hx_form_is_also_a_real_form(client):
    """The no-JS rule, checked mechanically on the two densest pages."""
    note = _create(client)
    cid = note["chapters"][0]["id"]
    for url in (
        f"/notes/{note['id']}",
        f"/notes/{note['id']}/chapters/{cid}/edit",
        f"/notes/{note['id']}/settings",
    ):
        html = client.get(url).text
        for form in re.findall(r"<form[^>]*>", html):
            if "hx-post" in form:
                assert 'action="' in form and 'method="post"' in form, (url, form)
        for tag in re.findall(r"<(?:a|div|button|img)[^>]*hx-get[^>]*>", html):
            assert tag.startswith("<a") and 'href="' in tag, (url, tag)


def test_edit_form_is_a_page_without_htmx_and_a_fragment_with(client):
    note = _create(client)
    cid = note["chapters"][0]["id"]
    url = f"/notes/{note['id']}/chapters/{cid}/edit"
    page = client.get(url)
    assert _doc(page) and 'class="chapter-edit-form"' in page.text
    frag = client.get(url, headers=HX)
    assert not _doc(frag) and 'class="chapter-edit-form"' in frag.text


def test_save_chapter_with_plain_fields(client):
    note = _create(client)
    cid = note["chapters"][0]["id"]
    resp = client.post(
        f"/notes/{note['id']}/chapters/{cid}/edit",
        data={"title": "Renamed", "content_text": "hello, no script", "source": "a ;; b ;"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    ch = client.get(f"/api/notes/{note['id']}").json()["chapters"][0]
    assert (ch["title"], ch["content"], ch["source"]) == ("Renamed", "hello, no script", "a; b")


def test_add_block_positions(client):
    note = _create(client)
    root = note["chapters"][0]["id"]
    nid = note["id"]
    client.post(
        f"/notes/{nid}/chapters",
        data={"block_type": "paragraph", "position": "child", "ref_id": root},
    )
    client.post(
        f"/notes/{nid}/chapters",
        data={"block_type": "chapter", "position": "after", "ref_id": root},
    )
    client.post(
        f"/notes/{nid}/chapters",
        data={"block_type": "chapter", "position": "before", "ref_id": root},
    )
    chapters = client.get(f"/api/notes/{nid}").json()["chapters"]
    roots = sorted([c for c in chapters if c["parent_id"] is None], key=lambda c: c["order"])
    assert [c["id"] == root for c in roots] == [False, True, False]
    assert [c["type"] for c in chapters if c["parent_id"] == root] == ["paragraph"]


def test_reorder_buttons(client):
    note = _create(client)
    nid, first = note["id"], note["chapters"][0]["id"]
    client.post(f"/notes/{nid}/chapters", data={"block_type": "chapter", "position": "end"})
    second = client.get(f"/api/notes/{nid}").json()["chapters"][1]["id"]
    assert (
        client.post(
            f"/notes/{nid}/chapters/{second}/reorder", data={"op": "up"}, follow_redirects=False
        ).status_code
        == 303
    )
    orders = {c["id"]: c["order"] for c in client.get(f"/api/notes/{nid}").json()["chapters"]}
    assert orders[second] < orders[first]
    assert (
        client.post(f"/notes/{nid}/chapters/{second}/reorder", data={"op": "sideways"}).status_code
        == 400
    )


def test_settings_page_rename_and_delete(client):
    note = _create(client, "Old")
    nid = note["id"]
    page = client.get(f"/notes/{nid}/settings")
    assert _doc(page) and 'id="note-settings"' in page.text
    client.post(f"/notes/{nid}/title", data={"title": "New"})
    assert client.get(f"/api/notes/{nid}").json()["title"] == "New"
    resp = client.post(f"/notes/{nid}/delete", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/"
    assert client.get(f"/api/notes/{nid}").status_code == 404


def test_delete_chapter_form(client):
    note = _create(client)
    nid, cid = note["id"], note["chapters"][0]["id"]
    assert (
        client.post(f"/notes/{nid}/chapters/{cid}/delete", follow_redirects=False).status_code
        == 303
    )
    assert client.get(f"/api/notes/{nid}").json()["chapters"] == []


def test_media_upload_select_delete_as_forms(client):
    note = _create(client)
    nid, root = note["id"], note["chapters"][0]["id"]
    client.post(
        f"/notes/{nid}/chapters", data={"block_type": "media", "position": "child", "ref_id": root}
    )
    mcid = client.get(f"/api/notes/{nid}").json()["chapters"][1]["id"]
    buf = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    resp = client.post(
        f"/notes/{nid}/media/upload",
        data={"chapter_id": mcid},
        files={"file": ("red.png", buf.getvalue(), "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and resp.headers["location"].endswith(f"/chapters/{mcid}/edit")
    [filename] = client.get(f"/api/notes/{nid}/media/list").json()["media"]
    url = f"/api/notes/{nid}/media/{filename}"
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": url})
    assert client.get(f"/api/notes/{nid}").json()["chapters"][1]["content"] == url
    assert (
        client.post(
            f"/notes/{nid}/media/{filename}/delete",
            data={"chapter_id": mcid},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert client.get(f"/api/notes/{nid}/media/list").json()["media"] == []
    bad = client.post(
        f"/notes/{nid}/media/upload",
        data={"chapter_id": mcid},
        files={"file": ("x.png", b"not an image", "image/png")},
    )
    assert bad.status_code == 400


def test_code_block_is_visible_without_scripts(client):
    note = _create(client)
    nid, root = note["id"], note["chapters"][0]["id"]
    client.post(
        f"/notes/{nid}/chapters", data={"block_type": "code", "position": "child", "ref_id": root}
    )
    cid = client.get(f"/api/notes/{nid}").json()["chapters"][1]["id"]
    client.post(
        f"/notes/{nid}/chapters/{cid}/edit", data={"content_text": "print(1)", "language": "python"}
    )
    html = client.get(f"/notes/{nid}").text
    assert (
        "<pre" in html
        and "print(1)" in html
        and "display:none" not in html.split("print(1)")[0][-300:]
    )


def test_add_note_chooser_is_a_page_and_a_fragment(client):
    page = client.get("/notes/new")
    assert _doc(page) and 'id="note-new"' in page.text
    frag = client.get("/notes/new", headers=HX)
    assert not _doc(frag) and 'class="row new-note-form"' in frag.text
    for form in re.findall(r"<form[^>]*>", frag.text):
        assert 'action="' in form and 'method="post"' in form, form


def test_import_json_from_the_chooser_redirects_to_the_new_note(client):
    src = _create(client, "Exported")
    doc = client.get("/api/export").content
    resp = client.post(
        "/notes/import",
        files={"file": ("notes.json", doc, "application/json")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    new_id = resp.headers["location"].rsplit("/", 1)[-1]
    assert new_id != src["id"]  # a new note, never a merge into the existing one
    assert client.get(f"/api/notes/{new_id}").json()["title"] == "Exported"
    assert len(client.get("/api/notes").json()) == 2


def test_create_and_import_close_the_add_note_overlay(client):
    # htmx appends the chooser to <body>; the refresh fragment does not cover it,
    # so the answer must carry the event app.js removes overlays on.
    created = client.post("/notes", data={"title": "Via htmx"}, headers=HX)
    assert created.status_code == 200
    assert created.headers.get("hx-trigger") == "close-note-settings"
    doc = client.get("/api/export").content
    imported = client.post(
        "/notes/import", files={"file": ("notes.json", doc, "application/json")}, headers=HX
    )
    assert imported.status_code == 200
    assert imported.headers.get("hx-trigger") == "close-note-settings"
    # control: a mutation that leaves the overlay alone does not send it
    nid = client.get("/api/notes").json()[0]["id"]
    renamed = client.post(f"/notes/{nid}/folder", data={"folder": "x"}, headers=HX)
    assert renamed.status_code == 200 and "hx-trigger" not in renamed.headers


def test_import_rejects_garbage_with_400(client):
    for name, body in (
        ("notes.json", b"not json"),
        ("x.zip", b"PK\x03\x04garbage"),
        ("e.json", b""),
    ):
        resp = client.post(
            "/notes/import", files={"file": (name, body, "application/octet-stream")}
        )
        assert resp.status_code == 400, name


def test_note_zip_export_round_trips_with_its_image(client):
    note = _create(client, "Zipped")
    nid, root = note["id"], note["chapters"][0]["id"]
    client.post(
        f"/notes/{nid}/chapters", data={"block_type": "media", "position": "child", "ref_id": root}
    )
    mcid = client.get(f"/api/notes/{nid}").json()["chapters"][1]["id"]
    buf = BytesIO()
    Image.new("RGB", (6, 4), "blue").save(buf, format="PNG")
    client.post(
        f"/notes/{nid}/media/upload",
        data={"chapter_id": mcid},
        files={"file": ("b.png", buf.getvalue(), "image/png")},
    )
    [filename] = client.get(f"/api/notes/{nid}/media/list").json()["media"]
    client.post(
        f"/notes/{nid}/chapters/{mcid}/media/select",
        data={"url": f"/api/notes/{nid}/media/{filename}"},
    )
    zipped = client.get(f"/notes/{nid}/export.zip")
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip"
    resp = client.post(
        "/notes/import",
        files={"file": ("zipped.zip", zipped.content, "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    new_id = resp.headers["location"].rsplit("/", 1)[-1]
    new = client.get(f"/api/notes/{new_id}").json()
    [new_file] = client.get(f"/api/notes/{new_id}/media/list").json()["media"]
    media_chapter = next(c for c in new["chapters"] if c["type"] == "media")
    assert media_chapter["content"] == f"/api/notes/{new_id}/media/{new_file}"
    assert new_file != filename  # minted, not copied from the archive
    assert client.get(media_chapter["content"]).status_code == 200


def test_unknown_note_is_404(client):
    assert client.get("/notes/does-not-exist").status_code == 404
    assert client.get("/does-not-exist").status_code == 404  # no catch-all swallows it


def test_notes_pane_toggles_without_scripts(client):
    """The pane is a <details> with a <summary>: native collapse, no script required."""
    html = client.get("/").text
    m = re.search(r'<details id="note-list"[^>]*>', html)
    assert m and " open" in m.group(0)
    assert re.search(r'<summary class="pane-header"', html)
    assert "<noscript>" in html


def _off_the_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return True
    return False


def test_import_and_upload_decode_off_the_event_loop(client, monkeypatch):
    # Image decoding is CPU-bound; run on the loop it stalls every other request.
    seen = {}
    real_import, real_process = pages.import_bundle, pages.process_uploaded_image

    def spy(name, real):
        def wrapper(*args):
            seen[name] = _off_the_event_loop()
            return real(*args)

        return wrapper

    monkeypatch.setattr(pages, "import_bundle", spy("pages import", real_import))
    monkeypatch.setattr(api, "import_bundle", spy("api import", real_import))
    monkeypatch.setattr(pages, "process_uploaded_image", spy("upload", real_process))
    nid = _create(client, "Loop")["id"]
    doc = client.get("/api/export").content
    for url in ("/notes/import", "/api/import"):
        assert client.post(url, files={"file": ("n.json", doc, "application/json")}).is_success
    png = BytesIO()
    Image.new("RGB", (4, 4)).save(png, format="PNG")
    resp = client.post(
        f"/notes/{nid}/media/upload",
        files={"file": ("p.png", png.getvalue(), "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303  # stored; the redirect target is not under test
    assert seen == {"pages import": True, "api import": True, "upload": True}


def test_export_of_a_non_ascii_title_downloads_with_its_name(client):
    # The title 'Заметки' was a UnicodeEncodeError (500): headers are latin-1.
    nid = _create(client, 'Заметки "q"')["id"]
    resp = client.get(f"/notes/{nid}/export.zip")
    assert resp.status_code == 200
    cd = resp.headers["content-disposition"]
    name = client.get(f"/api/notes/{nid}").json()["name"]
    assert cd.startswith('attachment; filename="')
    assert f"filename*=UTF-8''{quote(name + '.zip', safe='')}" in cd
    fallback = cd.split('filename="', 1)[1].split('"', 1)[0]
    assert fallback.isascii() and '"' not in fallback


def test_stray_non_ascii_media_downloads_with_its_name(client, service):
    note = _create(client, "Stray")
    service.repo.save_media(note["name"], "файл.bin", b"\x00\x01")
    resp = client.get(f"/api/notes/{note['id']}/media/{quote('файл.bin')}")
    assert resp.status_code == 200
    assert "filename*=utf-8''" + quote("файл.bin") in resp.headers["content-disposition"]


def test_an_import_with_a_missing_image_says_so_on_the_note_page(client):
    # 20261019-011: skipped images went to the log only; the user saw a clean import.
    note = {
        "id": "n1", "name": "Trip", "title": "Trip", "tags": [],
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        "chapters": [
            {"id": "c1", "title": "Ch", "content": "", "order": 0, "parent_id": None, "type": "chapter"},
            {"id": "c2", "title": "", "content": "/api/notes/n1/media/gone.png", "order": 1, "parent_id": "c1", "type": "media"},
        ],
    }  # fmt: skip
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Trip/Trip.json", json.dumps(note))
    files = {"file": ("Trip.zip", buf.getvalue(), "application/zip")}
    resp = client.post("/notes/import", files=files, follow_redirects=False)
    assert resp.status_code == 303
    page = client.get(resp.headers["location"]).text
    assert 'class="import-missing"' in page and "gone.png" in page
    assert "Image missing from the import: gone.png" in page
    fragment = client.post("/notes/import", files=files, headers={"hx-request": "true"}).text
    assert 'class="import-missing"' in fragment  # the htmx path re-renders the editor with it
    api_resp = client.post("/api/import", files=files).json()
    assert api_resp["missing"] == ["gone.png"]


def test_harness_control_a_complete_note_shows_no_missing_notice(client):
    nid = _create(client, "Complete")["id"]
    assert "import-missing" not in client.get(f"/notes/{nid}").text


def test_theme_is_a_cookie_the_page_reads(client):
    nid = _create(client, "Themed")["id"]
    # no cookie: no data-theme, so the CSS follows the system preference
    assert "data-theme=" not in client.get("/").text
    resp = client.post(
        "/theme", data={"theme": "light", "next": f"/notes/{nid}"}, follow_redirects=False
    )
    assert resp.status_code == 303 and resp.headers["location"] == f"/notes/{nid}"
    assert client.cookies.get("theme") == "light"
    assert '<html lang="en" data-theme="light">' in client.get("/").text
    client.post("/theme", data={"theme": "system"}, follow_redirects=False)
    assert "data-theme=" not in client.get("/").text


def test_the_theme_switch_returns_to_the_page_it_was_on(client):
    # Every page is sent with Referrer-Policy: no-referrer, so a browser posts
    # /theme with no Referer; the form itself names the page to return to.
    nid = _create(client, "Back here")["id"]
    page = client.get(f"/notes/{nid}?x=1")
    assert page.headers["referrer-policy"] == "no-referrer"  # the premise
    assert f'name="next" value="/notes/{nid}?x=1"' in page.text
    resp = client.post(
        "/theme", data={"theme": "dark", "next": f"/notes/{nid}?x=1"}, follow_redirects=False
    )
    assert resp.headers["location"] == f"/notes/{nid}?x=1"


def test_theme_ignores_unknown_values_and_foreign_targets(client):
    client.cookies.set("theme", 'x" onload="alert(1)')
    assert "data-theme=" not in client.get("/").text  # only light/dark are echoed
    for target in (
        "https://evil.example/phish",
        "//evil.example/x",
        "/\\evil.example/x",
        "/\t/evil.example/x",  # browsers drop the tab and read //evil.example
        "javascript:alert(1)",
        "notes/relative",
        "",
    ):
        resp = client.post("/theme", data={"theme": "dark", "next": target}, follow_redirects=False)
        assert resp.headers["location"] == "/", target
