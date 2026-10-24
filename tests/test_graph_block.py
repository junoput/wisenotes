"""The graph block, slice 1 of 20261022-064: a text definition, checked on save (20261024-003)."""

import html

from markupsafe import escape

from app.blocks import BLOCKS
from app.schemas import NoteCreate

HX = {"HX-Request": "true"}
GOOD = "view 2d  x -5..5  y -3..3\na = slider(0, 5, value 1)\nf(x) = a*sin(x)\nP = (1, f(1))"
BAD = "a = slider(5, 1)\nf(x) = 2x"
SENTINEL = '<img src=x onerror="alert(1)">'


def graph_note(service, content=""):
    chapters = [
        {"id": "ch", "title": "Top", "order": 0, "type": "chapter"},
        {
            "id": "g",
            "title": "",
            "order": 0,
            "type": "graph",
            "parent_id": "ch",
            "content": content,
        },
    ]
    return service.create_note(NoteCreate(title="Graphs", chapters=chapters))


def stored(service, note_id):
    return next(c for c in service.get_note(note_id).chapters if c.id == "g")


def test_graph_is_in_the_picker(client, service):
    assert BLOCKS["graph"].show_in_picker
    note = graph_note(service)
    assert 'value="graph"' in client.get(f"/notes/{note.id}").text


def test_a_graph_block_can_be_added_under_a_chapter(client, service):
    note = graph_note(service)
    r = client.post(
        f"/notes/{note.id}/chapters",
        data={"block_type": "graph", "position": "child", "ref_id": "ch"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert [c.type for c in service.get_note(note.id).chapters].count("graph") == 2


def test_without_scripts_the_block_shows_its_definition(client, service):
    note = graph_note(service, GOOD)
    page = client.get(f"/notes/{note.id}").text
    assert '<pre class="graph-spec">' + html.escape(GOOD, quote=False) + "</pre>" in page
    assert "Graph definition" in page


def test_a_good_definition_is_saved(client, service):
    note = graph_note(service)
    r = client.post(
        f"/notes/{note.id}/chapters/g/edit",
        data={"title": "Wave", "content_text": GOOD},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert stored(service, note.id).content == GOOD


def test_a_bad_definition_is_refused_by_line_and_kept_in_the_form(client, service):
    note = graph_note(service, GOOD)
    r = client.post(
        f"/notes/{note.id}/chapters/g/edit",
        data={"title": "Wave", "content_text": BAD + "\n# " + SENTINEL},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "Not saved. Fix these lines and save again:" in r.text
    assert "line 1: the slider must go from low to high" in r.text
    assert "line 2: two values without an operator between them" in r.text
    # the text as typed, escaped, in the form, so nothing typed is lost
    assert str(escape(BAD + "\n# " + SENTINEL)) in r.text
    assert SENTINEL not in r.text
    assert 'value="Wave"' in r.text
    assert stored(service, note.id).content == GOOD  # nothing was written


def test_with_htmx_the_refusal_replaces_only_the_open_form(client, service):
    note = graph_note(service, GOOD)
    r = client.post(f"/notes/{note.id}/chapters/g/edit", data={"content_text": BAD}, headers=HX)
    assert r.status_code == 400
    assert r.headers["HX-Retarget"] == "#edit-g"
    assert r.headers["HX-Reswap"] == "outerHTML"
    assert 'id="edit-g"' in r.text and "line 1:" in r.text
    assert "<html" not in r.text


def test_the_check_is_only_for_graph_blocks(client, service):
    # the quiet side: a text block keeps any text, including a bad graph definition
    note = graph_note(service)
    client.post(
        f"/notes/{note.id}/chapters",
        data={"block_type": "paragraph", "position": "child", "ref_id": "ch"},
    )
    para = next(c for c in service.get_note(note.id).chapters if c.type == "paragraph")
    r = client.post(
        f"/notes/{note.id}/chapters/{para.id}/edit",
        data={"content_text": BAD},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_the_api_refuses_a_bad_graph_on_create_and_update(client, service):
    chapters = [
        {"id": "ch", "title": "Top", "order": 0, "type": "chapter"},
        {"id": "g", "title": "", "order": 0, "type": "graph", "parent_id": "ch", "content": BAD},
    ]
    r = client.post("/api/notes", json={"title": "Bad", "chapters": chapters})
    assert r.status_code == 400
    assert "g: line 1: the slider must go from low to high" in r.json()["detail"]
    assert all(n.title != "Bad" for n in service.list_notes())

    note = graph_note(service, GOOD)
    r = client.put(f"/api/notes/{note.id}", json={"chapters": chapters})
    assert r.status_code == 400
    assert stored(service, note.id).content == GOOD
    chapters[1]["content"] = GOOD
    assert client.put(f"/api/notes/{note.id}", json={"chapters": chapters}).status_code == 200


def test_the_edit_form_explains_the_language(client, service):
    note = graph_note(service, GOOD)
    form = client.get(f"/notes/{note.id}/chapters/g/edit").text
    assert "Graph language" in form
    assert "Write <code>2*x</code>, not <code>2x</code>." in form


def test_a_stored_definition_is_escaped_on_the_page(client, service):
    # The save refuses '<', but an import or a hand-edited file can still carry it.
    note = graph_note(service, "# " + SENTINEL)
    page = client.get(f"/notes/{note.id}").text
    assert SENTINEL not in page
    assert str(escape("# " + SENTINEL)) in page
