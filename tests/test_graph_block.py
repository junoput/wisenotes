"""The graph block, slice 1 of 20261022-064: a text definition, checked on save (20261024-003)."""

import html

from markupsafe import escape

from app.blocks import BLOCKS
from app.graph_spec import SpecError
from app.routes import pages
from app.schemas import NoteCreate

HX = {"HX-Request": "true"}
GOOD = "view 2d  x -5..5  y -3..3\na = slider(0, 5, value 1)\nf(x) = a*sin(x)\nP = (1, f(1))"
BAD = "a = slider(5, 1)\nf(x) = 2x"
CHAIN = "+".join(["1"] * 2000)  # 4 KB: under the 20k cap, and no parenthesis in sight
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
    # A comment may carry any text, '<' included, and an import or a hand-edited file
    # can carry a definition the save would refuse; the page escapes all of it.
    note = graph_note(service, "# " + SENTINEL)
    page = client.get(f"/notes/{note.id}").text
    assert SENTINEL not in page
    assert str(escape("# " + SENTINEL)) in page


def test_a_long_chain_is_refused_by_line_on_every_path_and_never_a_500(client, service):
    # 20261027-021 G1: 2000 terms raised RecursionError in the checker on save.
    note = graph_note(service, GOOD)
    typed = f"a = slider(0, {CHAIN})"
    r = client.post(
        f"/notes/{note.id}/chapters/g/edit",
        data={"title": "Wave", "content_text": typed},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "line 1: longer than" in r.text
    assert typed in r.text  # the typed text comes back, as for any refused line
    assert stored(service, note.id).content == GOOD

    chapters = [
        {"id": "ch", "title": "Top", "order": 0, "type": "chapter"},
        {"id": "g", "title": "", "order": 0, "type": "graph", "parent_id": "ch", "content": typed},
    ]
    r = client.post("/api/notes", json={"title": "Chain", "chapters": chapters})
    assert r.status_code == 400 and "g: line 1: longer than" in r.json()["detail"]
    r = client.put(f"/api/notes/{note.id}", json={"chapters": chapters})
    assert r.status_code == 400


def test_a_refusal_message_is_escaped_in_the_form(client, service, monkeypatch):
    # 20261027-021 G2: the form lists reasons with {{ err }}; a "|safe" there would pass
    # every other test, because no real message carries markup. Force one that does.
    note = graph_note(service, GOOD)
    hostile = SpecError(3, "hostile", SENTINEL)
    monkeypatch.setattr(pages.graph_spec, "validate", lambda text: [hostile])
    r = client.post(f"/notes/{note.id}/chapters/g/edit", data={"content_text": BAD})
    assert r.status_code == 400
    assert SENTINEL not in r.text
    assert str(escape(f"line 3: {SENTINEL}")) in r.text
    r = client.post(f"/notes/{note.id}/chapters/g/edit", data={"content_text": BAD}, headers=HX)
    assert SENTINEL not in r.text and str(escape(SENTINEL)) in r.text


def test_a_stored_bad_graph_can_be_sent_back_unchanged_but_not_changed_to_another(client, service):
    # 20261027-021 G3: an import stores a definition the save would refuse (it does not
    # check). PUT must not then refuse the note's own chapters sent back as they are.
    note = graph_note(service, BAD)
    chapters = [c.model_dump(mode="json") for c in service.get_note(note.id).chapters]
    r = client.put(f"/api/notes/{note.id}", json={"title": "Renamed", "chapters": chapters})
    assert r.status_code == 200, r.text
    assert service.get_note(note.id).title == "Renamed"
    # the quiet side: change that block to another bad definition and it is refused
    chapters[1]["content"] = BAD + "\nb = slider(9, 1)"
    r = client.put(f"/api/notes/{note.id}", json={"chapters": chapters})
    assert r.status_code == 400 and "g: line 1:" in r.json()["detail"]
    assert stored(service, note.id).content == BAD
    # and a new block with a bad definition is refused, though another block is unchanged
    chapters[1]["content"] = BAD
    chapters.append({**chapters[1], "id": "g2"})
    assert client.put(f"/api/notes/{note.id}", json={"chapters": chapters}).status_code == 400


def test_an_empty_math_block_has_no_caption(client, service):
    # M1: renderMath skips an empty formula, so a "Formula source" label would stay
    # over nothing, with scripts on or off.
    chapters = [
        {"id": "m", "title": "", "order": 0, "type": "math", "content": ""},
        {"id": "w", "title": "", "order": 1, "type": "math", "content": "  \n"},
        {"id": "f", "title": "", "order": 2, "type": "math", "content": "x^2"},
    ]
    note = service.create_note(NoteCreate(title="Formulas", chapters=chapters))
    html_page = client.get(f"/notes/{note.id}").text
    assert html_page.count("math-source-caption") == 1
    assert html_page.index("math-source-caption") < html_page.index("x^2")


def import_invalid_graph(service, content=BAD):
    """A definition the save would refuse, stored as an import stores it (unchecked)."""
    return graph_note(service, content)


def test_a_stored_invalid_graph_is_a_visible_error_on_the_page_without_scripts(client, service):
    # 20261027-036: the block shows why it will not draw, from the server, so it needs no script
    note = import_invalid_graph(service)
    page = client.get(f"/notes/{note.id}").text
    assert '<ul class="graph-errors" role="alert">' in page
    assert "line 1: the slider must go from low to high" in page
    assert "line 2: two values without an operator between them" in page
    good = client.get(f"/notes/{graph_note(service, GOOD).id}").text
    assert "graph-errors" not in good  # the quiet side


def test_the_error_list_escapes_what_it_shows(client, service):
    note = import_invalid_graph(service, "f(x) = <b>" + SENTINEL)
    page = client.get(f"/notes/{note.id}").text
    assert SENTINEL not in page


def test_the_block_form_checks_only_a_changed_definition_like_put(client, service):
    # 20261027-036 item 4: an imported invalid graph sent back unchanged with a new title
    # was a 400 here and a 200 on PUT.
    note = import_invalid_graph(service)
    r = client.post(
        f"/notes/{note.id}/chapters/g/edit",
        data={"title": "Renamed", "content_text": BAD},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert stored(service, note.id).title == "Renamed"
    # a plain form posts CRLF: still unchanged
    r = client.post(
        f"/notes/{note.id}/chapters/g/edit",
        data={"title": "Again", "content_text": BAD.replace("\n", "\r\n")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # the quiet side: changed to another invalid definition is refused, and nothing is written
    r = client.post(
        f"/notes/{note.id}/chapters/g/edit",
        data={"title": "Third", "content_text": BAD + "\nb = slider(9, 1)"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert stored(service, note.id).title == "Again"
    # and a valid new one is saved
    r = client.post(
        f"/notes/{note.id}/chapters/g/edit",
        data={"content_text": GOOD},
        follow_redirects=False,
    )
    assert r.status_code == 303 and stored(service, note.id).content == GOOD
