# Git Workflow & Commit Rules

> **Audience:** every contributor. Branch policy is in
> [`BRANCHING.md`](BRANCHING.md); the short version and the project's own
> rules are in [`CONTRIBUTING.md`](../CONTRIBUTING.md).
> **Model:** `main` (deployment) + `develop` (integration) + short-lived topic
> branches, merged `--no-ff`; promotion `develop -> main` by pull request and tag.

## 1. Commit rules

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

## 2. Quality gates

CI (`.github/workflows/ci.yml`) runs these on every push and pull request,
and a pull request cannot merge red:

```sh
ruff check app tests
ruff format --check app tests
pytest tests/
```

### Running them from a clean shell

Python 3.12 or newer is required. If `python3.12` is on your PATH:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/pytest tests/
```

If the system Python is older (devbox has 3.11 and no sudo), bootstrap a 3.12
with `uv` in a throwaway venv; nothing is installed outside the checkout:

```sh
python3 -m venv .venv-uv && .venv-uv/bin/pip install -q uv
.venv-uv/bin/uv venv --python 3.12 .venv
.venv-uv/bin/uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/pytest tests/
```

The venv must be named `.venv`: the dev box's shared `gate` tool looks only
there. Expected last line today: `NN passed` with no `failed`; a run that
prints only dots and no summary did not finish.

On a warm venv the three take under five seconds. Green means green: a
flaky test is a bug with a ticket, not a retry.

A green here says what it ran and nothing more: unit and HTTP-level tests
against the FastAPI test client on Linux, including `tests/test_journeys_nojs.py`,
which submits the real forms out of the rendered HTML the way a browser
with scripts off would. It does **not** run a browser, so it cannot see
htmx, CodeMirror or KaTeX. For a change that touches templates or
JavaScript, also run the browser driver (`CONTRIBUTING.md`, the no-JavaScript rule) and name the result in the PR.

## 3. Pull requests and review

- Target `develop` (only a hotfix and a promotion target `main`). Small: aim
  for under ~400 changed lines; a large change is a
  stack of small PRs.
- Description: what changed, why, how it was verified (commands and their
  output), what a reviewer should look at first, the ticket id.
- **At least one reader who did not write it.** On the dev box that is the
  `@code-reviewer` subagent or the operator; the author never merges their
  own PR unreviewed.
- Merge with a merge commit (`--no-ff`), not squash. The atomic commits and
  their verification bodies are the record; squashing throws them away, and
  `develop` and `main` stay bisectable per logical change either way.
- Resolve review threads by changing code or by explicit agreement in the
  thread, never by clicking resolve.
- Broken `develop` or `main` is the top priority for whoever broke it; revert
  first, fix
  after. Reverting is cheap.

## 4. What was kept from nexora, what changed, and why

Kept as-is: Conventional Commits and atomic commits; `<type>/<slug>` branch
names; short-lived branches pushed on day one; rebase-not-merge for topic
branches; delete-at-merge with an ancestry check rather than a name check;
small PRs; one non-author reviewer; green-means-green; releases as
semver tags; revert-first on a broken integration branch.

Changed:

| nexora | wisenotes | why |
|---|---|---|
| `main` + `develop` + `ios/develop` | `main` + `develop` | Operator's decision, 2026-09-21: fleet consistency over per-project minimalism, so every repo on the box has the same branch model. An earlier draft had `main` only, on the reasoning that one deployment surface and one operator gave a staging branch no reader; that reasoning was sound on its premise and the premise changed. No `ios/develop`: no block owns a second integration line here. |
| `hotfix/*` from `main`, back-merged to `develop` | `fix/*` from `main`, back-merged to `develop` | Same flow, plainer name; a hotfix is a fix that cannot wait for promotion. |
| `release/*` branches | none; promote `develop -> main` by PR and tag | No stabilisation window is needed for a repo this size; promotion is a `--no-ff` merge plus a tag. |
| squash-merge topic branches, merge commits for release/hotfix | `--no-ff` merge commits everywhere | Commit bodies here carry the verification; squashing loses it. |
| `cargo fmt/clippy/test/deny` | `ruff check`, `ruff format --check`, `pytest` | Python toolchain. No dependency-audit step yet; add `pip-audit` when there is a reason to. |
| three documents | three documents, same names | Deliberate convention-matching, not an accident of copying: an operator opening `docs/GIT_WORKFLOW.md` in any repo on the box should find the same thing. The minimum-files goal is about source, not documentation; an earlier draft folded these into one file on a misreading of it. |
| lane workflow, `tick mr`, gate tool | not required by this doc | Those are dev-box conventions, documented in the box's own rules; a contributor without the box follows `docs/BRANCHING.md`, this file and `CONTRIBUTING.md` and is compliant. |

Added, not in nexora: the no-JavaScript rule (in `CONTRIBUTING.md`, where a
contributor meets it first) and the "say how you know it is unused" commit
rule. Both exist because the audit that produced this
document found the app broken without JavaScript in nine journeys, 22 files
nothing loaded, and nine more modules with one consumer or none.
