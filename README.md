# Wisenotes

A fast, server-rendered note-taking web app. Each note contains chapters with typed content blocks (text, code, math, media). Built with Python, FastAPI, Jinja2, and HTMX — no SPA, no build step.

## Features

- **Notes & chapters** — create, edit, delete, reorder; drag-and-drop chapter ordering
- **Block types** — paragraph, code (syntax-highlighted), math (LaTeX/AsciiMath), media (images), nested chapters
- **Export / import** — full JSON export and import of all notes
- **Keyboard-friendly** — configurable accessibility keybindings
- **Light / dark theme** — toggle via UI
- **Strict security** — per-request CSP nonce, secure headers, atomic file writes, path traversal protection
- **Plugin hooks** — extensible server-side lifecycle events

## Quickstart

### Docker (recommended)

```bash
docker compose up --build
```

Open <http://localhost:8000>.

### Native

Requires Python 3.12+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload --port 8000
```

### Tests

```bash
pytest tests/
```

## Project Structure

| Path | Purpose |
|------|---------|
| `app/routes/` | FastAPI route handlers (pages + API) |
| `app/services/` | Business logic (`NoteService`) and file storage |
| `app/blocks.py` | Block type catalogue |
| `app/templates/` | Jinja2 templates and HTMX partials |
| `app/plugins/` | Server-side plugin hooks |
| `app/web/` | Dependency injection wiring |
| `data/` | File-based note storage (one folder per note) |
| `tests/` | Pytest test suite |

## Deployment

- **Docker**: multi-stage build, non-root user, health check at `/health`
- **Volumes**: mount `/data` for persistent note storage
- **Config**: environment variables prefixed `WISENOTES_` (e.g. `WISENOTES_DATA_DIR`)
- **Dev override**: `docker-compose.override.yml` adds hot-reload and source mounting

## Documentation

