# Git Workflow & Commit Rules

> **Audience:** every contributor. Branch policy is in
> [`BRANCHING.md`](BRANCHING.md); the short version and the project's own
> rules are in [`CONTRIBUTING.md`](../CONTRIBUTING.md).
> **Model:** `main` (tagged releases; nothing deploys from it today) +
> `develop` (integration; the preview follows it) + short-lived topic
> branches, merged `--no-ff`; releases as kept `release/<x.y>` branches merged
> into `main` and tagged, operator-gated.

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

If there is no `python3.12` (devbox: the system `python3` is 3.13 since
2026-10-13 and there is no sudo; the supported 3.12 is uv-managed),
bootstrap one with `uv` in a throwaway venv; nothing is installed outside the
checkout:

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

- Target `develop` (only `hotfix/<slug>` and `release/<x.y>` target `main`). Small: aim
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

### Branch protection on `main`, and why it is shaped this way

`main` is protected on GitHub (set by the operator, 2026-09-21; checked from
the API, not from the command that set it): every change must arrive by
pull request, force-pushes and deletions are refused. Three settings look
loose and are deliberate. Do not "tighten" them without reading this:

- **No required status checks.** A required check that stops reporting
  turns protection into a deadlock: nexora once had protection demanding
  three checks that could no longer pass, and nothing could merge for
  days. CI here is young; make a check required once it has a track
  record, not before.
- **Zero required approvals.** The pull request is still mandatory, which
  is the point. Requiring one approval means an author cannot approve
  their own PR; with one operator and a fleet of agents that is a merge
  that can never happen.
- **Not enforced on admins.** The operator keeps an escape hatch for the
  day protection wedges the repo.

The review requirement in §3 (a reader who did not write it) is therefore
a rule people follow, not one GitHub enforces; that is intentional.

`develop` is **not** protected, and that is the operator's open decision
rather than an oversight. Until it is decided, no force-push and no rewrite
of `develop` hold by discipline. Direct pushes to `develop` are allowed to
one role only: the wisenotes sub-orchestrator, after each gated landing and
its own secret scan (operator, 2026-10-19, ticket 20261019-007). Each such
push redeploys the preview onto the live notes, and a landing counts only
after the preview's smoke check passes.

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
| `hotfix/*` from `main`, back-merged to `develop` | `hotfix/<slug>` from the tag on `main`, merged into `main`, `develop` and any live `release/<x.y>` | Fleet conventions v6 (`BRANCHING.md`). An earlier version of this row said `fix/*` from `main`'s tip; cutting from the tip can drag an unreleased merge into a patch. |
| `release/*` branches | `release/<x.y>` from `develop`, kept as the maintenance line | Fleet conventions v6. An earlier version said "none; promote `develop -> main`": no stabilisation window was needed at this size. The fleet rule won, so the two documents do not disagree. Nothing deploys from `main` yet, so no release has been cut. |
| squash-merge topic branches, merge commits for release/hotfix | `--no-ff` merge commits everywhere | Commit bodies here carry the verification; squashing loses it. |
| `cargo fmt/clippy/test/deny` | `ruff check`, `ruff format --check`, `pytest` | Python toolchain. No dependency-audit step yet; add `pip-audit` when there is a reason to. |
| three documents | three documents, same names | Deliberate convention-matching, not an accident of copying: an operator opening `docs/GIT_WORKFLOW.md` in any repo on the box should find the same thing. The minimum-files goal is about source, not documentation; an earlier draft folded these into one file on a misreading of it. |
| lane workflow, `tick mr`, gate tool | not required by this doc | Those are dev-box conventions, documented in the box's own rules; a contributor without the box follows `docs/BRANCHING.md`, this file and `CONTRIBUTING.md` and is compliant. |

Added, not in nexora: the no-JavaScript rule (in `CONTRIBUTING.md`, where a
contributor meets it first) and the "say how you know it is unused" commit
rule. Both exist because the audit that produced this
document found the app broken without JavaScript in nine journeys, 22 files
nothing loaded, and nine more modules with one consumer or none.

## 5. Where the fleet section below and wisenotes differ

The section between the markers below is rendered fleet-wide by
`conventions render` and is not edited here. Read it with these wisenotes
facts:

- **Integration branch.** It says "declared in `.devbox-git-profile`".
  wisenotes has no such file; `develop` is declared in `BRANCHING.md`.
- **`git push` after a landing.** Only the wisenotes sub-orchestrator pushes
  `develop` (§3), and each push redeploys the preview.
- **Verifying a landing.** It suggests `git ls-remote origin <integration>`.
  That form matches by suffix (the fleet `BRANCHING.md` section explains
  why); here use `git fetch origin` and then
  `git merge-base --is-ancestor <branch tip> origin/develop`.
- **Releases, hotfixes and production.** The release and hotfix shapes are
  adopted (`BRANCHING.md`), and every step of them is operator-gated. What
  runs on the live notes is `develop`, not a tag on `main`.

<!-- devbox-conventions docs__GIT_WORKFLOW.md v6 BEGIN — generated; edit outside the markers -->
## How a change lands

A change is landed by merging a topic branch into the integration branch
declared in `.devbox-git-profile`. The merge is `--no-ff`, always, so the branch
survives as a readable unit: a squash makes the landed/on-origin test below
unable to see what it merged, and a project that squashes reads every
integration as something else.

    git fetch origin
    git merge --no-ff --no-commit <branch>
    <resolve, if anything conflicts>
    git commit -F -            # the reasoning, not the file list
    git push

### Gate the MERGED RESULT, not the branch

A branch green on its own and red once merged is the ordinary case, and it is
invisible to any check run before the merge. So `gate` runs on the merge result,
with the working tree clean, and its verdict NAMES the worktree path and the
commit SHA it came from. A project here can have several copies of everything —
a lane, a shared checkout, a deployment surface — and a correct result from the
wrong tree is indistinguishable from a right one.

A receipt that says the tree was DIRTY does not vouch for a commit. Do not file
a merge request whose prose says green while the receipt embedded below it says
otherwise: `tick mr` embeds the receipt faithfully and nothing compares the two
for you.

### Fetch immediately before merging, not before reviewing

On an active branch those are minutes apart, and a stale tip merges cleanly.

## How a change is verified as landed

`tick close`'s guard compares against the LOCAL integration ref, which passes
for a merge that never reached the remote. Before closing, ask the remote:

    git ls-remote origin <integration>
    git merge-base --is-ancestor origin/<branch> origin/<integration>

The second names the BRANCH TIP, not the SHA you merged. `--is-ancestor
<merged-sha>` answers *did what I merged reach origin* and says nothing about
commits the branch carried that the merge did not take. Those two questions look
identical to whoever did the merging, which is exactly when nobody asks the
second one.

## Conflicts

Resolve from each side's COMPLETE file (`git show <ref>:<path>`), not from the
interleaved conflict view: a conflict hunk shows the disagreement and hides the
surrounding agreement, and the surrounding agreement is where a whole-file
revert hides. Before resolving, enumerate by name what each side contributes,
and find those names in the resolved file before gating. Taking either side
wholesale merges clean, builds green, passes every test — the reverted code's
tests went with it — and produces a file list indistinguishable from a correct
merge.

A rebase of published work that throws a conflict is the LUCKY outcome. One that
replays cleanly rewrites published history silently and nothing goes red.

## How a release is prepared

A release is a BRANCH, not a moment. When the integration branch holds what the
next version should ship:

    git fetch origin
    git switch -c release/<x.y> origin/<integration>
    <only fixes, the version bump, release notes — NO new features>
    git switch main && git merge --no-ff release/<x.y>
    git tag -a v<x.y.0> -m "<x.y.0>"        # the TAG is what production runs
    git switch <integration> && git merge --no-ff release/<x.y>

Three things about that sequence are decisions rather than mechanics.

**The integration branch does not freeze.** It keeps taking features while the
release stabilises, which is the reason to cut a branch instead of declaring a
code freeze. A frozen integration branch stops every other agent on the box.

**The merge-back is not optional.** Fixes made on the release branch exist only
there until it happens, so skipping it loses exactly the work that was urgent
enough to do during stabilisation — and loses it silently, because `main` is
correct and nothing downstream looks at the integration branch for it.

**The release branch is KEPT.** It is that version's maintenance line. Deleting
it after tagging is what makes the next hotfix have nowhere to go but `main`'s
tip.

Promotion to `main` is operator-gated where a project says so, and this changes
how a release is PREPARED rather than who approves it.

## How production is fixed after a release

A critical production bug does NOT go through the integration branch.

    git fetch origin --tags
    git switch -c hotfix/<name> v<x.y.z>     # the TAG in production, not main's tip
    <the smallest fix that addresses it>
    git switch main && git merge --no-ff hotfix/<name>
    git tag -a v<x.y.z+1> -m "<x.y.z+1>"
    git switch <integration> && git merge --no-ff hotfix/<name>
    git switch release/<x.y> && git merge --no-ff hotfix/<name>    # if still live

**Cut from the TAG, not from `main`.** `main` may already carry a later release
than the one deployed. Branching from its tip fixes code that is not running in
production, and merging that branch back drags the newer release into what was
meant to be a patch.

**Three merge targets, and the third is the one that gets forgotten.** Into
`main` so production has the fix; into the integration branch so the next
release does not regress it; into any live `release/<x.y>` so that maintenance
line does not either. Forgetting the second is a bug that returns at the next
release with nothing in the history explaining why.

**A non-critical bug is not a hotfix.** It is a `fix/<name>` from the
integration branch and ships with the next release. The hotfix path exists to
bypass stabilisation, and bypassing it for a bug that could wait spends the
tagging and merge-back cost for nothing.

Where `main` IS the integration branch — `.devbox-git-profile` declaring
`integration=main` — the merge-back step is the same merge as the first and
collapses. Everything else holds unchanged, including cutting from the TAG:
there, every landing is a deployment, so `main`'s tip is routinely ahead of the
last tag.

## Lanes

Two agents never share a checkout. `lane new <name>` cuts an isolated worktree,
branch and port block from the integration branch.

Lanes are worktrees of ONE repository: they share one object store and one
`refs/heads`. So "does this branch hold unlanded work" is a question about the
repository and has no per-lane answer — asking it per lane multiplies one set by
the number of worktrees. Enumerate branches once, then ask which worktree holds
each.

A linked worktree's `.git` is a regular FILE containing a `gitdir:` line, so
`test -d "$d/.git"` is false for every lane. The question you meant is
`git -C "$d" rev-parse --is-inside-work-tree`.

## Before deleting a branch or a lane

`docs/BRANCHING.md` gives the two axes — landed, and on-origin — and says a
branch is irreversible only when both are false. Three things that document does
not cover, because they are about the worktree rather than the branch:

- `unpushed=0` answers NEITHER axis. It is exactly what a branch pushed to
  origin and never merged reports.
- Both axes assume the branch was pushed at least once. A branch never pushed
  has no remote-tracking ref, so it is not reported as risky — it is not
  reported at all.
- `git status --porcelain` per worktree and `git stash list` are two further
  destruction paths neither axis can see, and nobody asks the second.

Finding stranded work is not authority to publish it. Work kept local may be
kept local deliberately; file it and let its owner decide.
<!-- devbox-conventions END -->
