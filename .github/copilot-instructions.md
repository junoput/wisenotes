# Copilot / Agent Instructions — Wisenotes (concise)

Wisenotes is a FastAPI + Jinja2 app that favors server-rendered HTML and HTMX partials over heavy frontend frameworks. Agents should focus on the backend service layer, HTMX endpoint patterns, simple file-backed persistence, and plugin hooks.

- **Big picture**: HTTP routes in `app/routes/` render templates in `app/templates/`. Business rules live in `app/services/notes.py`. Storage is file-based under `data/` and accessed via `app/services/storage.py`.

- **HTMX pattern (must follow)**: HTMX endpoints return HTML fragments (not JSON). Use `response_class=HTMLResponse` and `templates.TemplateResponse()` for partial responses — see [app/routes/pages.py](app/routes/pages.py) and `app/templates/partials/hx_refresh.html`.

- **Service boundary**: All domain logic belongs in `app/services/notes.py`. Routes must use DI: `service: NoteService = Depends(get_note_service())` from [app/web/dependencies.py](app/web/dependencies.py). Do not instantiate services inside routes.

- **Persistence details**: Data is stored as JSON files under `data/`. The repository implementation in `app/services/storage.py` uses file locking — preserve `FileLock` usage on writes to avoid corruption.

- **Plugin system**: Lifecycle hooks live in `app/plugins/` (see `base.py`, `registry.py`, `word_count.py`). Hooks include `on_note_saved`, `on_export`, `on_import`. New plugins must be registered via the `PluginRegistry` used by `get_note_service()`.

- **Editor assets**: CodeMirror and editor glue are under `app/static/vendor/codemirror` and `app/static/js/editors/`. When changing editors, update templates and CSP in `app/main.py`.

- **Security / CSP**: `app/main.py` applies CSP and security headers. Adding external CDN scripts/styles requires updating that middleware or requests will be blocked.

- **Testing & running**:
  - Run tests: `pytest` (see `tests/test_health.py` for TestClient usage).
  - Local dev: `uvicorn app.main:app --reload --port 8000` (Python 3.12+).
  - Docker: `docker compose up --build` (recommended for parity with CI).

- **Formatting & typing**: Project uses `ruff` and `mypy` configured in `pyproject.toml`. Import style prefers single-line imports (see `pyproject.toml` rules).

- **Templates & partials**: Prefer small partial templates in `app/templates/partials/` for HTMX swaps. Full page shells reside in `app/templates/` (e.g., `index.html`).

- **When editing chapters**: Use `NoteService` methods (e.g., `add_chapter`, `delete_chapter`) which maintain parent/child integrity and timestamps; see `app/editor/mixed_content.py` for editor serialization.

- **Quick references**:
  - Routes & HTMX: [app/routes/pages.py](app/routes/pages.py), [app/routes/api.py](app/routes/api.py)
  - Services: [app/services/notes.py](app/services/notes.py), storage: [app/services/storage.py](app/services/storage.py)
  - DI & settings: [app/web/dependencies.py](app/web/dependencies.py)
  - Plugins: [app/plugins/registry.py](app/plugins/registry.py)
  - CSP & middleware: [app/main.py](app/main.py)

If any part of this summary is unclear or you want a longer, example-driven version (including common change patterns or a sample PR checklist), tell me which area to expand and I will iterate.
# Wisenotes AI Development Guide

## Architecture Overview

Wisenotes is a **Python-first, HTMX-driven** note-taking app built on FastAPI. It deliberately minimizes frontend complexity using server-rendered HTML with progressive enhancement, avoiding SPA patterns.

### Core Architecture Patterns

- **Backend**: FastAPI + Jinja2 templates serving HTML; HTMX handles partial updates
- **Storage**: File-based JSON repository (`JsonNoteRepository`) with file locking for concurrency
- **Service Layer**: All domain logic in `app/services/notes.py` (`NoteService`), never in routes
- **Data Model**: Hierarchical notes with nested chapters (`parent_id` relationships). Chapters can be infinitely nested.
- **Plugin System**: Lifecycle hooks (`on_note_saved`, `on_export`, `on_import`) via `PluginRegistry` in [app/plugins/registry.py](app/plugins/registry.py)

## Critical Development Patterns

### Route Design (Server-Rendered + HTMX)

Routes in `app/routes/` follow two patterns:

1. **Full page routes** (`pages.py`): Return complete HTML templates (e.g., `index.html`)
2. **HTMX partial routes** (`pages.py` + `api.py`): Return template fragments from `app/templates/partials/` for in-place DOM swaps

Example HTMX pattern from [app/routes/pages.py#L30-L43](app/routes/pages.py#L30-L43):
```python
@router.post("/notes", response_class=HTMLResponse)
async def create_note(...):
    note = service.create_note(...)
    notes = service.list_notes()
    return templates.TemplateResponse(
        "partials/hx_refresh.html", 
        {"request": request, "notes": notes, "active": note}
    )
```

**Always return HTML responses** (not JSON) from HTMX endpoints. Use `response_class=HTMLResponse` and render templates.

### Dependency Injection

Services are wired via FastAPI dependencies in [app/web/dependencies.py](app/web/dependencies.py):
- `get_note_service()` → NoteService (with repo + plugins)
- Settings from `get_settings()` (Pydantic settings with `WISENOTES_` prefix)

Never instantiate services directly in routes. Always use `service: NoteService = Depends(get_note_service)`.

### Data Persistence & Validation

- **Repository**: `JsonNoteRepository` uses `FileLock` for safe concurrent access to `data/notes.json`
- **Schemas**: Pydantic models in [app/schemas.py](app/schemas.py) enforce validation (e.g., chapter ID uniqueness, parent_id sanitization in `Note.validate_chapters()`)
- **Mutations**: All writes go through `NoteService` methods which handle:
  1. Business logic (e.g., collecting descendant chapters in `delete_chapter`)
  2. Timestamp updates (`updated_at`)
  3. Plugin notifications

### Security Headers & CSP

[app/main.py#L14-L32](app/main.py#L14-L32) sets strict security headers via middleware:
- CSP allows only `'self'` + specific CDNs (Unpkg for vendors)
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`
- When adding external scripts/styles, **update the CSP middleware** or they'll be blocked

### Chapter Hierarchies

Chapters use `parent_id` for nesting. Key operations:
- **Adding chapters**: `NoteService.add_chapter()` with optional `parent_id`
- **Deleting**: `NoteService.delete_chapter()` recursively collects descendants via `_collect_descendant_ids()`
- **Editor representation**: [app/editor/mixed_content.py](app/editor/mixed_content.py) serializes nested chapters as JSON for rich editors (e.g., CodeMirror)

When modifying chapter logic, ensure parent-child integrity in `Note.validate_chapters()`.

## Developer Workflows

### Running Locally

**Docker (recommended)**:
```bash
docker compose up --build  # App on http://localhost:8000
docker compose restart     # After code changes (hot reload via uvicorn)
```

**Native Python** (requires Python 3.12+):
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload --port 8000
```

### Testing

Run tests with:
```bash
pytest              # All tests
pytest -v           # Verbose
pytest tests/test_health.py  # Specific test
```

Test pattern (see [tests/test_health.py](tests/test_health.py)):
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)  # No need to manually wire dependencies
```

### Code Quality Tools

Configured in [pyproject.toml](pyproject.toml):
- **Ruff**: Linter + formatter (runs on save if editor configured)
- **MyPy**: Strict type checking (`strict = true`)
- Run manually: `ruff check .`, `ruff format .`, `mypy app/`

## Project-Specific Conventions

### File Organization

- `app/routes/`: Endpoint definitions (FastAPI routers)
- `app/services/`: Business logic (never in routes)
- `app/schemas.py`: Pydantic models for validation
- `app/templates/`: Jinja2 templates (full pages + `partials/` for HTMX)
- `app/static/`: CSS, JS (minimal client-side JS; mostly event handling)
- `app/plugins/`: Plugin base classes and implementations
- `data/`: Runtime data (JSON file, gitignored in production)

### Import Style

Ruff enforces `force-single-line = true` in imports:
```python
# Correct
from app.schemas import Chapter
from app.schemas import Note

# Incorrect
from app.schemas import Chapter, Note
```

### Plugin Development

Extend `Plugin` base class from [app/plugins/base.py](app/plugins/base.py):
```python
class MyPlugin(Plugin):
    def on_note_saved(self, note: Note) -> None:
        # Custom logic here
        pass
```

Register in [app/web/dependencies.py](app/web/dependencies.py) via `PluginRegistry.register()`. See [app/plugins/word_count.py](app/plugins/word_count.py) for reference.

## Common Gotchas

1. **HTMX endpoints must return HTML**, not JSON. Use `templates.TemplateResponse()` with partial templates.
2. **CSP violations**: When adding external resources, update the CSP middleware in [app/main.py](app/main.py).
3. **File locking**: `JsonNoteRepository` uses `FileLock` - don't bypass it or concurrent writes will corrupt data.
4. **Chapter validation**: `Note` model auto-sanitizes invalid `parent_id` references in `validate_chapters()`. Test edge cases.
5. **Settings prefix**: Environment variables need `WISENOTES_` prefix (e.g., `WISENOTES_DATA_DIR`).

## Export/Import Format

Versioned JSON schema (see [app/schemas.py#L52-L60](app/schemas.py#L52-L60)):
```json
{
  "version": "1.0.0",
  "exported_at": "2025-12-17T10:00:00Z",
  "notes": [...]
}
```

Validation enforces max payload size (512KB default) in [app/routes/api.py#L54-L56](app/routes/api.py#L54-L56).
