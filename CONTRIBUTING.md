# Contributing to Wisenotes

Two documents before a first change, same names as in nexora so the box's
conventions read the same everywhere:

1. [`docs/BRANCHING.md`](docs/BRANCHING.md) — the branch policy: `develop` for
   integration (the preview follows it), `main` for tagged releases (nothing
   deploys from it today), topic branches, kept `release/<x.y>` branches and
   `hotfix/` from the tag.
2. [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md) — commit format, quality
   gates and how to run them from a clean shell, pull requests and review,
   what was kept or changed from nexora and why, and where the fleet
   conventions and wisenotes differ (§5).
3. [`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md) — the fleet's language for
   logs, health, metrics and security events, and how far wisenotes is from it.

Engineering rules (architecture, security, testing conventions) are in
[`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## The short version of the workflow

- Branch from `origin/develop`: `feat/`, `fix/`, `chore/`, `docs/`, `test/`,
  `refactor/` + short slug. One branch, one logical change, days not weeks,
  pushed the day it is created.
- [Conventional Commits](https://www.conventionalcommits.org/), atomic, and
  the body carries the verification: the command and the line it printed.
- Open a PR into `develop`, small (under ~400 changed lines), with a reader who
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
  # the Playwright version must match the installed chromium build, or the run
  # fails at launch before testing anything (devbox: playwright==1.61.0 for chromium-1228)
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
- The one thing a server-side test cannot see is app.js letting a refused graph
  save (a 400 with the edit form) through htmx. `tests/graph_refusal.py` drives
  it in both arms against the same running server, and exits 1 when the reasons
  do not show. It is not part of `pytest`; run it after any change to the
  `htmx:beforeSwap` handler in app.js:

  ```sh
  .venv/bin/python tests/graph_refusal.py http://127.0.0.1:8000
  ```

  Expected: `VERDICT: PASS` in both arms. Removing the `BLOCK_SAVE` clause from
  app.js gives `VERDICT: FAIL reasons shown` in the JS-on arm.

### The JavaScript floor

Fourteen script files are tracked, and that is the floor while CodeMirror
stays, not a number to drive down:

| file | why it stays |
|---|---|
| `static/vendor/htmx/htmx.min.js` | the enhancement layer itself: fragments instead of full reloads |
| `static/js/app.js` (~190 lines) | pane state, keyboard, confirms, mounts CodeMirror and KaTeX, re-runs after swaps |
| `static/js/drag-drop.js` | drag-to-reorder; the reorder buttons are the plain path it enhances |
| `static/js/graph.js`, `static/js/graph-spec.js` | the graph block: draws a definition with JSXGraph, and the JS parser that shares `tests/graph_spec_cases.json` with `app/graph_spec.py`; without scripts the block shows its definition |
| `static/vendor/jsxgraph/jsxgraphcore.js` | JSXGraph 1.14.1, unmodified, loaded the first time a graph is on the page; `jc.compile` is false (see its README) |
| `static/js/init-layout.js` (8 lines) | sets the sidebar width before first paint; must be a blocking script, and CSP forbids inline scripts, so it is a file |
| `static/vendor/codemirror/` (7 files) | editor core, close-brackets, and one mode per offered language (python, javascript for JS and TS, clike for Java, go, rust) |

Delete CodeMirror and the floor is seven. That is a product decision (the
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

<!-- devbox-conventions CONTRIBUTING.md v6 BEGIN — generated; edit outside the markers -->
## Before you write anything, the work has a ticket

`tick` is the shared board across every project on this box. Claim before you
work — `tick list --status in_progress` to see what is taken, then
`tick start <id>` — because two agents on one ticket is the cost this exists to
avoid. Notice a defect outside your current task? `tick new bug "<title>"` and
move on; park it rather than chasing it.

Close with the REASONING, not with "done". The close is the report: it is what
the next person reads when they hit the same thing, and it is the only record of
what you decided not to do.

**A ticket is a hypothesis, not a specification.** An implementer who measures
before building is doing the job, not resisting it. More than one ticket here
has asked for a test that could not fail; the right response was to say so on
the ticket.

## What a change has to come with

### Assertions that could have failed

A test that cannot fail differently is not a test. Before believing a green,
flip something you know should change the answer and confirm it does — and do it
with the mutant asserted PRESENT before the run, because a patch that silently
fails to apply produces a green identical to a healthy control arm.

Beware the assertion that runs, on real data, and means less than it says:
`is_some()`, `is_ok()`, `!= null`, `len() > 0`, `contains(x)` on a set nobody
bounded. Each asserts the machinery produced SOMETHING. Whether it produced the
RIGHT something is the question, and making the wrong something is the cheap way
to find out.

### A vacuity floor wherever something is counted

A walker that silently finds nothing passes forever. Require a floor — at least
N suites parsed, at least N files matched — and report VACUOUS rather than a
verdict when the floor is not met. A selector that matches PARTIALLY is worse
than one that matches nothing: the empty set announces itself, a partial set
wears the shape of a pass.

### The quiet side of every switch and threshold

Asserting a warning fires proves the code can print. Only asserting it stays
SILENT when it should proves the condition is read at all. An unconditional
warning and a working detector are indistinguishable from the loud side alone.

## Reporting a result

**Name the tree and the commit.** A confident, correct result from the wrong
copy of the repository is indistinguishable from a right one.

**State the window, or do not report the null.** `--since`, `head`, `tail`, a
result cap, a page size, a retention policy, an index that only covers one
branch: each converts "absent" into "absent within a boundary you did not
mention". Say the boundary in the same sentence as the finding.

**Report a pass only when the instrument says it FINISHED.** Grep for the
terminal verdict line, not for the absence of a failure — a killed run and a
passing one look the same if you read for failures.

**Quote the line, not the exit code.** Two rules can share a status and mean
entirely different things. And `$?` after a pipeline is the LAST command's
status, so `| tail` tells you about `tail`.

## Reviewing

Read the diff, not the commit message. Read the gate output, not the merge
request's gate section. A commit can announce work its own diff does not
contain, and git says nothing when a staged path has nothing to add.

For any change to a shared predicate or helper, enumerate its consumers BEFORE
reading the diff. Reviewing the logic is not reviewing the blast radius.

When fixing a class of defect, say which instances you did NOT change, and why.
The exceptions are where the next one hides, and enumerating the untouched set
is what turns a sweep into an audit.

## Gaps

A stated gap is an assignment, not a footnote. "I could not demonstrate X"
becomes a ticket with an owner — and nobody manufactures the demonstration to
close it. Leaving a gap stated is worth more than filling it with something
built to fit.

A carve-out written inside a blocked ticket inherits that ticket's status in
everyone's head, including its author's. File it as its own ticket at the moment
you write it down.
<!-- devbox-conventions END -->
