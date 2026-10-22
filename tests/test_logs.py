"""Log records in the conventions v6 vocabulary (docs/OBSERVABILITY.md, 20261020-042)."""

import io
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

from app import logs
from app.schemas import NoteCreate

SENTINEL = "Zq7SentinelTitle"
REQUIRED = (
    "timestamp",
    "severity_text",
    "severity_number",
    "service.name",
    "service.version",
    "deployment.environment",
    "body",
)
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def records():
    """Every record the app logs from here on, formatted by the app's own formatter."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logs.JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)

    def read() -> list[dict]:
        lines = stream.getvalue().splitlines()
        return [json.loads(line) for line in lines]

    yield read
    root.removeHandler(handler)


def requests_of(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["logger"] == "wisenotes.request"]


def test_every_record_carries_the_required_fields(records):
    logging.getLogger("wisenotes.test").info("hello %s", "there")
    (row,) = records()
    for field in REQUIRED:
        assert field in row, field
    assert TIMESTAMP.match(row["timestamp"]), row["timestamp"]
    assert (row["severity_text"], row["severity_number"]) == ("INFO", 9)
    assert row["service.name"] == "wisenotes"
    assert row["body"] == "hello there"


@pytest.mark.parametrize(
    ("level", "text", "number"),
    [
        (logging.DEBUG, "DEBUG", 5),
        (logging.INFO, "INFO", 9),
        (logging.WARNING, "WARN", 13),
        (logging.ERROR, "ERROR", 17),
        (logging.CRITICAL, "FATAL", 21),
        (logging.DEBUG - 5, "TRACE", 1),
    ],
)
def test_the_severity_scale_is_the_conventions_scale(level, text, number):
    assert logs.severity(level) == (text, number)


def test_service_identity_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "notes-override")
    monkeypatch.setenv("WISENOTES_VERSION", "abc1234")
    monkeypatch.setenv("WISENOTES_ENVIRONMENT", "prod")
    assert logs.service_identity() == {
        "service.name": "notes-override",
        "service.version": "abc1234",
        "deployment.environment": "prod",
    }


def test_an_unknown_build_or_environment_is_not_spelled_as_a_value(monkeypatch):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("WISENOTES_VERSION", raising=False)
    monkeypatch.setenv("WISENOTES_ENVIRONMENT", "production")  # not on the scale
    assert logs.service_identity() == {
        "service.name": "wisenotes",
        "service.version": "unknown",
        "deployment.environment": "dev",
    }


@pytest.mark.parametrize(
    ("path", "status", "severity"),
    [("/", 200, "INFO"), ("/notes/no-such-note", 404, "WARN")],
)
def test_one_record_per_request_with_severity_by_outcome(client, records, path, status, severity):
    assert client.get(path).status_code == status
    (row,) = requests_of(records())
    assert row["severity_text"] == severity
    assert row["http.response.status_code"] == status
    assert row["http.request.method"] == "GET"
    assert row["url.path"] == path
    assert row["body"] == f"GET {path} {status}"
    assert re.fullmatch(r"[0-9a-f]{32}", row["correlation_id"])


def test_a_failure_of_ours_is_an_error_with_its_exception(client, service, records, monkeypatch):
    def broken():
        raise OSError(13, "Permission denied", f"/app/data/{SENTINEL}")

    monkeypatch.setattr(service, "list_notes", broken)
    assert client.get("/").status_code == 500
    rows = records()
    (request,) = requests_of(rows)
    assert request["severity_text"] == "ERROR"
    (error,) = [r for r in rows if "exception.type" in r]
    assert error["severity_text"] == "ERROR"
    assert error["exception.type"] == "builtins.PermissionError"
    assert error["exception.message"] == "Permission denied"
    assert "broken" in error["exception.stacktrace"]
    assert re.fullmatch(r"[0-9a-f]{16}", error["error.fingerprint"])
    # one request, one correlation id across its records
    assert error["correlation_id"] == request["correlation_id"]
    assert SENTINEL not in json.dumps(rows)


def test_the_fingerprint_is_the_shape_not_the_data():
    def fail(where: str):
        raise OSError(2, "No such file or directory", where)

    def fingerprint(where: str) -> str:
        try:
            fail(where)
        except OSError as e:
            return logs._exception_fields(e, e.__traceback__)["error.fingerprint"]
        raise AssertionError("fail() returned")

    def other_site() -> str:
        try:
            raise OSError(2, "No such file or directory", "x")
        except OSError as e:
            return logs._exception_fields(e, e.__traceback__)["error.fingerprint"]

    assert fingerprint("/a/one") == fingerprint("/b/two")
    assert fingerprint("/a/one") != other_site()


def test_the_route_is_logged_and_the_query_and_host_are_not(client, service, records):
    note = service.create_note(NoteCreate(title="x"))
    r = client.get(f"/notes/{note.id}?q={SENTINEL}", headers={"Host": f"{SENTINEL}.example"})
    assert r.status_code == 200
    (row,) = requests_of(records())
    assert row["url.path"] == f"/notes/{note.id}"
    assert row["http.route"] == "/notes/{note_id}"
    assert SENTINEL not in json.dumps(row)


def test_health_probes_are_not_logged(client, records):
    assert client.get("/health").status_code == 200
    assert requests_of(records()) == []
    # control: the same client's next request is
    client.get("/")
    assert len(requests_of(records())) == 1


def test_each_request_has_its_own_correlation_id(client, records):
    client.get("/")
    client.get("/")
    ids = {r["correlation_id"] for r in requests_of(records())}
    assert len(ids) == 2
    logging.getLogger("wisenotes.test").info("outside any request")
    assert "correlation_id" not in records()[-1]


def test_a_skipped_import_entry_is_logged_without_its_title(client, service, records):
    note = service.create_note(NoteCreate(title="kept"))
    bundle = io.BytesIO(client.get(f"/notes/{note.id}/export.zip").content)
    with zipfile.ZipFile(bundle, "a") as zf:
        zf.writestr(f"{SENTINEL}.txt", "not an image")
    r = client.post(
        "/notes/import",
        files={"file": ("b.zip", bundle.getvalue(), "application/zip")},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303), r.text
    rows = records()
    skipped = [r for r in rows if r["body"].startswith("import skipped")]
    assert skipped, "the import skipped nothing, so this test proves nothing"
    assert skipped[0]["body"] == "import skipped an entry: not notes.json or an image under media/"
    assert SENTINEL not in json.dumps(rows)


def test_an_unreadable_note_folder_is_logged_without_its_name(repo, records):
    folder = repo._root_dir / SENTINEL
    folder.mkdir(parents=True)
    (folder / f"{SENTINEL}.json").write_text("{not json")
    repo.list_notes()
    rows = records()
    assert [r["body"] for r in rows] == ["Failed to read a note folder"]
    assert SENTINEL not in json.dumps(rows)


def test_under_uvicorn_every_line_is_json_and_its_access_log_is_off(tmp_path):
    """The real server: uvicorn applies its own logging config before it imports
    the app, so this is where a plain-text line or a query string would appear."""
    env = {
        **os.environ,
        "WISENOTES_DATA_DIR": str(tmp_path / "data"),
        "WISENOTES_VERSION": "test-build",
    }
    env.pop("WISENOTES_ENVIRONMENT", None)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "0"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines: list[str] = []
    try:
        port = None
        deadline = time.monotonic() + 20
        while port is None and time.monotonic() < deadline:
            line = server.stdout.readline()
            if not line:
                break
            lines.append(line)
            m = re.search(r"http://127\.0\.0\.1:(\d+)", line)
            port = m and int(m.group(1))
        assert port, f"uvicorn never said where it listens: {lines}"
        urllib.request.urlopen(f"http://127.0.0.1:{port}/?q={SENTINEL}", timeout=5).read()
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5).read()
    finally:
        server.terminate()
        out, _ = server.communicate(timeout=10)
    lines += out.splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]  # a plain line fails here
    assert any(r["logger"].startswith("uvicorn") for r in rows), "uvicorn's records did not arrive"
    (request,) = requests_of(rows)
    assert request["url.path"] == "/"
    assert all(r["service.version"] == "test-build" for r in rows)
    assert all(r["deployment.environment"] == "dev" for r in rows)
    assert not any(r["logger"] == "uvicorn.access" for r in rows)
    assert SENTINEL not in "".join(lines)
