"""The HTML routes. Every other test file talks to /api or the service; these
are the pages a browser loads, so a template-signature or layout regression
shows up here and nowhere else."""


def _create(client, title="Page test"):
    resp = client.post("/notes", data={"title": title})
    assert resp.status_code == 200
    return resp


def test_home_is_a_full_document(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text.lstrip().lower().startswith("<!doctype html>")
    assert 'rel="stylesheet"' in resp.text


def test_create_note_form_post_returns_fragment_and_persists(client):
    resp = _create(client, "Formed")
    # today: an HTMX out-of-band fragment, not a document (no-JS gap, ticketed)
    assert "<!doctype" not in resp.text.lower()
    assert "Formed" in resp.text
    notes = client.get("/api/notes").json()
    assert [n["title"] for n in notes] == ["Formed"]
    assert len(notes[0]["chapters"]) == 1


def test_note_page_by_id_and_by_name(client):
    _create(client, "Deep Link")
    note = client.get("/api/notes").json()[0]
    for url in (f"/notes/{note['id']}", f"/{note['name']}"):
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert resp.text.lstrip().lower().startswith("<!doctype html>")
        assert "Deep Link" in resp.text
        assert 'class="chapter-section' in resp.text


def test_htmx_request_gets_fragment(client):
    _create(client)
    note = client.get("/api/notes").json()[0]
    resp = client.get(f"/notes/{note['id']}", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "<!doctype" not in resp.text.lower()
    assert 'hx-swap-oob' in resp.text


def test_chapter_edit_form_renders(client):
    _create(client)
    note = client.get("/api/notes").json()[0]
    cid = note["chapters"][0]["id"]
    resp = client.get(f"/notes/{note['id']}/chapters/{cid}/edit")
    assert resp.status_code == 200
    assert 'class="chapter-edit-form"' in resp.text


def test_unknown_note_is_404(client):
    assert client.get("/notes/does-not-exist").status_code == 404
    assert client.get("/does-not-exist").status_code == 404
