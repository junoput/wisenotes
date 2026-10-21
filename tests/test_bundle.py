"""Import sanitisation and export round trip, at the service level."""

import io
import json
import threading
import zipfile
from datetime import datetime

import pytest
from PIL import Image

from app.schemas import NoteCreate
from app.services import bundle
from app.services.bundle import BundleError
from app.services.bundle import export_zip
from app.services.bundle import import_bundle
from app.services.notes import NoteService


def _png(color="red", size=(4, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _doc(*notes):
    return json.dumps(
        {"version": "1.0.0", "exported_at": datetime.utcnow().isoformat(), "notes": list(notes)}
    ).encode()


def _note(**over):
    base = {
        "id": "n1",
        "name": "Old-Name",
        "title": "Hello, World!",
        "tags": ["a"],
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "chapters": [
            {
                "id": "c1",
                "title": "Chapter",
                "content": "",
                "order": 0,
                "parent_id": None,
                "type": "chapter",
            },
            {
                "id": "c2",
                "title": "",
                "content": "body\x00text\x07",
                "order": 0,
                "parent_id": "c1",
                "type": "paragraph",
            },
            {
                "id": "c3",
                "title": "pic",
                "content": "media/Old-Name/pic.png",
                "order": 1,
                "parent_id": "c1",
                "type": "media",
            },
        ],
    }
    base.update(over)
    return base


def _zip(entries: dict[str, bytes], **kw) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestJson:
    def test_ids_names_and_control_chars_are_replaced(self, service):
        r = import_bundle(service, "notes.json", _doc(_note()))
        [n] = r.notes
        assert n.id != "n1" and n.name != "Old-Name" and n.title == "Hello, World!"
        ids = {c.id for c in n.chapters}
        assert "c1" not in ids and "c2" not in ids
        para = next(c for c in n.chapters if c.type == "paragraph")
        assert para.content == "bodytext"
        assert para.parent_id == next(c for c in n.chapters if c.type == "chapter").id

    def test_import_never_merges_into_an_existing_note(self, service):
        existing = service.create_note(NoteCreate(title="Mine"))
        r = import_bundle(service, "n.json", _doc(_note(id=existing.id, title="Theirs")))
        assert r.notes[0].id != existing.id
        assert service.get_note(existing.id).title == "Mine"
        assert len(service.list_notes()) == 2

    def test_single_note_and_list_shapes(self, service):
        assert (
            len(
                import_bundle(
                    service, "a.json", json.dumps({"title": "Bare", "chapters": []}).encode()
                ).notes
            )
            == 1
        )
        assert (
            len(
                import_bundle(
                    service, "b.json", json.dumps([_note(id="x"), _note(id="y")]).encode()
                ).notes
            )
            == 2
        )

    def test_unknown_block_type_falls_back_and_media_without_bundle_is_emptied(self, service):
        n = _note(
            chapters=[
                {
                    "id": "c",
                    "title": "",
                    "content": "x",
                    "order": 0,
                    "parent_id": None,
                    "type": "chapter",
                },
                {
                    "id": "d",
                    "title": "",
                    "content": "javascript:alert(1)",
                    "order": 0,
                    "parent_id": "c",
                    "type": "media",
                },
                {
                    "id": "e",
                    "title": "",
                    "content": "https://example.org/a.png",
                    "order": 1,
                    "parent_id": "c",
                    "type": "media",
                },
                {
                    "id": "f",
                    "title": "",
                    "content": "t",
                    "order": 2,
                    "parent_id": "c",
                    "type": "exploit",
                },
            ]
        )
        r = import_bundle(service, "n.json", _doc(n))
        [imported] = r.notes
        by_order = sorted((c for c in imported.chapters if c.parent_id), key=lambda c: c.order)
        # 20261014-140, 20261021-009: an external URL is kept as it is, never fetched;
        # the page shows it as not stored (media_kind "external"), counted in missing.
        assert [c.content for c in by_order[:2]] == ["", "https://example.org/a.png"]
        assert r.missing == ["https://example.org/a.png"]
        assert "https://example.org/a.png: external image, not fetched" in r.skipped
        assert by_order[2].type == "text"

    @pytest.mark.parametrize("body", [b"", b"not json", b"[1,2]", b'{"notes": "x"}', b'{"a":1}'])
    def test_bad_json_is_a_bundle_error(self, service, body):
        with pytest.raises(BundleError):
            import_bundle(service, "n.json", body)

    def test_oversized_upload_is_refused_before_parsing(self, service, monkeypatch):
        monkeypatch.setattr(bundle, "MAX_UPLOAD_BYTES", 10)
        with pytest.raises(BundleError, match="too large"):
            import_bundle(service, "n.json", b"x" * 11)


class TestZip:
    def test_round_trip_with_image(self, service):
        z = _zip({"notes.json": _doc(_note()), "media/Old-Name/pic.png": _png()})
        r = import_bundle(service, "b.zip", z)
        [n] = r.notes
        assert r.images == 1 and r.skipped == []
        media = next(c for c in n.chapters if c.type == "media")
        [stored] = service.repo.list_media(n.name)
        assert media.content == f"/api/notes/{n.id}/media/{stored}"
        assert stored.endswith(".webp")  # re-encoded, not the archive's bytes or name
        again = export_zip(service, [n.id])
        with zipfile.ZipFile(io.BytesIO(again)) as zf:
            names = zf.namelist()
            assert "notes.json" in names and any(x.startswith(f"media/{n.name}/") for x in names)
            doc = json.loads(zf.read("notes.json"))
            assert doc["notes"][0]["chapters"][2]["content"].startswith(f"media/{n.name}/")
        r2 = import_bundle(service, "again.zip", again)
        assert r2.images == 1 and r2.notes[0].id != n.id

    def test_nested_dirs_and_zip_magic_without_extension(self, service):
        z = _zip({"export/notes.json": _doc(_note()), "export/media/Old-Name/pic.png": _png()})
        r = import_bundle(service, "whatever.bin", z)
        assert r.images == 1

    def test_note_folder_zipped_from_the_data_dir(self, service):
        # The on-disk layout: <name>/<name>.json, images in <name>/media/, blocks
        # pointing at the original note's /api/notes/<id>/media/<file>.
        n = _note(name="Trip")
        n["chapters"][2]["content"] = "/api/notes/n1/media/pic.png"
        z = _zip({"Trip/Trip.json": json.dumps(n).encode(), "Trip/media/pic.png": _png()})
        r = import_bundle(service, "Trip.zip", z)
        [note] = r.notes
        assert r.images == 1 and r.skipped == []
        media = next(c for c in note.chapters if c.type == "media")
        [stored] = service.repo.list_media(note.name)
        assert media.content == f"/api/notes/{note.id}/media/{stored}"

    @pytest.mark.parametrize(
        "bad", ["../notes.json", "/abs/notes.json", "a\\b.json", "c:/x.json", "media/../../x.png"]
    )
    def test_traversal_names_are_refused(self, service, bad):
        z = _zip({bad: _doc(_note()), "notes.json": _doc(_note())})
        with pytest.raises(BundleError, match="Unsafe path"):
            import_bundle(service, "b.zip", z)

    def test_symlink_entry_is_refused(self, service):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("notes.json", _doc(_note()))
            info = zipfile.ZipInfo("media/Old-Name/link.png")
            info.external_attr = 0o120777 << 16
            zf.writestr(info, b"/etc/passwd")
        with pytest.raises(BundleError, match="Symlink"):
            import_bundle(service, "b.zip", buf.getvalue())

    def test_non_image_and_svg_entries_are_dropped_and_reported(self, service):
        z = _zip(
            {
                "notes.json": _doc(_note()),
                "media/Old-Name/pic.png": b"<html>not an image</html>",
                "media/Old-Name/evil.svg": b"<svg onload=alert(1)/>",
                "run.sh": b"rm -rf /",
                "media/Old-Name/x.exe": b"MZ",
            }
        )
        r = import_bundle(service, "b.zip", z)
        assert r.images == 0
        # 20261019-011: not an empty block (silent loss) but a placeholder naming the file
        assert (
            next(c for c in r.notes[0].chapters if c.type == "media").content == "missing:pic.png"
        )
        assert r.missing == ["pic.png"]
        assert service.repo.list_media(r.notes[0].name) == []
        assert any("pic.png" in s for s in r.skipped) and any("evil.svg" in s for s in r.skipped)
        assert any("run.sh" in s for s in r.skipped) and any("x.exe" in s for s in r.skipped)

    def test_limits_are_enforced_from_the_directory_before_extraction(self, service, monkeypatch):
        monkeypatch.setattr(bundle, "MAX_ZIP_ENTRIES", 2)
        with pytest.raises(BundleError, match="Too many"):
            import_bundle(
                service, "b.zip", _zip({"notes.json": _doc(_note()), "a.txt": b"1", "b.txt": b"2"})
            )
        monkeypatch.setattr(bundle, "MAX_ZIP_ENTRIES", 2000)
        monkeypatch.setattr(bundle, "MAX_ENTRY_BYTES", 100)
        with pytest.raises(BundleError, match="Entry too large"):
            import_bundle(
                service,
                "b.zip",
                _zip({"notes.json": _doc(_note()), "media/Old-Name/p.png": b"\x00" * 101}),
            )
        monkeypatch.setattr(bundle, "MAX_ENTRY_BYTES", 20 * 1024 * 1024)
        monkeypatch.setattr(bundle, "MAX_TOTAL_BYTES", 150)
        with pytest.raises(BundleError, match="beyond the size limit"):
            import_bundle(
                service,
                "b.zip",
                _zip(
                    {
                        "notes.json": _doc(_note()),
                        "media/Old-Name/p.png": b"\x00" * 100,
                        "media/Old-Name/q.png": b"\x00" * 100,
                    }
                ),
            )

    def test_zip_bomb_ratio_is_refused(self, service):
        z = _zip(
            {"notes.json": _doc(_note()), "media/Old-Name/bomb.png": b"\x00" * (2 * 1024 * 1024)}
        )
        with pytest.raises(BundleError, match="compression ratio"):
            import_bundle(service, "b.zip", z)

    def test_zip_without_notes_json_or_corrupt(self, service):
        with pytest.raises(BundleError, match=r"no notes\.json"):
            import_bundle(service, "b.zip", _zip({"media/x/p.png": _png()}))
        with pytest.raises(BundleError, match="valid zip"):
            import_bundle(service, "b.zip", b"PK\x03\x04" + b"garbage")


def _three_note_zip(bad_image_in_second: bytes) -> bytes:
    notes, files = [], {}
    for i, name in enumerate(("One", "Two", "Three")):
        n = _note(id=f"n{i}", name=name, title=name)
        n["chapters"][2]["content"] = f"media/{name}/pic.jpg"
        notes.append(n)
        files[f"media/{name}/pic.jpg"] = bad_image_in_second if i == 1 else _png()
    files["notes.json"] = _doc(*notes)
    return _zip(files)


def _jpeg_truncated_in_scan_data() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(buf, format="JPEG")
    return buf.getvalue()[:-10]  # passes verify(), fails at decode


class TestAllOrNothing:
    def test_a_bad_image_mid_import_is_skipped_not_a_half_import(self, service):
        # The reviewer's reproduction: 3 notes, a truncated JPEG in note 2. Was a
        # 500 with 2 notes left behind; now all 3 notes, the image reported.
        r = import_bundle(service, "x.zip", _three_note_zip(_jpeg_truncated_in_scan_data()))
        assert [n.title for n in r.notes] == ["One", "Two", "Three"]
        assert r.images == 2 and len(r.skipped) == 1 and "pic.jpg" in r.skipped[0]
        assert len(service.list_notes()) == 3

    def test_an_unexpected_failure_rolls_back_every_note_created(
        self, service, data_dir, monkeypatch
    ):
        service.create_note(NoteCreate(title="Already here"))
        real_save = service.save_media_file
        calls = []

        def save_then_fail(note_id, name, data):
            calls.append(note_id)
            if len(calls) == 2:
                raise RuntimeError("disk full")
            real_save(note_id, name, data)

        monkeypatch.setattr(service, "save_media_file", save_then_fail)
        with pytest.raises(RuntimeError, match="disk full"):
            import_bundle(service, "x.zip", _three_note_zip(_png()))
        assert len(calls) == 2  # precondition: the failure came after a note was created
        assert [n.title for n in service.list_notes()] == ["Already here"]
        # and no folder left on disk either (media included)
        assert [p.name for p in data_dir.iterdir() if p.is_dir()] == [service.list_notes()[0].name]


APPLEDOUBLE = b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        \x00\x02"  # what ._<file> holds


def _finder_zip(note: dict, images: dict[str, bytes]) -> bytes:
    """A note folder zipped in macOS Finder, junk FIRST so it cannot win by order."""
    entries = {
        "__MACOSX/._Trip": APPLEDOUBLE,
        "__MACOSX/Trip/._Trip.json": APPLEDOUBLE,  # ends in .json: must not be read as the note
        "Trip/.DS_Store": b"\x00\x00\x00\x01Bud1",
        "__MACOSX/Trip/._.DS_Store": APPLEDOUBLE,
    }
    for name in images:
        entries[f"__MACOSX/Trip/media/._{name}"] = APPLEDOUBLE  # ends in .png: must not be an image
    entries["Trip/Trip.json"] = json.dumps(note).encode()
    entries.update({f"Trip/media/{name}": data for name, data in images.items()})
    return _zip(entries)


class TestFinderZip:
    """20261019-011: the operator's SWEN1.zip, a note folder zipped in Finder."""

    def test_finder_metadata_is_ignored_and_never_stored(self, service):
        n = _note(name="Trip")
        n["chapters"][2]["content"] = "/api/notes/n1/media/pic.png"
        r = import_bundle(service, "Trip.zip", _finder_zip(n, {"pic.png": _png()}))
        [note] = r.notes
        assert r.images == 1 and r.missing == [] and r.ignored == 5
        assert not [s for s in r.skipped if "__MACOSX" in s or ".DS_Store" in s], r.skipped
        [stored] = service.repo.list_media(note.name)
        assert next(c for c in note.chapters if c.type == "media").content.endswith(stored)

    def test_a_referenced_image_absent_from_the_zip_stays_visible(self, service):
        n = _note(name="Trip")
        media = n["chapters"][2]
        n["chapters"].append(
            {**media, "id": "c9", "order": 9, "content": "/api/notes/n1/media/gone.png"}
        )
        media["content"] = "/api/notes/n1/media/pic.png"
        r = import_bundle(service, "Trip.zip", _finder_zip(n, {"pic.png": _png()}))
        [note] = r.notes
        assert r.images == 1 and r.missing == ["gone.png"]
        contents = sorted(c.content for c in note.chapters if c.type == "media")
        assert contents[0].startswith("/api/notes/") and contents[1] == "missing:gone.png"

    def test_a_placeholder_survives_export_and_reimport(self, service):
        n = _note(name="Trip")
        n["chapters"][2]["content"] = "/api/notes/n1/media/gone.png"
        [first] = import_bundle(service, "Trip.zip", _finder_zip(n, {})).notes
        again = import_bundle(service, "x.zip", export_zip(service, [first.id]))
        [note] = again.notes
        assert next(c for c in note.chapters if c.type == "media").content == "missing:gone.png"


def _folder_note(name: str, image: str) -> dict:
    n = _note(id=f"id-{name}", name=name, title=name)
    n["chapters"][2]["content"] = f"/api/notes/id-{name}/media/{image}"
    return n


class TestSeveralNoteFolders:
    """20261019-069: two note folders in one zip imported only the first, silently."""

    COLORS = ("red", "blue", "green")

    def _zip_of_folders(self, *paths: str, extra: dict[str, bytes] | None = None) -> bytes:
        """One folder per path, every image named pic.png (20261020-045: a keying by
        file name alone must not pass), each folder a different colour."""
        entries: dict[str, bytes] = {}
        for i, path in enumerate(paths):
            name = path.rsplit("/", 1)[-1]
            entries[f"{path}/{name}.json"] = json.dumps(_folder_note(name, "pic.png")).encode()
            entries[f"{path}/media/pic.png"] = _png(self.COLORS[i % 3])
        entries.update(extra or {})
        return _zip(entries)

    @staticmethod
    def _color_of(service, note) -> tuple[int, int, int]:
        [stored] = service.repo.list_media(note.name)
        with Image.open(service.repo.get_media_path(note.name, stored)) as im:
            return im.convert("RGB").getpixel((1, 1))

    def test_every_note_folder_is_imported_with_its_own_images(self, service):
        r = import_bundle(service, "two.zip", self._zip_of_folders("Bravo", "Alpha"))
        assert [n.title for n in r.notes] == ["Alpha", "Bravo"]  # sorted, so stable
        assert r.images == 2 and r.missing == [] and r.skipped == []
        for note in r.notes:
            [stored] = service.repo.list_media(note.name)
            media = next(c for c in note.chapters if c.type == "media")
            assert media.content == f"/api/notes/{note.id}/media/{stored}"
        alpha, bravo = r.notes
        assert self._color_of(service, alpha)[2] > 200  # Alpha was zipped blue
        assert self._color_of(service, bravo)[0] > 200  # Bravo red

    def test_two_folders_with_the_same_name_keep_their_own_images(self, service):
        # 20261020-045 3a: keyed by the folder directly above media/, both got y's image.
        r = import_bundle(service, "same.zip", self._zip_of_folders("x/Alpha", "y/Alpha"))
        assert len(r.notes) == 2 and r.images == 2 and r.missing == []
        x_note, y_note = r.notes  # path order: x/ before y/
        assert self._color_of(service, x_note)[0] > 200  # x zipped red
        assert self._color_of(service, y_note)[2] > 200  # y zipped blue

    def test_a_note_cannot_take_another_folders_images_by_naming_it(self, service):
        n = _folder_note("Bravo", "pic.png")  # its JSON names Bravo, but it lives in x/
        z = _zip({"x/x.json": json.dumps(n).encode(), "Bravo/media/pic.png": _png()})
        r = import_bundle(service, "named.zip", z)
        assert r.images == 0 and r.missing == ["pic.png"]

    def test_a_folder_whose_name_ends_in_media_is_a_note_folder(self, service):
        # 20261020-086: '"media/" not in name' was a substring test; socialmedia/ was dropped.
        r = import_bundle(service, "social.zip", self._zip_of_folders("Alpha", "socialmedia"))
        assert [n.title for n in r.notes] == ["Alpha", "socialmedia"]
        assert r.images == 2 and r.missing == [] and r.skipped == []
        assert self._color_of(service, r.notes[1])[2] > 200  # socialmedia zipped blue

    def test_a_json_inside_a_media_folder_is_still_not_a_note(self, service):
        # the quiet side of the fix above: a media/ path component still excludes it
        z = self._zip_of_folders("Alpha", extra={"Alpha/media/meta.json": b"{}"})
        r = import_bundle(service, "meta.zip", z)
        assert [n.title for n in r.notes] == ["Alpha"]
        assert r.skipped == ["Alpha/media/meta.json: not notes.json or an image under media/"]

    def test_a_root_level_note_cannot_take_a_folders_images_by_naming_it(self, service):
        # 20261020-086: x.json at the root fell back to its name, Bravo, and so
        # reached Bravo/media/pic.png.
        n = _folder_note("Bravo", "pic.png")
        z = _zip({"x.json": json.dumps(n).encode(), "Bravo/media/pic.png": _png()})
        r = import_bundle(service, "root.zip", z)
        assert r.images == 0 and r.missing == ["pic.png"]

    def test_with_the_folder_note_present_only_it_gets_its_images(self, service):
        # ...and with Bravo/Bravo.json beside it, both notes got the image.
        n = _folder_note("Bravo", "pic.png")
        z = self._zip_of_folders("Bravo", extra={"x.json": json.dumps(n).encode()})
        r = import_bundle(service, "both.zip", z)
        assert len(r.notes) == 2 and r.images == 1 and r.missing == ["pic.png"]
        [owner] = [n for n in r.notes if service.repo.list_media(n.name)]
        media = next(c for c in owner.chapters if c.type == "media")
        assert media.content.startswith(f"/api/notes/{owner.id}/media/")
        assert service.repo.get_note(owner.id).name == "Bravo"

    def test_harness_control_a_root_level_note_keeps_its_export_style_images(self, service):
        # The fallback that stays: a root-level note's media/<name>/<file> references.
        z = _zip({"x.json": json.dumps(_note()).encode(), "media/Old-Name/pic.png": _png()})
        r = import_bundle(service, "export-style.zip", z)
        assert r.images == 1 and r.missing == []

    def test_a_doubled_slash_in_the_folder_path_still_finds_its_images(self, service):
        # 20261020-086: the scope was normalised (x/Alpha) but the media key was not (x//Alpha).
        n = _folder_note("Alpha", "pic.png")
        z = _zip({"x//Alpha/Alpha.json": json.dumps(n).encode(), "x//Alpha/media/pic.png": _png()})
        r = import_bundle(service, "slashes.zip", z)
        assert r.images == 1 and r.missing == []

    def test_a_note_titled_notes_is_a_note_not_an_export(self, service):
        # 3b: stored as notes/notes.json, it was classified as an export by its file name.
        z = self._zip_of_folders("notes", "Alpha")
        r = import_bundle(service, "with-notes.zip", z)
        assert sorted(n.title for n in r.notes) == ["Alpha", "notes"] and r.images == 2

    def test_a_data_dir_with_an_old_export_beside_its_folders_is_refused_by_name(self, service):
        z = self._zip_of_folders("data/Alpha", extra={"data/notes.json": _doc(_note())})
        with pytest.raises(BundleError, match=r"the export data/notes\.json and also data/Alpha"):
            import_bundle(service, "datadir.zip", z)
        assert service.list_notes() == []

    def test_harness_control_one_folder_still_imports_one_note(self, service):
        r = import_bundle(service, "one.zip", self._zip_of_folders("Alpha"))
        assert [n.title for n in r.notes] == ["Alpha"] and r.images == 1

    def test_an_export_mixed_with_a_note_folder_is_refused_whole(self, service):
        z = self._zip_of_folders("Alpha", extra={"notes.json": _doc(_note())})
        with pytest.raises(BundleError, match=r"notes\.json and also Alpha/Alpha\.json"):
            import_bundle(service, "mixed.zip", z)
        assert service.list_notes() == []

    def test_two_exports_in_one_zip_are_refused(self, service):
        z = _zip({"a/notes.json": _doc(_note()), "b/notes.json": _doc(_note())})
        with pytest.raises(
            BundleError, match=r"more than one export: a/notes\.json, b/notes\.json"
        ):
            import_bundle(service, "two-exports.zip", z)
        assert service.list_notes() == []

    def test_the_json_size_cap_counts_every_note_file(self, service, monkeypatch):
        z = self._zip_of_folders("Alpha", "Bravo")
        one = len(json.dumps(_folder_note("Alpha", "Alpha.png")))
        monkeypatch.setattr(bundle, "MAX_JSON_BYTES", one + 10)  # each fits, both do not
        with pytest.raises(BundleError, match="too large together"):
            import_bundle(service, "big.zip", z)


class TestImportRacesAMediaDelete:
    """20261021-027: import stored a note's images, then wrote the links in a
    separate call; a media delete between the two found the file unused."""

    def test_a_delete_during_the_import_of_a_note_cannot_remove_its_image(
        self, service, monkeypatch
    ):
        z = _zip({"notes.json": _doc(_note()), "media/Old-Name/pic.png": _png()})
        paused, release = threading.Event(), threading.Event()
        real = NoteService.update_note
        seen = {}

        def slow_update(self, note_id, payload):
            if payload.chapters and not paused.is_set():
                seen["id"] = note_id
                seen["files"] = list(self.repo.list_media(self.repo.get_note(note_id).name))
                paused.set()  # images stored, links not yet written
                release.wait(5)
            return real(self, note_id, payload)

        monkeypatch.setattr(NoteService, "update_note", slow_update)
        out = {}
        importer = threading.Thread(
            target=lambda: out.update(r=import_bundle(service, "raced.zip", z))
        )
        importer.start()
        assert paused.wait(5)
        [stored] = seen["files"]
        deleter = threading.Thread(
            target=lambda: out.update(d=service.delete_media_unless_used(seen["id"], stored))
        )
        deleter.start()
        deleter.join(0.3)
        assert deleter.is_alive()  # waits for the import's lock hold
        release.set()
        importer.join(5)
        deleter.join(5)
        assert out["d"][1] and out["d"][2] is False  # refused: the block shows it now
        assert service.repo.list_media(service.get_note(seen["id"]).name) == [stored]

    def test_a_note_deleted_while_its_images_are_decoded_fails_the_import_whole(
        self, service, monkeypatch
    ):
        # The other window: the note was created, its images are being decoded (no
        # lock), and someone deletes it. The import refuses instead of writing
        # images for a note that is gone, and rolls back.
        z = _zip({"notes.json": _doc(_note()), "media/Old-Name/pic.png": _png()})
        decoding, release = threading.Event(), threading.Event()
        real = bundle.process_uploaded_image

        def slow_process(*a):
            decoding.set()
            release.wait(5)
            return real(*a)

        monkeypatch.setattr(bundle, "process_uploaded_image", slow_process)
        out = {}

        def run():
            try:
                import_bundle(service, "deleted.zip", z)
            except BundleError as e:
                out["error"] = str(e)

        importer = threading.Thread(target=run)
        importer.start()
        assert decoding.wait(5)
        [created] = service.list_notes()
        assert service.delete_note_unless_shown(created.id)[1] == []
        release.set()
        importer.join(5)
        assert out["error"].startswith("A note was deleted while it was being imported")
        assert service.list_notes() == []
