"""Import sanitisation and export round trip, at the service level."""

import io
import json
import zipfile
from datetime import datetime

import pytest
from PIL import Image

from app.schemas import NoteCreate
from app.services import bundle
from app.services.bundle import BundleError
from app.services.bundle import export_zip
from app.services.bundle import import_bundle


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
        [imported] = import_bundle(service, "n.json", _doc(n)).notes
        by_order = sorted((c for c in imported.chapters if c.parent_id), key=lambda c: c.order)
        assert [c.content for c in by_order[:2]] == ["", "https://example.org/a.png"]
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
        assert next(c for c in r.notes[0].chapters if c.type == "media").content == ""
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
