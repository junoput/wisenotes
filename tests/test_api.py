"""Tests for API routes."""

import json


class TestHealthEndpoint:
    def test_html_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.text == "ok"

    def test_api_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestNoteAPI:
    def test_create_note(self, client):
        resp = client.post("/api/notes", json={"title": "API Note"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "API Note"
        assert "id" in data

    def test_list_notes(self, client):
        client.post("/api/notes", json={"title": "One"})
        client.post("/api/notes", json={"title": "Two"})
        resp = client.get("/api/notes")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_note(self, client):
        created = client.post("/api/notes", json={"title": "Get Me"}).json()
        resp = client.get(f"/api/notes/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_note_not_found(self, client):
        resp = client.get("/api/notes/nonexistent")
        assert resp.status_code == 404

    def test_update_note(self, client):
        created = client.post("/api/notes", json={"title": "Old"}).json()
        resp = client.put(
            f"/api/notes/{created['id']}",
            json={"title": "New"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New"

    def test_delete_note(self, client):
        created = client.post("/api/notes", json={"title": "Delete Me"}).json()
        resp = client.delete(f"/api/notes/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        # Verify gone
        resp = client.get(f"/api/notes/{created['id']}")
        assert resp.status_code == 404

    def test_delete_nonexistent_note(self, client):
        resp = client.delete("/api/notes/nonexistent")
        assert resp.status_code == 404


class TestExportImportAPI:
    def test_export_empty(self, client):
        resp = client.get("/api/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["notes"] == []
        assert "version" in data

    def test_export_with_notes(self, client):
        client.post("/api/notes", json={"title": "Export Me"})
        resp = client.get("/api/export")
        assert len(resp.json()["notes"]) == 1

    def test_import_empty_file(self, client):
        resp = client.post("/api/import", files={"file": ("notes.json", b"", "application/json")})
        assert resp.status_code == 400

    def test_import_invalid_json(self, client):
        resp = client.post(
            "/api/import",
            files={"file": ("notes.json", b"not json", "application/json")},
        )
        assert resp.status_code == 400
