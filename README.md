# Wisenotes – Project Plan

Product goal: a modern, fast note-taking web app where each note contains chapters and each chapter holds text content. All notes live in a single JSON document that can be exported and imported. Design for security by default, clean code, modularity, and future plugin extensibility. Target deployment: Docker container.

## 1) Scope & Basic Feature Set (MVP)
- Notes & chapters: create/edit/delete notes; per-note chapters (add/edit/delete/reorder); note title and optional tags; timestamps.
- Editing UX: fast keyboard-friendly editor, autosave (debounced), undo/redo, markdown-friendly plain text.
- Storage: server-side store (initially JSON file), plus single JSON export/import covering all notes, metadata, and app version.
- Navigation & search: note list with filters (tag/text), chapter sidebar, quick switcher.
- Safety & validation: required titles, length limits, validation on import (schema/version check), graceful error messages.
- Theming: light/dark toggle; responsive layout for mobile/desktop.
- Observability: minimal server logging hook (non-PII), feature flags for experimental features.

## 2) Architecture Overview (Python-first, minimal JS)
- Backend: FastAPI (async, typed) serving HTML via Jinja2 templates; APIs for export/import; optional Server-Sent Events for live updates.
- Frontend: server-rendered HTML with progressive enhancement via HTMX (tiny runtime, no SPA) and Hyperscript/Alpine optional; Tailwind CLI for styling; zero build-step JS beyond vendored HTMX.
- State & storage: in-process service with pluggable storage drivers (JSON file for MVP; later SQLite/Postgres). All mutations go through the service layer for validation and auditing.
- Data model: `Note { id, title, tags[], createdAt, updatedAt, chapters: Chapter[] }`; `Chapter { id, title, content, order }`. Versioned JSON envelope: `{ version, exportedAt, notes: Note[] }`.
- Plugin surface (initial design): Python entrypoints for server-side hooks (noteCreated, noteUpdated, exportRequested) and template slots; guarded client hooks via HTMX events with allowlisted behaviors.
- Security-by-design defaults: strict CSP (disallow inline scripts; hash only HTMX), HTMX config with `confirm`/`boost` limits, output escaping via templates, request size limits, rate limiting middleware.

## 3) Clean Code & Quality Baseline
- Conventions: Python 3.12+, Ruff for lint/format, MyPy for typing, Pre-commit hooks.
- Testing: Pytest for domain/services; Playwright (or pytest-playwright) for E2E export/import and note flows.
- Accessibility: semantic HTML, ARIA for navigation/editor, focus management, color-contrast checks; server-rendered forms work without JS.
- Documentation: ADRs for major decisions, `docs/` for plugin API draft and data schema, `SECURITY.md` for hardening notes.

## 4) Security Practices (MVP-level)
- Content handling: sanitize rendered markdown on the server; escape all output; enforce size limits on notes/chapters and overall JSON payloads.
- Supply chain: `uv.lock`/`requirements.txt` committed; `pip audit`/`pip-audit` in CI; optional Renovate.
- Headers: CSP (no inline except hashed HTMX), X-Content-Type-Options, Referrer-Policy, Permissions-Policy, frame busting, HSTS (behind TLS terminator). Disable `eval`/dangerous Jinja constructs.
- Auth (future-ready): storage/service interfaces support swapping to authenticated persistence; plugin APIs allowlisted and versioned.

## 5) Project Structure (planned)
- `app/`: FastAPI app, routers, services, models, schemas, plugin registry, dependency injection wiring.
- `app/templates/`: Jinja2 templates with HTMX partials; layout, note list, editor, modals.
- `app/static/`: CSS (Tailwind build), minimal JS (vendored HTMX/hyperscript), icons.
- `plugins/`: sample server-side plugins (e.g., word count on save, export hook) using Python entrypoints.
- `tests/`: unit and integration tests; `e2e/` for Playwright.
- `infra/`: Dockerfile, docker-compose for local run, CI workflows.
- `docs/`: ADRs, plugin API draft, data schema, SECURITY.md.

## 6) Implementation Steps
1. Bootstrap repo: Python package layout; uv/venv; Ruff + MyPy + Pre-commit; FastAPI + Uvicorn; Tailwind CLI (via `npx tailwindcss` or `bun` only for CSS build step).
2. Define domain: Pydantic models + services; versioned JSON format and migration stubs; zod equivalent not needed.
3. Storage: file-based JSON repository with read/write locks; abstraction for future DB; validation and error handling.
4. UI shell (server-rendered): base layout, note list, chapter list, editor form; HTMX endpoints for partial updates; keyboard shortcuts via minimal JS (no SPA).
5. Editor: textarea with markdown preview (server-rendered or small client-side markdown lib), debounced autosave via HTMX `trigger`/`delay`, chapter reorder via HTMX + server ordering.
6. Search & navigation: server-side search over titles/content; tag filter; quick switcher endpoint returning partial.
7. Plugin scaffold: Python entrypoint registry for lifecycle events; limited client hooks via HTMX events; sample plugin (word count on save, export metadata injector).
8. Testing: Pytest for services/routes, snapshot tests for templates, Playwright for export/import and CRUD flows.
9. Security hardening: CSP, size limits, rate limiting middleware, markdown sanitization, dependency audit, locked dependencies.
10. Dockerization: multi-stage (builder for deps + Tailwind CSS; final slim Python image, non-root), health endpoint; docker-compose for local run.
11. CI: lint+type+test on PR; container build; pip-audit; optional preview deploy to container platform.

## 7) Data Export/Import Contract (draft)
- JSON schema versioned: `version: semver`, `notes: Note[]`, `exportedAt` ISO string.
- Validation: reject unknown/oversized payloads; cap total size; report per-note errors.
- Import flow: preview summary (counts, size), dry-run validation, then replace or merge strategy.

## 8) Modularity & Plugin Concepts
- Service interfaces: storage, search, logger, feature flags exposed via dependency injection; plugins receive limited capabilities (register lifecycle hooks, enrich exports, add template partials via allowlisted slots).
- Isolation: plugins cannot perform direct template injection without slot approval; sanitize any plugin-rendered text; restrict filesystem access.
- Versioning: plugin manifest with semver + required API version; loader checks compatibility and disables incompatible plugins.

## 9) Deployment & Ops (initial)
- Container: multi-stage Dockerfile, non-root user, runs Uvicorn behind a minimal ASGI server; serve static assets with far-future cache headers plus CSP.
- Config: runtime env via `.env` mounted at run; 12-factor settings; feature flags for plugins and experimental UI.
- Monitoring (future): privacy-respecting telemetry toggle; structured logs; readiness/liveness endpoints.

## 10) Next Delivery
- Generate initial Python-first codebase skeleton (FastAPI + Jinja + HTMX, lint/type/test configs, storage abstraction, sample plugin, Dockerfile + compose) aligned to this plan.

## Developer Documentation

### Extending Wisenotes

- **[Block Types Reference](docs/BLOCK_TYPES_REFERENCE.md)** - Quick reference for all block types
- **[Adding Block Types](docs/ADDING_BLOCK_TYPES.md)** - Complete guide to adding new block types
- **[Cleanup Summary](docs/CLEANUP_SUMMARY.md)** - Recent refactoring and improvements

### Architecture Notes

Wisenotes uses a modular block type system:
- Block types are defined in `app/block_types.py`
- Configuration includes emoji, color, nesting rules, and language options
- Adding a new block type requires minimal changes (5-15 lines of code)
- All templates automatically receive block type configuration

## Quickstart (dev)
- Prereqs: Python 3.12, `pip`.
- Setup: `python -m venv .venv && source .venv/bin/activate && pip install -e .[dev]`.
- Run dev server: `uvicorn app.main:app --reload` and open `http://localhost:8000`.
- Tests: `pytest` (unit) — add Playwright later for E2E.
- Docker: `docker compose up --build`.
