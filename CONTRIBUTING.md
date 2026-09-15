# Contributing to Wisenotes

One document: branch policy, commit rules, quality gates, review. Wisenotes is
small enough that splitting these into three files would cost more in reading
than it buys in structure. The rules are adapted from nexora's
`docs/BRANCHING.md`, `docs/GIT_WORKFLOW.md` and `CONTRIBUTING.md`; §6 says what
was kept, what was changed, and why.

Engineering rules (architecture, security, testing conventions) live in
[`.github/copilot-instructions.md`](.github/copilot-instructions.md). Read both
before a first change.

## 1. Branches

```
main       ──●────●────●────●──▶   the only permanent branch; every commit deployable
              ▲    ▲    ▲
fix/x    ─────┘    │    │           short-lived topic branches, merged --no-ff
feat/y   ──────────┘    │
chore/z  ───────────────┘
```

- **`main` is the only permanent branch.** It is what `docker compose up
  --build` deploys. Protected: no direct pushes, no force-pushes, no rewriting.
- **There is no `develop`.** A second permanent branch buys a staging line
  between "merged" and "released" for a project with several developers and
  a release train. Wisenotes has one deployment surface and one operator;
  `develop` would double every merge and make `main` lag the reviewed state
  for no reader. If that changes, add it then, with a written reason.
- **Every change is a topic branch** cut from `origin/main`, named
  `<type>/<short-kebab-slug>`: `feat/`, `fix/`, `chore/`, `docs/`, `test/`,
  `refactor/`. The name should let a reader guess the content. One branch,
  one logical change; if it grows a second purpose, split it.
- **Short-lived.** Days, not weeks. Push the branch the day it is created.
- **Rebase, do not merge `main` into a topic branch.** `git fetch origin &&
  git rebase origin/main`. Force-push your own unshared branch with
  `--force-with-lease` only, and never after review has started without
  saying so.
- **Delete at merge**, local and remote. Before deleting any branch, prove it
  landed: `git merge-base --is-ancestor <branch> origin/main` must succeed
  for the branch's current tip. `git branch --merged` is not proof. If the
  answer is unclear, leave the branch and say so.
- **Releases are tags on `main`**: `vMAJOR.MINOR.PATCH`, semantic versioning,
  created when the container is rebuilt for the operator's server. The
  version in `pyproject.toml` moves in the same commit as the tag.

## 2. Commits

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <imperative summary, <= 72 chars>

<body: what changed and WHY; how it was verified, with the command and
its result line. Wrap at ~100.>

<footer: Fixes <ticket id>, BREAKING CHANGE: ...>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `build`, `ci`, `chore`,
`revert`. Imperative mood, no trailing period.

- **Atomic.** One logical change per commit; build and tests pass at every
  commit. Never mix a refactor with a behaviour change.
- **The body carries the verification**, not just the intent: the command run
  and the line it printed (`pytest tests/` -> `61 passed`). "Tests pass" with
  no output is a claim; the line is evidence.
- **Before deleting anything, say how you know it is unused.** A file that
  looks unused and a file that is unused are different things; the commit
  names the grep (or the runtime check) that separated them.
- Tests ship in the same commit as the code they cover.
- Never commit secrets, `.env`, `data/`, build output, or commented-out code.

## 3. Quality gates

CI (`.github/workflows/ci.yml`) runs these on every push and pull request,
and a pull request cannot merge red:

```sh
ruff check app tests
ruff format --check app tests
pytest tests/
```

Run them locally before opening the PR; on a warm venv the three take under
five seconds. Green means green: a flaky test is a bug with a ticket, not a
retry.

A green here says what it ran and nothing more: unit and HTTP-level tests
against the FastAPI test client on Linux. It does **not** drive a browser. A
change that touches templates or JavaScript is verified by hand against a
running server (see §4) and the PR says which journeys were driven.

## 4. The no-JavaScript rule

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
- To check: open the page with JavaScript disabled (Firefox `about:config`
  `javascript.enabled=false`, Chromium DevTools > Settings > Debugger >
  Disable JavaScript, or Playwright `java_script_enabled=False`), drive the
  journey, and name it in the PR. `curl` on the form's action with its fields
  is a sufficient check for a single form.

## 5. Pull requests and review

- Target `main`. Small: aim for under ~400 changed lines; a large change is a
  stack of small PRs.
- Description: what changed, why, how it was verified (commands and their
  output), what a reviewer should look at first, the ticket id.
- **At least one reader who did not write it.** On the dev box that is the
  `@code-reviewer` subagent or the operator; the author never merges their
  own PR unreviewed.
- Merge with a merge commit (`--no-ff`), not squash. The atomic commits and
  their verification bodies are the record; squashing throws them away, and
  `main` stays bisectable per logical change either way.
- Resolve review threads by changing code or by explicit agreement in the
  thread, never by clicking resolve.
- Broken `main` is the top priority for whoever broke it; revert first, fix
  after. Reverting is cheap.

## 6. What was kept from nexora, what changed, and why

Kept as-is: Conventional Commits and atomic commits; `<type>/<slug>` branch
names; short-lived branches pushed on day one; rebase-not-merge for topic
branches; delete-at-merge with an ancestry check rather than a name check;
small PRs; one non-author reviewer; green-means-green; releases as
semver tags; revert-first on a broken integration branch.

Changed:

| nexora | wisenotes | why |
|---|---|---|
| `main` + `develop` + `ios/develop` | `main` only | One deployment surface, one operator; a staging branch has no reader here. |
| `hotfix/*` from `main`, back-merged to `develop` | just `fix/*` | With one permanent branch there is nothing to back-merge into. |
| `release/*` branches | none; tag on `main` | No stabilisation window is needed for a repo this size. |
| squash-merge topic branches | `--no-ff` merge commits | Commit bodies here carry the verification; squashing loses it. |
| `cargo fmt/clippy/test/deny` | `ruff check`, `ruff format --check`, `pytest` | Python toolchain. No dependency-audit step yet; add `pip-audit` when there is a reason to. |
| three documents | one | Three files for a 72-file project is the kind of thing this project is trying to stop doing. |
| lane workflow, `tick mr`, gate tool | not required by this doc | Those are dev-box conventions, documented in the box's own rules; a contributor without the box follows §1–§5 and is compliant. |

Added, not in nexora: §4, the no-JavaScript rule, and the "say how you know
it is unused" commit rule. Both exist because the audit that produced this
document found the app broken without JavaScript in nine journeys, 22 files
nothing loaded, and nine more modules with one consumer or none.
