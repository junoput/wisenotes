"""The write fence: only the container named in <data>/.writer may write (20261022-035)."""

import json
import subprocess
import threading
from pathlib import Path

import pytest

from app import write_fence
from app.config import get_settings
from app.services.storage import JsonNoteRepository


@pytest.fixture()
def fenced(data_dir: Path, monkeypatch):
    """The app's data dir is data_dir, the lock file exists, and this container is "me"."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / write_fence.LOCK_FILE).touch()
    monkeypatch.setenv("WISENOTES_DATA_DIR", str(data_dir))
    monkeypatch.setenv("WISENOTES_WRITER_ID", "me")
    get_settings.cache_clear()
    yield data_dir
    get_settings.cache_clear()


def name_writer(data_dir: Path, who: str) -> None:
    (data_dir / write_fence.WRITER_FILE).write_text(who + "\n")


def snapshot(data_dir: Path) -> dict[str, bytes]:
    return {str(p.relative_to(data_dir)): p.read_bytes() for p in data_dir.rglob("*") if p.is_file()}


def test_the_named_writer_writes(client, fenced):
    name_writer(fenced, "me")
    r = client.post("/notes", data={"title": "Kept"}, follow_redirects=False)
    assert r.status_code in (200, 303), r.text
    assert any(p.name == "Kept" for p in fenced.iterdir())


def test_a_container_not_named_refuses_writes_and_changes_nothing(client, fenced):
    name_writer(fenced, "the-other-container")
    before = snapshot(fenced)
    r = client.post("/notes", data={"title": "Lost"}, follow_redirects=False)
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "2"
    assert "switching to a new version" in r.text
    assert r.headers["X-Frame-Options"] == "DENY"  # the headers middleware still wraps it
    for method, path in (("PUT", "/api/notes/x"), ("DELETE", "/api/notes/x")):
        assert client.request(method, path).status_code == 503
    assert snapshot(fenced) == before


def test_a_container_not_named_still_serves_reads(client, fenced):
    name_writer(fenced, "the-other-container")
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("missing", [write_fence.WRITER_FILE, write_fence.LOCK_FILE])
def test_a_missing_fence_file_refuses_writes(client, fenced, missing):
    name_writer(fenced, "me")
    (fenced / missing).unlink()
    assert client.post("/notes", data={"title": "Lost"}, follow_redirects=False).status_code == 503


def test_without_a_writer_id_there_is_no_fence(client, fenced, monkeypatch):
    monkeypatch.delenv("WISENOTES_WRITER_ID")
    name_writer(fenced, "the-other-container")
    r = client.post("/notes", data={"title": "Kept"}, follow_redirects=False)
    assert r.status_code in (200, 303), r.text


def test_a_change_of_writer_waits_for_a_write_in_flight(fenced):
    # deploy.sh changes the writer under `flock -x`; it must wait while a write holds the lock.
    name_writer(fenced, "me")
    fd, allowed = write_fence.acquire(fenced)
    assert allowed and fd is not None
    deploy = subprocess.Popen(
        ["flock", "-x", "-w", "5", str(fenced / write_fence.LOCK_FILE), "sh", "-c", f"echo other > {fenced / '.writer'}"]
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            deploy.wait(timeout=0.5)
        assert (fenced / ".writer").read_text().strip() == "me"
    finally:
        write_fence.release(fd)
    assert deploy.wait(timeout=5) == 0
    assert write_fence.acquire(fenced) == (None, False)


def test_a_write_waits_while_the_writer_is_being_changed(fenced):
    name_writer(fenced, "me")
    deploy = subprocess.Popen(["flock", "-x", str(fenced / write_fence.LOCK_FILE), "sleep", "0.5"])
    result = {}
    try:
        # let the deploy take the lock first
        for _ in range(100):
            probe = subprocess.run(["flock", "-n", "-s", str(fenced / write_fence.LOCK_FILE), "true"])
            if probe.returncode != 0:
                break
            threading.Event().wait(0.01)
        else:
            pytest.fail("the deploy never took the lock")
        t = threading.Thread(target=lambda: result.update(got=write_fence.acquire(fenced)))
        t.start()
        t.join(timeout=0.2)
        assert t.is_alive(), "acquire returned while the exclusive lock was held"
        t.join(timeout=5)
    finally:
        deploy.wait()
    fd, allowed = result["got"]
    assert allowed
    write_fence.release(fd)


def test_the_legacy_migration_runs_only_in_the_writer(fenced):
    legacy = fenced / "notes.json"
    t = "2026-10-01T00:00:00Z"
    note = {"id": "n1", "name": "Old-note", "title": "Old note", "created_at": t, "updated_at": t}
    legacy.write_text(json.dumps({"exported_at": t, "notes": [note]}))
    name_writer(fenced, "the-other-container")
    before = snapshot(fenced)
    JsonNoteRepository(legacy)
    assert snapshot(fenced) == before
    name_writer(fenced, "me")
    JsonNoteRepository(legacy)
    assert (fenced / "Old-note" / "Old-note.json").exists()


def test_a_write_holds_the_lock_until_its_handler_has_finished(client, fenced, service, monkeypatch):
    # If the lock were dropped before the handler ran, a change of writer could
    # land in the middle of this write.
    name_writer(fenced, "me")
    seen = {}
    create = service.create_note

    def probing_create(payload):
        probe = subprocess.run(["flock", "-n", "-x", str(fenced / write_fence.LOCK_FILE), "true"])
        seen["exclusive_refused"] = probe.returncode != 0
        return create(payload)

    monkeypatch.setattr(service, "create_note", probing_create)
    r = client.post("/notes", data={"title": "Held"}, follow_redirects=False)
    assert r.status_code in (200, 303), r.text
    assert seen == {"exclusive_refused": True}
    # and released afterwards
    assert subprocess.run(["flock", "-n", "-x", str(fenced / write_fence.LOCK_FILE), "true"]).returncode == 0
