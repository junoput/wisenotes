# Contributing to Wisenotes

Two documents before a first change, same names as in nexora so the box's
conventions read the same everywhere:

1. [`docs/BRANCHING.md`](docs/BRANCHING.md) — the branch policy: `main` only,
   topic branches, releases as tags.
2. [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md) — commit format, quality
   gates and how to run them from a clean shell, pull requests and review, and
   what was kept or changed from nexora and why.

Engineering rules (architecture, security, testing conventions) are in
[`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## The short version of the workflow

- Branch from `origin/main`: `feat/`, `fix/`, `chore/`, `docs/`, `test/`,
  `refactor/` + short slug. One branch, one logical change, days not weeks,
  pushed the day it is created.
- [Conventional Commits](https://www.conventionalcommits.org/), atomic, and
  the body carries the verification: the command and the line it printed.
- Open a PR into `main`, small (under ~400 changed lines), with a reader who
  did not write it. Merged `--no-ff`; the topic branch is deleted after an
  ancestry check, never on the strength of its name.
- Tests ship in the same commit as the code they cover.

## Quality gates (CI enforces these)

```sh
ruff check app tests
ruff format --check app tests
pytest tests/
```

Clean-shell recipe, expected output and what a green does and does not
cover: `docs/GIT_WORKFLOW.md` §2. A change that touches templates or
JavaScript is also driven in a browser; the rule below says how.

## Ground rules worth repeating

### The no-JavaScript rule

The app must work with JavaScript disabled; JavaScript enhances. That is a
review criterion, checked per change:

- Every `hx-get`/`hx-post`/`hx-delete` sits on an element that also works
  without htmx: a `<form action method>` or an `<a href>`. A `<div hx-get>`
  is a dead end for a plain browser.
- Every route a fragment can reach also renders a full page when the request
  has no `HX-Request` header; a POST without that header answers with a
  redirect (303) to the page, not with a fragment.
- Anything the server can do, the server does: rendering code, listing media,
  reordering. JavaScript may do it faster or prettier, never only.
- To check by hand: open the page with JavaScript disabled (Firefox
  `about:config` `javascript.enabled=false`; Chromium DevTools > Settings >
  Debugger > Disable JavaScript) and drive the journey.
- To check mechanically: `tests/journeys.py` drives fourteen journeys in a
  real browser twice, once with scripts off and once with them on (the
  control arm, which proves the driver can see success), against a running
  server:

  ```sh
  .venv/bin/pip install -e '.[e2e]' && .venv/bin/playwright install chromium
  .venv/bin/uvicorn app.main:app --port 8000 &     # any writable data dir
  .venv/bin/python tests/journeys.py http://127.0.0.1:8000
  ```

  Exit 0 is a pass in both arms; exit 1 names the failed journey; exit 2 is
  VACUOUS, meaning an arm observed fewer than fourteen journeys or could not
  tell scripts-on from scripts-off, and no verdict is reported. Expected
  output ends with `VERDICT: PASS (14/14 journeys observed)` for each arm.
  On devbox the cached chromium needs two variables before the run:
  `LD_LIBRARY_PATH=$HOME/.local/chromium-libs/extracted/usr/lib/x86_64-linux-gnu`
  and `FONTCONFIG_FILE` pointing at a `fonts.conf` whose `<dir>` is
  `$HOME/.local/chromium-libs/extracted/usr/share/fonts`.

### The JavaScript floor

Eleven script files are tracked, and that is the floor while CodeMirror
stays, not a number to drive down:

| file | why it stays |
|---|---|
| `static/vendor/htmx/htmx.min.js` | the enhancement layer itself: fragments instead of full reloads |
| `static/js/app.js` (~190 lines) | pane state, keyboard, confirms, mounts CodeMirror and KaTeX, re-runs after swaps |
| `static/js/drag-drop.js` | drag-to-reorder; the reorder buttons are the plain path it enhances |
| `static/js/init-layout.js` (8 lines) | sets the sidebar width before first paint; must be a blocking script, and CSP forbids inline scripts, so it is a file |
| `static/vendor/codemirror/` (7 files) | editor core, close-brackets, and one mode per offered language (python, javascript for JS and TS, clike for Java, go, rust) |

Delete CodeMirror and the floor is four. That is a product decision (the
code editor becomes a plain textarea, which already works with scripts
off), not a cleanup; make it on a ticket, not in passing.

### Third-party hosts

The app must stay usable when only its own host answers. Every asset a
journey needs is served from `/static`: htmx is vendored for that reason
(commit 6e6acdd, after the vendored copy turned out to be a truncated
stub). One exception is deliberate: **KaTeX loads from cdn.jsdelivr.net**
with subresource integrity. It renders math blocks and nothing else; with
the CDN unreachable the formula source stays visible as text, and vendoring
it would add three files plus about sixty font files to a tree this project
is trying to keep small. The check is the driver with every non-server host
aborted:

```sh
.venv/bin/python tests/journeys.py http://127.0.0.1:8000 --block-cdn
```

Expected: `PASS (14/14 journeys observed)` in both arms. Anything a journey
needs may not come from a CDN; anything that does come from one must
degrade to readable content, and this run is how that is shown.

## Dev-box conventions are not part of the contract

Lane worktrees, `tick mr`, the shared `gate` tool and the orchestrator's
review are how work is organised on the development box. A contributor
without the box who follows the two documents above and this page is
compliant.
