"""The picture of a graph block's default view (20261022-064, slice 5).

A browser that drew a graph sends a picture of its default view; the server stores it under a
name made of the definition's hash. Without scripts, and on paper, the block shows that
picture. Export carries it, import keeps it, and the media gallery does not list it.
"""

import io
import json
import zipfile
from datetime import datetime

import pytest
from PIL import Image

from app import graph_snapshot
from app.routes import pages
from app.schemas import NoteCreate
from app.services.bundle import export_zip
from app.services.bundle import import_bundle

SPEC = "view 2d  x -5..5  y -3..3\nf(x) = sin(x)\n"
OTHER = "view 2d  x -2..2  y -2..2\nf(x) = x\n"


def picture(color="white", size=(64, 40), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def graph_note(service, *contents, title="Graphs"):
    chapters = [{"id": "ch", "title": "Top", "order": 0, "type": "chapter"}] + [
        {"id": f"g{i}", "title": "", "order": i, "type": "graph", "parent_id": "ch", "content": c}
        for i, c in enumerate(contents)
    ]
    return service.create_note(NoteCreate(title=title, chapters=chapters))


def send(client, note, spec, data=None, chapter="g0"):
    return client.post(
        f"/notes/{note.id}/chapters/{chapter}/graph-snapshot",
        data={"spec": spec},
        files={"image": ("snapshot.png", picture() if data is None else data, "image/png")},
    )


def media(service, note):
    return service.repo.list_media(service.get_note(note.id).name)


# ---------------------------------------------------------------- the name


def test_a_definition_has_one_name_whatever_its_line_ends():
    assert graph_snapshot.spec_hash("a\r\nb") == graph_snapshot.spec_hash("a\nb")
    assert graph_snapshot.spec_hash("a\nb") != graph_snapshot.spec_hash("a\nb ")
    name = graph_snapshot.snapshot_name(SPEC)
    assert name == f"graph-{graph_snapshot.spec_hash(SPEC)}.webp" and len(name) == 6 + 16 + 5


@pytest.mark.parametrize(
    "name",
    [
        "graph-0123456789abcdef.webp",
        "graph-ffffffffffffffff.webp",
    ],
)
def test_a_snapshot_name_is_recognised(name):
    assert graph_snapshot.is_snapshot(name)


@pytest.mark.parametrize(
    "name",
    [
        "graph-0123456789abcde.webp",  # 15 hex
        "graph-0123456789abcdef0.webp",  # 17 hex
        "graph-0123456789ABCDEF.webp",  # upper case: never minted
        "graph-0123456789abcdef.png",
        "graph-0123456789abcdef.webp.exe",
        "xgraph-0123456789abcdef.webp",
        "graph-0123456789abcdef.webp\n",
        "../graph-0123456789abcdef.webp",
        "1700000000000_ab12cd34.webp",  # an uploaded image
    ],
)
def test_other_names_are_not_snapshots(name):
    assert not graph_snapshot.is_snapshot(name)


# ---------------------------------------------------------------- storing it


def test_a_picture_is_stored_under_the_name_of_the_stored_definition(client, service):
    note = graph_note(service, SPEC)
    r = send(client, note, graph_snapshot.spec_hash(SPEC))
    assert r.status_code == 204, r.text
    assert media(service, note) == [graph_snapshot.snapshot_name(SPEC)]
    path = service.repo.get_media_path(
        service.get_note(note.id).name, graph_snapshot.snapshot_name(SPEC)
    )
    with Image.open(path) as stored:  # re-encoded, not kept as sent (charter R3)
        assert stored.format == "WEBP" and stored.size == (64, 40)


def test_a_picture_of_a_definition_that_changed_is_refused_and_nothing_is_written(client, service):
    note = graph_note(service, SPEC)
    r = send(client, note, graph_snapshot.spec_hash(OTHER))
    assert r.status_code == 409
    assert media(service, note) == []


def test_the_name_comes_from_the_stored_definition_not_from_the_client(client, service):
    note = graph_note(service, SPEC)
    r = send(client, note, "../../etc/passwd")  # whatever the client calls it, it is not the hash
    assert r.status_code == 409 and media(service, note) == []


def test_there_is_no_picture_for_a_block_that_is_not_a_graph_or_not_there(client, service):
    note = graph_note(service, SPEC)
    assert send(client, note, graph_snapshot.spec_hash(""), chapter="ch").status_code == 400
    assert send(client, note, "x", chapter="nope").status_code == 404
    r = client.post(
        "/notes/nope/chapters/g0/graph-snapshot",
        data={"spec": "x"},
        files={"image": ("s.png", picture(), "image/png")},
    )
    assert r.status_code == 404
    assert media(service, note) == []


def _gif() -> bytes:
    return picture(fmt="GIF")


@pytest.mark.parametrize(
    "data",
    [
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"not an image at all",
        b"",
        _gif(),  # kept as received by the pipeline, so refused here
        picture(size=(2000, 1500)) + b"\0" * (graph_snapshot.MAX_SNAPSHOT_BYTES + 1),
    ],
    ids=["svg", "text", "empty", "gif", "oversize"],
)
def test_what_is_not_a_picture_we_store_is_refused(client, service, data):
    note = graph_note(service, SPEC)
    r = send(client, note, graph_snapshot.spec_hash(SPEC), data)
    assert r.status_code == 400, r.text
    assert media(service, note) == []


def test_a_large_picture_is_scaled_down_like_any_upload(client, service):
    note = graph_note(service, SPEC)
    assert (
        send(client, note, graph_snapshot.spec_hash(SPEC), picture(size=(3000, 1000))).status_code
        == 204
    )
    path = service.repo.get_media_path(
        service.get_note(note.id).name, graph_snapshot.snapshot_name(SPEC)
    )
    with Image.open(path) as stored:
        assert max(stored.size) == 2048


def test_two_blocks_with_one_definition_share_one_picture(client, service):
    note = graph_note(service, SPEC, SPEC)
    assert send(client, note, graph_snapshot.spec_hash(SPEC)).status_code == 204
    page = client.get(f"/notes/{note.id}").text
    assert page.count('class="graph-snapshot"') == 2
    assert len(media(service, note)) == 1


def test_an_old_picture_goes_when_a_new_one_is_stored(client, service):
    note = graph_note(service, SPEC)
    send(client, note, graph_snapshot.spec_hash(SPEC))
    old = graph_snapshot.snapshot_name(SPEC)
    assert old in media(service, note)
    client.post(f"/notes/{note.id}/chapters/g0/edit", data={"title": "", "content_text": OTHER})
    assert old in media(service, note)  # nothing has asked for a new one yet
    assert send(client, note, graph_snapshot.spec_hash(OTHER)).status_code == 204
    assert media(service, note) == [graph_snapshot.snapshot_name(OTHER)]


def test_a_picture_another_block_still_names_is_kept(client, service):
    note = graph_note(service, SPEC, OTHER)
    send(client, note, graph_snapshot.spec_hash(SPEC), chapter="g0")
    send(client, note, graph_snapshot.spec_hash(OTHER), chapter="g1")
    assert sorted(media(service, note)) == sorted(
        [graph_snapshot.snapshot_name(SPEC), graph_snapshot.snapshot_name(OTHER)]
    )


def test_a_picture_a_media_block_shows_is_kept(client, service):
    note = graph_note(service, SPEC)
    send(client, note, graph_snapshot.spec_hash(SPEC))
    old = graph_snapshot.snapshot_name(SPEC)
    # a person pointed a media block at that picture, then changed the graph
    client.post(
        f"/notes/{note.id}/chapters",
        data={"block_type": "media", "position": "child", "ref_id": "ch"},
    )
    block = next(c for c in service.get_note(note.id).chapters if c.type == "media")
    picked = client.post(
        f"/notes/{note.id}/chapters/{block.id}/media/select",
        data={"url": f"/api/notes/{note.id}/media/{old}"},
    )
    assert picked.status_code in (200, 303)
    shown = next(c for c in service.get_note(note.id).chapters if c.id == block.id)
    assert shown.content.endswith(old)  # premise: the media block shows it
    client.post(f"/notes/{note.id}/chapters/g0/edit", data={"title": "", "content_text": OTHER})
    assert send(client, note, graph_snapshot.spec_hash(OTHER)).status_code == 204
    assert sorted(media(service, note)) == sorted([old, graph_snapshot.snapshot_name(OTHER)])


# ---------------------------------------------------------------- showing it


def test_without_scripts_the_block_shows_its_picture_and_its_text(client, service):
    note = graph_note(service, SPEC, title="Waves")
    before = client.get(f"/notes/{note.id}").text
    assert 'class="graph-snapshot"' not in before and "data-has-snapshot" not in before
    assert f'data-spec-hash="{graph_snapshot.spec_hash(SPEC)}"' in before
    assert f'data-snapshot-url="/notes/{note.id}/chapters/g0/graph-snapshot"' in before
    send(client, note, graph_snapshot.spec_hash(SPEC))
    after = client.get(f"/notes/{note.id}").text
    src = f"/api/notes/{note.id}/media/{graph_snapshot.snapshot_name(SPEC)}"
    assert f'<img class="graph-snapshot" src="{src}" alt="Graph, default view">' in after
    assert "data-has-snapshot" in after
    assert '<pre class="graph-spec">' in after  # the text stays: nothing is lost
    assert client.get(src).headers["content-type"] == "image/webp"


def test_the_picture_of_another_definition_is_not_shown(client, service):
    note = graph_note(service, SPEC)
    send(client, note, graph_snapshot.spec_hash(SPEC))
    client.post(f"/notes/{note.id}/chapters/g0/edit", data={"title": "", "content_text": OTHER})
    page = client.get(f"/notes/{note.id}").text
    assert 'class="graph-snapshot"' not in page and "data-has-snapshot" not in page


def test_a_page_after_a_change_shows_the_picture_too(client, service):
    """The htmx answer (hx_refresh) draws the same figure as the full page."""
    note = graph_note(service, SPEC)
    send(client, note, graph_snapshot.spec_hash(SPEC))
    r = client.post(
        f"/notes/{note.id}/chapters/g0/edit",
        data={"title": "", "content_text": SPEC},
        headers={"HX-Request": "true"},
    )
    assert 'class="graph-snapshot"' in r.text


def test_the_title_in_the_alt_text_is_escaped(client, service):
    note = graph_note(service, SPEC)
    client.post(
        f"/notes/{note.id}/chapters/g0/edit",
        data={"title": '"><script>x</script>', "content_text": SPEC},
    )
    send(client, note, graph_snapshot.spec_hash(SPEC))
    page = client.get(f"/notes/{note.id}").text
    assert "<script>x</script>" not in page and "&lt;script&gt;x&lt;/script&gt;" in page


def test_the_gallery_does_not_list_a_graph_picture(client, service):
    note = graph_note(service, SPEC)
    send(client, note, graph_snapshot.spec_hash(SPEC))
    client.post(
        f"/notes/{note.id}/chapters",
        data={"block_type": "media", "position": "child", "ref_id": "ch"},
    )
    block = next(
        c for c in service.get_note(note.id).chapters if c.type == "media"
    )  # it has the gallery
    upload = client.post(
        f"/notes/{note.id}/media/upload",
        data={"chapter_id": block.id},
        files={"file": ("pic.png", picture("red"), "image/png")},
    )
    assert upload.status_code == 200
    names = media(service, note)
    snapshot = graph_snapshot.snapshot_name(SPEC)
    assert len(names) == 2 and snapshot in names  # premise: both files are stored
    uploaded = next(n for n in names if n != snapshot)
    # the gallery fragment the edit form includes, and the list the page builds for it
    gallery = client.get(
        f"/notes/{note.id}/chapters/{block.id}/edit", headers={"HX-Request": "true"}
    ).text
    assert f"/media/{uploaded}" in gallery  # premise: the gallery lists what a person uploaded
    assert snapshot not in gallery
    assert [f["name"] for f in pages._media_files(service, service.get_note(note.id))] == [uploaded]


# ---------------------------------------------------------------- export and import


def exported(service, *notes):
    return export_zip(service, [n.id for n in notes])


def zip_names(data: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_export_carries_the_picture(client, service):
    note = graph_note(service, SPEC)
    send(client, note, graph_snapshot.spec_hash(SPEC))
    name = service.get_note(note.id).name
    assert f"media/{name}/{graph_snapshot.snapshot_name(SPEC)}" in zip_names(
        exported(service, note)
    )


def test_import_keeps_the_picture_and_the_block_shows_it(client, service):
    note = graph_note(service, SPEC, OTHER)
    send(client, note, graph_snapshot.spec_hash(SPEC), chapter="g0")
    send(client, note, graph_snapshot.spec_hash(OTHER), chapter="g1")
    result = import_bundle(service, "export.zip", exported(service, note))
    [copy] = result.notes
    assert copy.id != note.id
    assert sorted(media(service, copy)) == sorted(
        [graph_snapshot.snapshot_name(SPEC), graph_snapshot.snapshot_name(OTHER)]
    )
    assert result.images == 0  # a picture of a graph is not one of the person's images
    assert result.skipped == [] and result.missing == []
    page = client.get(f"/notes/{copy.id}").text
    assert page.count('class="graph-snapshot"') == 2
    assert f"/api/notes/{copy.id}/media/{graph_snapshot.snapshot_name(SPEC)}" in page


def test_import_keeps_a_picture_whose_definition_was_scrubbed(service):
    """The picture is named for the definition as exported; the block is stored as scrubbed."""
    dirty = "f(x) = x\x07\n"  # the control character is removed on import
    doc = {
        "version": "1.0.0",
        "exported_at": datetime.utcnow().isoformat(),
        "notes": [
            {
                "id": "n",
                "name": "Dirty",
                "title": "Dirty",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "chapters": [
                    {"id": "g", "title": "", "order": 0, "type": "graph", "content": dirty}
                ],
            }
        ],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.json", json.dumps(doc))
        zf.writestr(f"media/Dirty/{graph_snapshot.snapshot_name(dirty)}", picture())
    [copy] = import_bundle(service, "x.zip", buf.getvalue()).notes
    clean = copy.chapters[0].content
    assert clean == "f(x) = x\n"
    assert media(service, copy) == [graph_snapshot.snapshot_name(clean)]


def _bundle_with(name_for, data, content=SPEC):
    doc = {
        "version": "1.0.0",
        "exported_at": datetime.utcnow().isoformat(),
        "notes": [
            {
                "id": "n",
                "name": "Plain",
                "title": "Plain",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "chapters": [
                    {"id": "g", "title": "", "order": 0, "type": "graph", "content": content}
                ],
            }
        ],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.json", json.dumps(doc))
        if data is not None:
            zf.writestr(f"media/Plain/{name_for}", data)
    return buf.getvalue()


def test_a_bundle_without_pictures_imports_as_before(service):
    [copy] = import_bundle(service, "x.zip", _bundle_with(None, None)).notes
    assert media(service, copy) == [] and copy.chapters[0].content == SPEC


def test_a_picture_for_another_definition_is_not_taken(service):
    wrong = graph_snapshot.snapshot_name(OTHER)
    [copy] = import_bundle(service, "x.zip", _bundle_with(wrong, picture())).notes
    assert media(service, copy) == []


@pytest.mark.parametrize(
    "data",
    [b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"junk", _gif()],
    ids=["svg", "junk", "gif"],
)
def test_a_picture_that_is_not_one_we_store_is_dropped_and_reported(service, data):
    name = graph_snapshot.snapshot_name(SPEC)
    result = import_bundle(service, "x.zip", _bundle_with(name, data))
    [copy] = result.notes
    assert media(service, copy) == []
    assert [s.split(":")[0] for s in result.skipped] == [name]
    assert copy.chapters[0].content == SPEC  # the block itself imports


def test_a_json_file_has_no_pictures_and_the_block_imports(service):
    with zipfile.ZipFile(io.BytesIO(_bundle_with(None, None))) as zf:
        raw = zf.read("notes.json")
    [copy] = import_bundle(service, "notes.json", raw).notes
    assert media(service, copy) == [] and copy.chapters[0].content == SPEC
