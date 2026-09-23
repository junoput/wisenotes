# Wisenotes

A fast, server-rendered note-taking web app. Each note contains chapters with typed content blocks (text, code, math, media). Built with Python, FastAPI, Jinja2, and HTMX — no SPA, no build step.

## Features

- **Notes & chapters** — create, edit, delete, reorder; drag-and-drop chapter ordering
- **Block types** — paragraph, code (syntax-highlighted), math (LaTeX/AsciiMath), media (images), nested chapters
- **Export / import** — JSON export of everything; zip export per note or of all notes with images; import a `.json` or `.zip` from the "+" chooser (new ids, images re-encoded, archive inspected before anything is read)
- **Keyboard-friendly** — arrow-key navigation between notes and blocks
- **Strict security** — CSP, secure headers, atomic file writes, path traversal protection
- **Self-contained** — every asset the app needs is served by the app; only KaTeX (math rendering) comes from a CDN and math falls back to its source text without it

## Quickstart

### Container (how it is deployed)

```bash
deploy/deploy.sh --ref HEAD     # builds the image with podman, starts it on :8000, smoke-tests it
```

Open <http://localhost:8000>. `deploy/README.md` has the production layout,
the data path and what happens on a bad deploy.

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

Needs Python 3.12; see [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md) for a clean-shell
recipe and [CONTRIBUTING.md](CONTRIBUTING.md) for the browser journey driver.

## Project Structure

| Path | Purpose |
|------|---------|
| `app/routes/` | FastAPI route handlers (pages + API) |
| `app/services/` | Business logic (`NoteService`) and file storage |
| `app/blocks.py` | Block type catalogue |
| `app/templates/` | Jinja2 templates and HTMX partials |
| `data/` | File-based note storage (one folder per note) |
| `tests/` | Pytest test suite |

## Deployment

- **Container**: multi-stage image, non-root user, one `podman run` per host via `deploy/deploy.sh`, smoke-tested (`/health` and `GET /`), rolled back if the new image does not answer
- **Volumes**: mount `/data` for persistent note storage
- **Config**: environment variables prefixed `WISENOTES_` (e.g. `WISENOTES_DATA_DIR`)

## Documentation

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (start here, the no-JavaScript rule), [docs/BRANCHING.md](docs/BRANCHING.md) and [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md) (commits, gates, review).
