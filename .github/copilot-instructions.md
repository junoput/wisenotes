# Copilot / Agent Instructions — Wisenotes

Wisenotes is a FastAPI + Jinja2 note-taking app using server-rendered HTML and HTMX partials. Notes contain chapters with typed content blocks (text, code, math, media). Storage is file-based JSON.

---

## Architecture

```
app/
├── main.py                  # FastAPI app, middleware, CSP, router mounting
├── config.py                # Settings (pydantic-settings) + accessibility config
├── schemas.py               # Pydantic models: Note, Chapter, NoteCreate, NoteUpdate, NoteDocument
├── routes/
│   ├── pages.py             # HTML/HTMX page endpoints (server-rendered)
│   └── api.py               # JSON REST API (/api/*)
├── services/
│   ├── notes.py             # NoteService — all business logic
│   ├── storage.py           # JsonNoteRepository — file-based persistence
│   └── image_processing.py  # Pillow-based media processing
├── blocks/                  # Modular block system (auto-discovered)
│   ├── base.py              # BaseBlock dataclass
│   ├── registry.py          # Auto-discovery + registry
│   └── <type>/block.py      # chapter, code, math, media, paragraph, text
├── editor/
│   └── mixed_content.py     # Mixed-content editor helpers
├── plugins/
│   ├── base.py              # PluginBase hooks interface
│   └── registry.py          # Plugin lifecycle management
├── templates/               # Jinja2 (base, index, partials/, components/)
├── static/                  # CSS, JS, vendor libs
└── web/
    └── dependencies.py      # FastAPI dependency injection wiring
tests/                       # Pytest test suite
data/                        # Runtime note storage (one folder per note)
```

### Data Flow

1. **Request** → `routes/pages.py` or `routes/api.py`
2. **Route** calls `NoteService` (injected via `Depends(get_note_service)`)
3. **NoteService** calls `JsonNoteRepository` for persistence
4. **Response**: pages return HTML fragments (HTMX) or full pages; API returns JSON

### Router Ordering (Critical)

In `app/main.py`, routers are included in this order:
1. `api.router` (prefix `/api`) — must come first
2. `pages.router` — has a catch-all `/{note_name}` route

**Never add new catch-all GET routes to `pages.py`.** The existing `/{note_name}` already catches unmatched paths. New API endpoints go in `api.py` under the `/api` prefix.

---

## Strict Rules

### HTMX Endpoints Return HTML, Not JSON

```python
@router.post("/notes", response_class=HTMLResponse)
async def create_note(...):
    return templates.TemplateResponse("partials/hx_refresh.html", {...})
```

### Service Boundary

All business logic belongs in `NoteService`. Routes only validate HTTP input and call the service. Never instantiate services in routes — use DI:
```python
service: NoteService = Depends(get_note_service)
```

### No Orphan Code

- Don't add files that aren't imported or used
- Don't add backward-compatibility wrappers — update call sites directly
- Don't add empty stub modules. If a feature isn't implemented, don't create it

### Logging

- Use `logging.getLogger(__name__)` per module
- Log at `info` level for significant operations (create, delete, import/export)
- Log at `error` level only for actual failures
- Never log full request/response bodies or content previews
- Never add verbose DEBUG logging to route handlers. Keep routes thin

### Error Handling

- Raise `HTTPException` in routes for client errors (400, 404, 413)
- Raise `ValueError` in service methods for invalid operations
- Don't catch generic `Exception` in routes unless re-raising as 500
- Don't add try/except blocks around code that can't fail

---

## Block System

Blocks live in `app/blocks/<name>/` and are auto-discovered at startup.

### Adding a New Block

1. Create `app/blocks/myblock/block.py`:
   ```python
   from dataclasses import dataclass
   from app.blocks.base import BaseBlock

   @dataclass
   class MyBlock(BaseBlock):
       name: str = "myblock"
       display_name: str = "My Block"
       emoji: str = "🎯"
       color: str = "#10b981"
       can_nest: bool = False
       editor: str = "textarea"

   block = MyBlock()  # Required — registry looks for this
   ```
2. Create `app/blocks/myblock/templates/display.html` and `edit.html`
3. Restart — auto-discovered, no registration code needed

### Block Rules

- `chapter` is the only block allowed at root level and the only container (`can_nest=True`)
- `text` is the fallback for unknown types — `get_block("nonexistent")` returns text
- Block API: `get_block(name)`, `get_all_blocks()`, `get_block_choices()`

---

## Storage

- Per-note folders: `data/<name>/<name>.json`
- Media: `data/<name>/media/`
- Concurrency: `FileLock` — never bypass it
- Writes: atomic via `.tmp` file + `os.replace()`
- Public methods: `derive_name()`, `ensure_unique_name()`, `name_to_title()`

---

## Configuration

Environment variables use prefix `WISENOTES_`:
- `WISENOTES_DATA_DIR` — path to data storage directory

Settings are loaded via `app/config.py` using pydantic-settings with `lru_cache`.

---

## Security

- **CSP**: strict per-request nonce set in `app/main.py` middleware. When adding CDNs or inline scripts, update the CSP header
- **Headers**: X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy
- **Storage**: path traversal protection on media endpoints, size limits on uploads (10MB)
- **Imports**: max payload size enforced (`max_payload_bytes` setting)

---

## Testing

Tests live in `tests/` using pytest + FastAPI TestClient. Fixtures in `tests/conftest.py`:
- `data_dir` / `repo` / `service` — isolated temp storage per test
- `client` — TestClient with dependency overrides

### Test Conventions

- Test files: `tests/test_<area>.py`
- Use the `service` fixture for unit-testing business logic directly
- Use the `client` fixture for HTTP-level integration tests
- Every new feature or bug fix must include tests
- Run `pytest tests/` before committing — all tests must pass

---

## Run

```bash
# Docker
docker compose up --build

# Native (Python 3.12+)
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload --port 8000

# Tests
pytest tests/
```

---

## Clean Code Checklist (for every change)

1. **Scope**: Only change what's needed. Don't refactor unrelated code
2. **No dead code**: Remove unused imports, variables, files
3. **No verbose logging**: Keep log messages short and actionable
4. **DRY**: Extract helpers only when logic is duplicated 3+ times
5. **Flat over nested**: Avoid deep nesting in route handlers — early-return on errors
6. **Tests**: Add or update tests for any behavior change
7. **Types**: Use Python 3.12+ type syntax (`list[str]` not `List[str]`, `str | None` not `Optional[str]`)
8. **Imports**: One import per line, sorted (enforced by ruff)

---

## File Reference

| Area | Files |
|------|-------|
| App entry | `app/main.py` |
| Routes | `app/routes/pages.py`, `app/routes/api.py` |
| Service | `app/services/notes.py` |
| Storage | `app/services/storage.py` |
| Schemas | `app/schemas.py` |
| Blocks | `app/blocks/` (see `docs/BLOCKS_SYSTEM.md`) |
| DI | `app/web/dependencies.py` |
| Config | `app/config.py` |
| Plugins | `app/plugins/base.py`, `app/plugins/registry.py` |
| Tests | `tests/conftest.py`, `tests/test_*.py` |
