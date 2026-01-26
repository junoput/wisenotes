# Copilot / Agent Instructions — Wisenotes

Wisenotes is a FastAPI + Jinja2 app using server-rendered HTML and HTMX partials. Focus on the backend service layer, HTMX patterns, file-backed storage, plugin hooks, and the **modular block system**.

## Big Picture

- **Routes** in `app/routes/` render templates in `app/templates/`
- **Domain logic** lives in `app/services/notes.py` (`NoteService`)
- **Storage** is file-based under `data/` via `JsonNoteRepository` in `app/services/storage.py`
- **Blocks** are modular in `app/blocks/<type>/` with auto-discovery (see below)

## HTMX Rule (Strict)

HTMX endpoints must return **HTML fragments**, not JSON. Use:
```python
@router.post("/notes", response_class=HTMLResponse)
async def create_note(...):
    return templates.TemplateResponse("partials/hx_refresh.html", {...})
```

## Service Boundary

All business rules belong in `NoteService`. Routes use DI:
```python
service: NoteService = Depends(get_note_service)
```
Never instantiate services in routes.

## Modular Block System

Blocks live in `app/blocks/<name>/` with auto-discovery:

```
app/blocks/
├── base.py           # BaseBlock class
├── registry.py       # Auto-discovery
├── chapter/          # Container block (special)
│   ├── block.py
│   └── templates/
├── code/             # Syntax-highlighted code
├── math/             # LaTeX/AsciiMath formulas
├── media/            # Images
├── paragraph/        # Simple text
└── text/             # Default fallback
```

### Adding a New Block

1. Create folder: `app/blocks/myblock/templates/`
2. Create `block.py`:
   ```python
   from dataclasses import dataclass, field
   from app.blocks.base import BaseBlock

   @dataclass
   class MyBlock(BaseBlock):
       name: str = "myblock"
       display_name: str = "My Block"
       emoji: str = "🎯"
       color: str = "#10b981"
       can_nest: bool = False
       editor: str = "textarea"  # or "codemirror", "media"

   block = MyBlock()  # Required for auto-discovery
   ```
3. Create `templates/display.html` and `templates/edit.html`
4. Restart — block is auto-discovered!

### Special Blocks

- **`chapter`**: Only block allowed at root level, can contain children
- **`text`**: Default fallback for unknown block types

### Block API

```python
from app.blocks import get_block, get_all_blocks

code_block = get_block("code")  # Get specific block
unknown = get_block("nonexistent")  # Falls back to "text"
all_blocks = get_all_blocks()  # Dict of all blocks
```

## Storage

- Notes stored per-folder: `data/<name>/<name>.json`
- Media under `data/<name>/media/`
- Uses `FileLock` — never bypass it
- Writes are atomic (`.tmp` → `replace()`)

## Settings & Environment

Env vars use prefix `WISENOTES_`:
- `WISENOTES_DATA_DIR`
- `WISENOTES_ENABLE_SAMPLE_PLUGINS`

## CSP & Static Assets

`app/main.py` sets strict CSP with per-request nonce. When adding CDNs or external assets, update the CSP middleware.

## Run & Test

```bash
# Docker (recommended)
docker compose up --build

# Native (Python 3.12+)
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload --port 8000

# Tests
pytest tests/
```

## Quick References

| Area | Files |
|------|-------|
| Routes | `app/routes/pages.py`, `app/routes/api.py` |
| Service | `app/services/notes.py` |
| Storage | `app/services/storage.py` |
| Blocks | `app/blocks/` (see `docs/BLOCKS_SYSTEM.md`) |
| DI | `app/web/dependencies.py` |
| Plugins | `app/plugins/registry.py` |
| CSP | `app/main.py` |
