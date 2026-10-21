"""The HTML routes, driven the way a browser without JavaScript drives them:
plain form POSTs with no HX-Request header must redirect to a full page, and
the same POSTs with the header must return the htmx fragment."""

import asyncio
import base64
import json
import re
import threading
import zipfile
from io import BytesIO
from urllib.parse import quote

import pytest
from PIL import Image

from app.routes import api
from app.routes import pages
from app.schemas import NoteUpdate
from app.services import notes as notes_mod

HX = {"HX-Request": "true"}
NOT_SHOWN = "Image not shown: {} is not stored in this note. Upload or pick a copy here."


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
    client.post(
        f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"}
    )  # free it
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


def _mixed_zip() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.json", json.dumps({"version": "1.0.0", "notes": []}))
        zf.writestr("Alpha/Alpha.json", "{}")
    return buf.getvalue()


def test_a_refused_import_says_why_on_the_form_without_scripts(client):
    # 20261019-069: the refusal was a bare JSON body without scripts, and nothing with them.
    files = {"file": ("mixed.zip", _mixed_zip(), "application/zip")}
    resp = client.post("/notes/import", files=files, follow_redirects=False)
    assert resp.status_code == 400
    page = resp.text
    assert 'class="row import-note-form"' in page  # the form is there to try again
    error = page[page.index('id="import-error"') :].split("</p>")[0]
    assert "hidden" not in error and "notes.json and also Alpha/Alpha.json" in error


def test_a_refused_import_says_why_in_the_overlay_with_htmx(client):
    files = {"file": ("mixed.zip", _mixed_zip(), "application/zip")}
    resp = client.post("/notes/import", files=files, headers={"hx-request": "true"})
    assert resp.status_code == 400
    assert 'id="import-error"' in resp.text and 'hx-swap-oob="true"' in resp.text
    assert "notes.json and also Alpha/Alpha.json" in resp.text and "hidden" not in resp.text
    assert client.get("/api/notes").json() == []  # nothing was imported


def test_harness_control_the_import_form_has_a_hidden_empty_error(client):
    page = client.get("/notes/new").text
    error = page[page.index('id="import-error"') :].split("</p>")[0]
    assert " hidden" in error and error.endswith(">")


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
        "////evil.example/x",  # no netloc, but the path left is //evil.example/x
        "/\\evil.example/x",
        "/\t/evil.example/x",  # browsers drop the tab and read //evil.example
        "javascript:alert(1)",
        "notes/relative",
        "",
    ):
        resp = client.post("/theme", data={"theme": "dark", "next": target}, follow_redirects=False)
        assert resp.headers["location"] == "/", target


def _note_with_picked_image(client, title="Pics"):
    note = _create(client, title)
    nid, root = note["id"], note["chapters"][0]["id"]
    client.post(
        f"/notes/{nid}/chapters", data={"block_type": "media", "position": "child", "ref_id": root}
    )
    mcid = client.get(f"/api/notes/{nid}").json()["chapters"][1]["id"]
    buf = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    client.post(
        f"/notes/{nid}/media/upload",
        data={"chapter_id": mcid},
        files={"file": ("red.png", buf.getvalue(), "image/png")},
    )
    [filename] = client.get(f"/api/notes/{nid}/media/list").json()["media"]
    url = f"/api/notes/{nid}/media/{filename}"
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": url})
    return nid, mcid, filename, url


def test_an_image_a_block_shows_cannot_be_deleted(client):
    # 20261014-188: deleting it left the block requesting a file that was gone (404).
    nid, mcid, filename, _ = _note_with_picked_image(client)
    page = client.get(f"/notes/{nid}/chapters/{mcid}/edit").text
    assert f"/media/{filename}/delete" not in page
    assert 'class="media-in-use" title="Used by Pics / ' in page
    resp = client.post(
        f"/notes/{nid}/media/{filename}/delete", data={"chapter_id": mcid}, follow_redirects=False
    )
    assert resp.status_code == 409 and "is used by Pics / " in resp.text
    assert client.get(f"/api/notes/{nid}/media/list").json()["media"] == [filename]


def test_an_image_another_note_shows_cannot_be_deleted_either(client):
    nid, mcid, filename, url = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"})
    other = _create(client, "Elsewhere")
    root = other["chapters"][0]["id"]
    client.post(
        f"/notes/{other['id']}/chapters",
        data={"block_type": "media", "position": "child", "ref_id": root},
    )
    ocid = client.get(f"/api/notes/{other['id']}").json()["chapters"][1]["id"]
    client.post(f"/notes/{other['id']}/chapters/{ocid}/media/select", data={"url": url})
    resp = client.post(f"/notes/{nid}/media/{filename}/delete", data={"chapter_id": mcid})
    assert resp.status_code == 409 and "Elsewhere / " in resp.text


def test_harness_control_an_unused_image_keeps_its_delete(client):
    nid, mcid, filename, _ = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"})
    page = client.get(f"/notes/{nid}/chapters/{mcid}/edit").text
    assert f"/media/{filename}/delete" in page and "media-in-use" not in page


def test_a_refused_delete_without_scripts_is_the_edit_page_saying_why(client):
    # 20261020-084: a plain POST got a raw {"detail": ...} page.
    nid, mcid, filename, _ = _note_with_picked_image(client)
    resp = client.post(
        f"/notes/{nid}/media/{filename}/delete", data={"chapter_id": mcid}, follow_redirects=False
    )
    assert resp.status_code == 409 and _doc(resp)
    assert '<p class="import-missing media-error" role="alert">' in resp.text
    assert f"{filename} is used by Pics / " in resp.text
    # the gallery is drawn as it is now: the file shows as in use, with no delete
    assert 'class="media-in-use"' in resp.text
    assert f'action="/notes/{nid}/media/{filename}/delete"' not in resp.text


def test_a_refused_delete_with_htmx_is_the_gallery_saying_why(client):
    # 20261020-084: htmx dropped the 409's body, so a stale gallery showed nothing.
    nid, mcid, filename, _ = _note_with_picked_image(client)
    resp = client.post(
        f"/notes/{nid}/media/{filename}/delete", data={"chapter_id": mcid}, headers=HX
    )
    assert resp.status_code == 409 and not _doc(resp)
    assert 'class="media-gallery"' in resp.text and 'class="media-in-use"' in resp.text
    assert f"{filename} is used by Pics / " in resp.text


def test_app_js_swaps_the_refused_media_delete(client):
    # The fragment above is only seen if app.js lets htmx swap a 409; the path it
    # tests must be the one the gallery's delete form posts to.
    js = client.get("/static/js/app.js").text
    m = re.search(r"const MEDIA_DELETE = /(.+)/;", js)
    assert m and "status === 409" in js
    nid, mcid, _, _ = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"})
    page = client.get(f"/notes/{nid}/chapters/{mcid}/edit").text
    [action] = re.findall(r'hx-post="(/notes/[^"]+/media/[^"]+/delete)"', page)
    assert re.fullmatch(m.group(1), action)
    assert not re.fullmatch(m.group(1), f"/notes/{nid}/media/upload")


def test_a_url_with_a_query_or_a_host_still_counts_as_a_use(client):
    # 20261020-084: the match was exact, so a PUT-set variant displayed the file
    # but did not protect it.
    nid, mcid, filename, url = _note_with_picked_image(client)
    for shown in (url + "?v=2", "http://127.0.0.1:8000" + url, url.replace(".", "%2E")):
        client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": shown})
        resp = client.post(f"/notes/{nid}/media/{filename}/delete", data={"chapter_id": mcid})
        assert resp.status_code == 409, shown
    assert client.get(f"/api/notes/{nid}/media/list").json()["media"] == [filename]


def test_the_gallery_reads_the_notes_once_however_many_files(client, service, monkeypatch):
    # 20261020-084: _media_users ran list_notes() per file, files x notes reads per render.
    nid, mcid, _, _ = _note_with_picked_image(client)
    for colour in ("green", "blue"):
        buf = BytesIO()
        Image.new("RGB", (4, 4), colour).save(buf, format="PNG")
        client.post(
            f"/notes/{nid}/media/upload",
            data={"chapter_id": mcid},
            files={"file": (f"{colour}.png", buf.getvalue(), "image/png")},
        )
    assert len(client.get(f"/api/notes/{nid}/media/list").json()["media"]) == 3
    calls = []
    real = type(service).list_notes
    monkeypatch.setattr(type(service), "list_notes", lambda self: calls.append(1) or real(self))
    client.get(f"/notes/{nid}/chapters/{mcid}/edit", headers=HX)
    assert len(calls) == 1


def _borrowed_image(client):
    """Pics owns an image that a block in Elsewhere shows; Pics shows another file."""
    nid, mcid, filename, url = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"})
    other = _create(client, "Elsewhere")
    root = other["chapters"][0]["id"]
    client.post(
        f"/notes/{other['id']}/chapters",
        data={"block_type": "media", "position": "child", "ref_id": root},
    )
    ocid = client.get(f"/api/notes/{other['id']}").json()["chapters"][1]["id"]
    client.post(f"/notes/{other['id']}/chapters/{ocid}/media/select", data={"url": url})
    return nid, filename, other["id"]


def test_a_note_whose_image_another_note_shows_is_not_deleted(client):
    # 20261020-085: the delete removed the note's media/ folder under the other block.
    nid, filename, _ = _borrowed_image(client)
    resp = client.post(f"/notes/{nid}/delete", follow_redirects=False)
    assert resp.status_code == 409 and _doc(resp)
    assert '<p id="delete-error" class="import-missing delete-error" role="alert">' in resp.text
    assert f"{filename}: Elsewhere / " in resp.text
    assert 'class="note-settings-overlay"' in resp.text  # the settings, where the delete is
    assert client.get(f"/api/notes/{nid}/media/list").json()["media"] == [filename]


def test_a_refused_note_delete_with_htmx_is_the_reason_out_of_band(client):
    nid, filename, _ = _borrowed_image(client)
    resp = client.post(f"/notes/{nid}/delete", headers=HX)
    assert resp.status_code == 409 and not _doc(resp)
    assert 'id="delete-error"' in resp.text and 'hx-swap-oob="true"' in resp.text
    assert f"{filename}: Elsewhere / " in resp.text
    # the overlay it swaps into has the element, hidden until there is a reason
    page = client.get(f"/notes/{nid}/settings", headers=HX).text
    assert re.search(r'<p id="delete-error"[^>]* hidden>', page)


def test_the_api_refuses_the_same_delete(client):
    nid, filename, _ = _borrowed_image(client)
    resp = client.delete(f"/api/notes/{nid}")
    assert resp.status_code == 409 and f"{filename}: Elsewhere / " in resp.json()["detail"]
    assert client.get(f"/api/notes/{nid}").status_code == 200


def test_harness_control_a_note_showing_only_its_own_images_is_deleted(client):
    # The note's own blocks go with it, so they do not hold the delete.
    nid, _, _, _ = _note_with_picked_image(client)
    resp = client.post(f"/notes/{nid}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert client.get(f"/api/notes/{nid}").status_code == 404


def test_once_the_other_block_picks_another_image_the_note_is_deleted(client):
    nid, _, oid = _borrowed_image(client)
    ocid = client.get(f"/api/notes/{oid}").json()["chapters"][1]["id"]
    client.post(f"/notes/{oid}/chapters/{ocid}/media/select", data={"url": "/static/none.png"})
    assert client.post(f"/notes/{nid}/delete", follow_redirects=False).status_code == 303


def test_app_js_swaps_the_refused_note_delete(client):
    js = client.get("/static/js/app.js").text
    m = re.search(r"const NOTE_DELETE = /(.+)/;", js)
    assert m and "NOTE_DELETE.test(path)" in js
    note = _create(client, "Js")
    page = client.get(f"/notes/{note['id']}/settings", headers=HX).text
    [action] = re.findall(r'hx-post="(/notes/[^"]+/delete)"', page)
    assert re.fullmatch(m.group(1), action)
    assert not re.fullmatch(m.group(1), f"/notes/{note['id']}/media/x.png/delete")


def test_an_imported_external_image_is_a_visible_placeholder_not_a_broken_image(client):
    # 20261014-140: the URL was kept, and img-src 'self' blocked it without a word.
    note = {
        "id": "x1",
        "name": "Ext",
        "title": "Ext",
        "chapters": [
            {"id": "c1", "title": "Pics", "content": "", "order": 0, "type": "chapter"},
            {
                "id": "c2",
                "title": "",
                "content": "https://example.org/a.png",
                "order": 0,
                "parent_id": "c1",
                "type": "media",
            },
        ],
    }
    body = json.dumps(note).encode()
    resp = client.post("/notes/import", files={"file": ("ext.json", body, "application/json")})
    assert resp.status_code == 200 and _doc(resp)
    assert "1 image is not stored in this note and not shown" in resp.text
    assert NOT_SHOWN.format("https://example.org/a.png") in resp.text
    assert 'src="https://example.org' not in resp.text
    assert "img-src 'self' data:" in resp.headers["content-security-policy"]  # unchanged


def _theme_next(html):
    [back] = re.findall(r'<input type="hidden" name="next" value="([^"]*)">', html)
    return back


def test_the_theme_switch_on_a_page_answered_to_a_post_returns_to_a_get_page(client):
    # 20261020-095: next was the POST's own path, so Light/Dark answered 405.
    resp = client.post("/notes/import", files={"file": ("x.json", b"not json", "text/plain")})
    assert resp.status_code == 400 and _theme_next(resp.text) == "/notes/new"
    nid, mcid, filename, _ = _note_with_picked_image(client)
    resp = client.post(f"/notes/{nid}/media/{filename}/delete", data={"chapter_id": mcid})
    assert resp.status_code == 409
    assert _theme_next(resp.text) == f"/notes/{nid}/chapters/{mcid}/edit"
    bid, _, _ = _borrowed_image(client)
    resp = client.post(f"/notes/{bid}/delete")
    assert resp.status_code == 409 and _theme_next(resp.text) == f"/notes/{bid}/settings"
    # each one is a page a GET can open
    for back in ("/notes/new", f"/notes/{nid}/chapters/{mcid}/edit", f"/notes/{bid}/settings"):
        assert client.get(back).status_code == 200, back


def test_harness_control_a_get_page_still_names_itself(client):
    nid = _create(client, "Self")["id"]
    assert _theme_next(client.get(f"/notes/{nid}?x=1").text) == f"/notes/{nid}?x=1"


def test_an_external_image_set_after_import_is_a_placeholder_not_a_broken_image(client):
    # 20261014-140 leftover: a URL set through the select form or PUT still drew an
    # <img> that img-src 'self' blocks.
    nid, mcid, _, url = _note_with_picked_image(client)
    for external in (
        "https://example.org/a.png",
        "http://example.org/a.png",
        "//example.org/a.png",
    ):
        client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": external})
        page = client.get(f"/notes/{nid}").text
        assert NOT_SHOWN.format(external) in page, external
        assert f'src="{external}"' not in page, external
    # control: the note's own image is still drawn
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": url})
    page = client.get(f"/notes/{nid}").text
    assert f'<img src="{url}"' in page and "Image not shown" not in page


def _import_media(client, content, title="Kinds"):
    note = {
        "id": "k1",
        "name": title,
        "title": title,
        "chapters": [
            {"id": "c1", "title": "Pics", "content": "", "order": 0, "type": "chapter"},
            {
                "id": "c2",
                "title": "",
                "content": content,
                "order": 0,
                "parent_id": "c1",
                "type": "media",
            },
        ],
    }
    body = json.dumps(note).encode()
    resp = client.post("/notes/import", files={"file": ("k.json", body, "application/json")})
    assert resp.status_code == 200
    imported = client.get("/api/notes").json()[-1]
    return imported, resp.text


@pytest.mark.parametrize(
    "external", ["HTTP://example.org/a.png", "  https://example.org/a.png", "/\\example.org/a.png"]
)
def test_an_external_image_reads_the_same_imported_or_set_later(client, external):
    # 20261021-009: imported it was "missing from the import" and counted; set later,
    # another wording and not counted. Now one rule and one wording, both paths.
    imported, page = _import_media(client, external)
    stored = imported["chapters"][1]["content"]
    assert stored == external  # kept, never fetched
    assert NOT_SHOWN.format(stored) in page and "1 image is not stored in this note" in page
    nid, mcid, _, _ = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": external})
    later = client.get(f"/notes/{nid}").text
    assert NOT_SHOWN.format(external) in later and "1 image is not stored in this note" in later
    assert f'src="{external}"' not in page + later


def test_the_edit_form_does_not_draw_an_external_image_either(client):
    # 20261021-009: chapter_edit_form.html drew <img src="{{ chapter.content }}"> as is.
    nid, mcid, _, url = _note_with_picked_image(client)
    client.post(
        f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "https://example.org/a.png"}
    )
    form = client.get(f"/notes/{nid}/chapters/{mcid}/edit", headers=HX).text
    assert 'src="https://example.org' not in form
    assert NOT_SHOWN.format("https://example.org/a.png") in form
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": url})
    form = client.get(f"/notes/{nid}/chapters/{mcid}/edit", headers=HX).text
    assert f'<img src="{url}" alt="preview">' in form  # control: its own image is drawn


def test_an_inline_data_image_is_re_encoded_on_import_never_kept_as_received(client):
    # 20261021-009: import dropped data:, which img-src data: would show. Review of
    # ff02f92: keeping it verbatim let data:image/svg+xml through, against charter R3.
    # Now it goes through the upload pipeline like any image in a bundle.
    buf = BytesIO()
    Image.new("RGB", (4, 4), "green").save(buf, format="PNG")
    png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    imported, page = _import_media(client, png, "Inline")
    stored = imported["chapters"][1]["content"]
    assert stored.startswith(f"/api/notes/{imported['id']}/media/") and stored.endswith(".webp")
    assert client.get(stored).status_code == 200 and f'<img src="{stored}"' in page
    assert "data:" not in json.dumps(imported)


@pytest.mark.parametrize(
    "inline",
    [
        "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>",
        "data:image/svg+xml;base64,"
        + base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'/>").decode(),
        "DATA:image/png;base64,not-base64!",
        "data:image/png;base64," + base64.b64encode(b"just bytes, not an image").decode(),
        "data:image/png",
    ],
)
def test_an_inline_image_that_is_not_a_raster_becomes_a_placeholder(client, inline):
    imported, page = _import_media(client, inline, "Refused")
    assert imported["chapters"][1]["content"] == "missing:inline image"
    assert "Image missing from the import: inline image" in page
    assert "svg" not in json.dumps(imported).lower()  # nothing of it kept in the note
    assert client.get(f"/api/notes/{imported['id']}/media/list").json()["media"] == []


def test_javascript_is_still_dropped_on_import(client):
    imported, _ = _import_media(client, "JaVaScRiPt:alert(1)", "Script")
    assert imported["chapters"][1]["content"] == ""


def test_a_pick_waiting_on_a_delete_does_not_link_the_file_it_removed(client, service, monkeypatch):
    # 20261021-010: the in-use check and the delete took the lock separately, so a pick
    # saved between them was deleted anyway. Now the delete holds one lock for both, and
    # the pick, checked under the same lock, finds the file gone instead of linking it.
    nid, mcid, filename, url = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"})
    checked, release = threading.Event(), threading.Event()
    real = notes_mod.media_users

    def slow_users(*a):
        users = real(*a)
        checked.set()  # the check has run; the delete has not
        release.wait(5)
        return users

    monkeypatch.setattr(notes_mod, "media_users", slow_users)
    out = {}
    deleter = threading.Thread(
        target=lambda: out.update(d=service.delete_media_unless_used(nid, filename))
    )
    deleter.start()
    assert checked.wait(5)
    picker = threading.Thread(target=lambda: out.update(p=service.pick_media(nid, mcid, url)))
    picker.start()
    picker.join(0.3)
    assert picker.is_alive()  # the pick waits for the delete's lock hold
    release.set()
    deleter.join(5)
    picker.join(5)
    assert out["d"][2] is True  # deleted
    assert out["p"][1] is False  # and the pick was refused, not saved
    block = next(c for c in service.get_note(nid).chapters if c.id == mcid)
    assert block.content == "/static/none.png"


def test_a_refused_pick_says_why_with_scripts_or_without(client):
    nid, mcid, filename, url = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"})
    client.post(f"/notes/{nid}/media/{filename}/delete", data={"chapter_id": mcid})
    reason = "That image was deleted. Pick another or upload one."
    plain = client.post(
        f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": url}, follow_redirects=False
    )
    assert plain.status_code == 409 and _doc(plain) and reason in plain.text
    hx = client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": url}, headers=HX)
    assert hx.status_code == 409 and not _doc(hx) and reason in hx.text
    assert hx.headers["hx-retarget"] == f"#media-gallery-{mcid}"
    assert hx.headers["hx-reswap"] == "innerHTML"
    js = client.get("/static/js/app.js").text
    m = re.search(r"const MEDIA_SELECT = /(.+)/;", js)
    assert m and "MEDIA_SELECT.test(path)" in js
    assert re.fullmatch(m.group(1), f"/notes/{nid}/chapters/{mcid}/media/select")


def test_harness_control_a_pick_of_an_existing_or_foreign_url_is_saved(client, service):
    nid, mcid, _, url = _note_with_picked_image(client)
    for shown in ("/static/none.png", url):
        resp = client.post(
            f"/notes/{nid}/chapters/{mcid}/media/select",
            data={"url": shown},
            follow_redirects=False,
        )
        assert resp.status_code == 303, shown
        assert next(c for c in service.get_note(nid).chapters if c.id == mcid).content == shown


@pytest.mark.parametrize("hx", [True, False])
def test_a_refused_delete_reads_the_notes_once(client, service, monkeypatch, hx):
    # 20261021-010: the check, _media_files and _page each read every note.
    nid, mcid, filename, _ = _note_with_picked_image(client)
    bid, _, _ = _borrowed_image(client)
    calls = []
    repo = type(service.repo)
    real = repo.list_notes
    monkeypatch.setattr(repo, "list_notes", lambda self: calls.append(1) or real(self))
    headers = HX if hx else {}
    r = client.post(
        f"/notes/{nid}/media/{filename}/delete", data={"chapter_id": mcid}, headers=headers
    )
    assert r.status_code == 409 and len(calls) == 1, len(calls)
    calls.clear()
    assert client.post(f"/notes/{bid}/delete", headers=headers).status_code == 409
    assert len(calls) == 1, len(calls)


def _put_media(client, nid, mcid, url):
    note = client.get(f"/api/notes/{nid}").json()
    for c in note["chapters"]:
        if c["id"] == mcid:
            c["content"] = url
    return client.put(f"/api/notes/{nid}", json={"chapters": note["chapters"]})


def test_put_refuses_a_media_block_naming_a_deleted_image(client, service):
    # 20261021-016: only the select form checked; PUT wrote any URL.
    nid, mcid, filename, url = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"})
    client.post(f"/notes/{nid}/media/{filename}/delete", data={"chapter_id": mcid})
    for gone in (url, url + "?v=2", f"/api/notes/{nid}/media/nothing.webp"):
        resp = _put_media(client, nid, mcid, gone)
        assert resp.status_code == 409, gone
        assert f"{mcid}: {gone}" in resp.json()["detail"]
    block = next(c for c in service.get_note(nid).chapters if c.id == mcid)
    assert block.content == "/static/none.png"


def test_harness_control_put_saves_existing_foreign_and_unchanged_urls(client, service):
    nid, mcid, filename, url = _note_with_picked_image(client)
    for shown in ("/static/none.png", "https://example.org/a.png", url):
        assert _put_media(client, nid, mcid, shown).status_code == 200, shown
    # The block now names an image deleted underneath it. A save that leaves that
    # URL as it was is not refused: a note holding a broken link stays editable.
    service.repo.delete_media(service.get_note(nid).name, filename)
    chapters = client.get(f"/api/notes/{nid}").json()["chapters"]
    resp = client.put(f"/api/notes/{nid}", json={"title": "Renamed", "chapters": chapters})
    assert resp.status_code == 200 and resp.json()["title"] == "Renamed"


def test_a_put_waiting_on_a_delete_does_not_link_the_file_it_removed(client, service, monkeypatch):
    nid, mcid, filename, url = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"})
    checked, release = threading.Event(), threading.Event()
    real = notes_mod.media_users

    def slow_users(*a):
        users = real(*a)
        checked.set()
        release.wait(5)
        return users

    monkeypatch.setattr(notes_mod, "media_users", slow_users)
    chapters = [
        {**c.model_dump(mode="json"), "content": url} if c.id == mcid else c.model_dump(mode="json")
        for c in service.get_note(nid).chapters
    ]
    out = {}
    deleter = threading.Thread(
        target=lambda: out.update(d=service.delete_media_unless_used(nid, filename))
    )
    deleter.start()
    assert checked.wait(5)
    putter = threading.Thread(
        target=lambda: out.update(p=service.update_note_checked(nid, NoteUpdate(chapters=chapters)))
    )
    putter.start()
    putter.join(0.3)
    assert putter.is_alive()  # waits for the delete's lock hold
    release.set()
    deleter.join(5)
    putter.join(5)
    assert out["d"][2] is True and out["p"][1] == [f"{mcid}: {url}"]


def test_a_delete_waiting_on_a_put_sees_the_link_it_saved(client, service, monkeypatch):
    # The other order: the PUT has checked the file exists and not yet written. A
    # delete arriving then must wait, and then refuse: the block now shows the file.
    nid, mcid, filename, url = _note_with_picked_image(client)
    client.post(f"/notes/{nid}/chapters/{mcid}/media/select", data={"url": "/static/none.png"})
    checked, release = threading.Event(), threading.Event()
    real = type(service)._media_exists

    def slow_exists(self, *a):
        found = real(self, *a)
        checked.set()  # checked; not yet written
        release.wait(5)
        return found

    monkeypatch.setattr(type(service), "_media_exists", slow_exists)
    chapters = [
        {**c.model_dump(mode="json"), "content": url} if c.id == mcid else c.model_dump(mode="json")
        for c in service.get_note(nid).chapters
    ]
    out = {}
    putter = threading.Thread(
        target=lambda: out.update(p=service.update_note_checked(nid, NoteUpdate(chapters=chapters)))
    )
    putter.start()
    assert checked.wait(5)
    deleter = threading.Thread(
        target=lambda: out.update(d=service.delete_media_unless_used(nid, filename))
    )
    deleter.start()
    deleter.join(0.3)
    assert deleter.is_alive()  # waits for the PUT's lock hold
    release.set()
    putter.join(5)
    deleter.join(5)
    assert out["p"][1] == [] and out["d"][1] and out["d"][2] is False  # refused, kept
    assert filename in service.repo.list_media(service.get_note(nid).name)


def test_the_page_names_a_placeholder_the_way_media_kind_reads_it(client):
    # 20261021-013 review: placeholder and notice cut content.strip()[8:].
    nid, mcid, _, _ = _note_with_picked_image(client)
    assert _put_media(client, nid, mcid, "mis\tsing:a.png").status_code == 200
    page = client.get(f"/notes/{nid}").text
    assert "Image missing from the import: a.png<" in page
    assert "could not be imported and is not in this note:\n  a.png." in page
