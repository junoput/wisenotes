"""Saving a graph block's default view (20261022-064, slice 3).

The browser sends the board's box and the sliders' values; the server writes them into
the stored definition: the view line and each slider's `value`, nothing else.
"""

import math

import pytest

from app import graph_spec
from app.schemas import NoteCreate

TEXT = (
    "# demo\n"
    "view 2d  x -5..5  y -3..3  # the default\n"
    "a = slider(0, 5, step 0.1, value 1, play) # speed\n"
    "b = slider(0, 1)\n"
    "f(x) = a*sin(x)\n"
    "c(t) = (b*t, t), t in 0..2*pi\n"
    "P = (1, 2)\n"
)


def test_the_view_line_and_the_slider_values_are_replaced_and_nothing_else():
    got = graph_spec.with_view(TEXT, (-1.5, 8), (0, 3.25), {"a": 2.5, "b": 0.5})
    assert got.split("\n") == [
        "# demo",
        "view 2d  x -1.5..8  y 0..3.25  # the default",
        "a = slider(0, 5, step 0.1, value 2.5, play) # speed",
        "b = slider(0, 1, value 0.5)",
        "f(x) = a*sin(x)",
        "c(t) = (b*t, t), t in 0..2*pi",
        "P = (1, 2)",
        "",
    ]


def test_a_definition_without_a_view_gets_one_first():
    got = graph_spec.with_view("f(x) = x\n", (0, 1), (0, 1))
    assert got == "view 2d  x 0..1  y 0..1\nf(x) = x\n"


def test_a_slider_that_is_not_named_keeps_its_line():
    got = graph_spec.with_view(TEXT, (-5, 5), (-3, 3), {"a": 2})
    assert "b = slider(0, 1)" in got and "value 2," in got


def test_crlf_line_ends_are_kept():
    got = graph_spec.with_view(
        "view 2d\r\na = slider(0, 1)\r\nf(x) = a\r\n", (0, 1), (0, 1), {"a": 1}
    )
    assert got == "view 2d  x 0..1  y 0..1\r\na = slider(0, 1, value 1)\r\nf(x) = a\r\n"


@pytest.mark.parametrize(
    ("x", "y"),
    [
        ((0.000000123456789, 0.000000223456789), (-1, 1)),  # a zoom with no exponent in the text
        ((1000000, 1000000.5), (-1, 1)),
        ((-1e12, 1e12), (-3e11, 3e11)),
        ((100000, 100000.001), (-0.0000001, 0.0000001)),
    ],
)
def test_a_saved_view_reads_back_as_the_box_that_was_saved(x, y):
    spec = graph_spec.parse(graph_spec.with_view("f(x) = x", x, y))
    assert spec.errors == []
    for got, want in ((spec.view.x, x), (spec.view.y, y)):
        assert all(
            math.isclose(g, w, rel_tol=1e-4, abs_tol=0) for g, w in zip(got, want, strict=True)
        )


@pytest.mark.parametrize(
    ("x", "y", "values", "why"),
    [
        ((1, 1), (0, 1), {}, "x range"),
        ((0, 1), (2, 1), {}, "y range"),
        ((0, math.inf), (0, 1), {}, "x range"),
        ((0, 1), (math.nan, 1), {}, "y range"),
        ((0, 1), (0, 1), {"nope": 1}, "not a slider"),
        ((0, 1), (0, 1), {"a": 9}, "within its range"),
        ((0, 1), (0, 1), {"a": math.nan}, "within its range"),
    ],
)
def test_numbers_that_cannot_be_saved_are_refused(x, y, values, why):
    with pytest.raises(ValueError, match=why):
        graph_spec.with_view(TEXT, x, y, values)


def test_a_definition_with_errors_is_not_rewritten():
    with pytest.raises(ValueError, match="has errors"):
        graph_spec.with_view("f(x) = 2x", (0, 1), (0, 1))


# ---- the route


def graph_note(service, content=TEXT, title="keep me", source="a; b"):
    chapters = [
        {"id": "ch", "title": "Top", "order": 0, "type": "chapter"},
        {
            "id": "g",
            "title": title,
            "order": 0,
            "type": "graph",
            "parent_id": "ch",
            "content": content,
            "source": source,
        },
        {"id": "t", "title": "", "order": 1, "type": "text", "parent_id": "ch", "content": "hi"},
    ]
    return service.create_note(NoteCreate(title="Graphs", chapters=chapters))


def block(service, note, chapter_id="g"):
    return next(c for c in service.get_note(note.id).chapters if c.id == chapter_id)


FORM = {"x0": "-1.5", "x1": "8", "y0": "0", "y1": "3.25", "slider": ["a=2.5", "b=0.5"]}


def test_the_page_names_where_a_view_is_saved(client, service):
    note = graph_note(service)
    page = client.get(f"/notes/{note.id}").text
    assert f'data-view-url="/notes/{note.id}/chapters/g/graph-view"' in page


def test_saving_a_view_rewrites_only_the_definition(client, service):
    note = graph_note(service)
    r = client.post(
        f"/notes/{note.id}/chapters/g/graph-view",
        data=FORM,
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200 and 'id="editor"' in r.text  # the refreshed page, for htmx
    saved = block(service, note)
    assert saved.content == graph_spec.with_view(TEXT, (-1.5, 8), (0, 3.25), {"a": 2.5, "b": 0.5})
    assert (saved.title, saved.source, saved.type) == ("keep me", "a; b", "graph")
    assert block(service, note, "t").content == "hi"


def test_without_scripts_a_saved_view_goes_back_to_the_page(client, service):
    note = graph_note(service)
    r = client.post(f"/notes/{note.id}/chapters/g/graph-view", data=FORM, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/notes/{note.id}"


@pytest.mark.parametrize(
    "form",
    [
        {**FORM, "x1": "-1.5"},
        {**FORM, "x0": "nan"},
        {**FORM, "slider": ["a=99"]},
        {**FORM, "slider": ["zzz=1"]},
        {**FORM, "slider": ["a"]},
        {**FORM, "slider": ["a=lots"]},
    ],
)
def test_a_view_that_cannot_be_saved_is_a_400_and_changes_nothing(client, service, form):
    note = graph_note(service)
    r = client.post(f"/notes/{note.id}/chapters/g/graph-view", data=form)
    assert r.status_code == 400 and r.text
    assert block(service, note).content == TEXT


def test_a_view_is_saved_into_what_is_stored_now(client, service):
    # a page that was drawn from an older definition cannot put that definition back
    note = graph_note(service)
    service.update_chapter(note.id, "g", "keep me", TEXT + "Q = (3, 3)\n")
    client.post(f"/notes/{note.id}/chapters/g/graph-view", data=FORM)
    assert "Q = (3, 3)" in block(service, note).content


def test_only_a_graph_block_has_a_view(client, service):
    note = graph_note(service)
    r = client.post(f"/notes/{note.id}/chapters/t/graph-view", data=FORM)
    assert r.status_code == 400 and block(service, note, "t").content == "hi"


def test_a_missing_block_or_note_is_a_404(client, service):
    note = graph_note(service)
    assert client.post(f"/notes/{note.id}/chapters/nope/graph-view", data=FORM).status_code == 404
    assert client.post("/notes/nope/chapters/g/graph-view", data=FORM).status_code == 404
