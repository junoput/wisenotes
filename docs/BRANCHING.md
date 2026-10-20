# BRANCHING.md — Branch Policy

> Companion to [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) (commits, gates, review)
> and [`CONTRIBUTING.md`](../CONTRIBUTING.md) (start here). Same layout as
> nexora's, on purpose; the differences are listed in `GIT_WORKFLOW.md` §4.

## Permanent branches

Exactly two:

- **`main`** — called the deployment surface. Advances only by a release
  or a hotfix (below), and every commit on it is tagged. **Nothing deploys
  from `main` today:** the only deployment, the devbox preview, follows
  `develop` (`deploy/README.md`, fd754fc), so a promotion deploys nothing.
  That gap is recorded here, not resolved; it is the operator's to decide.
- **`develop`** — integration, and in practice the deployment: every push
  to it redeploys the preview onto the live notes. Every topic branch lands
  here first.

The integration branch is declared here, as `develop`. The fleet template
below says it is declared in `.devbox-git-profile`; wisenotes has no such
file yet (a privileged path, added only by the operator's route).

Nobody force-pushes either branch or rewrites it. On `main` GitHub enforces
that; on `develop` it is discipline (`GIT_WORKFLOW.md` §3, branch
protection). Direct pushes: the wisenotes sub-orchestrator may push
`develop` after each gated landing and its own secret scan (operator,
2026-10-19, ticket 20261019-007). That rule never covers `main`, a
force-push, `release/*` branches or tags; each of those goes to the
operator, through the orchestrator.

**Why two, when an earlier draft of this file argued for `main` only:** the
operator chose fleet consistency over per-project minimalism (2026-09-21).
An operator opening any repo on the box should find the same branch model.
The one-branch argument is kept in `GIT_WORKFLOW.md` §4 as the record of what
changed and why, not as a live position.

```
main      ──●───────────●─────────────▶  deployment; promoted from develop, tagged
             ▲           ▲
develop   ──●──●──●──●──●──●──●────────▶  integration; every topic branch lands here
                ▲     ▲        ▲
feat/x    ──────┘     │        │           short-lived topic branches, merged --no-ff
fix/y     ────────────┘        │
docs/z    ─────────────────────┘
```

## Topic branches

- Cut from `origin/develop`, named `<type>/<short-kebab-slug>`: `feat/`,
  `fix/`, `chore/`, `docs/`, `test/`, `refactor/` (the fleet list below also
  allows `feature/` and `perf/`; `release/` and `hotfix/` are not topic
  branches). The name should let a reader guess the content. One branch, one logical change; if it grows a
  second purpose, split it.
- Short-lived: days, not weeks. Push the branch the day it is created.
- Rebase, do not merge `develop` into a topic branch: `git fetch origin &&
  git rebase origin/develop`. Force-push your own unshared branch with
  `--force-with-lease` only. Once a branch is named in a merge request or
  under review, do not rebase it unless the reviewer sends it back: a rebase
  that replays cleanly rewrites what was reviewed and nothing goes red
  (`GIT_WORKFLOW.md`, "Conflicts").
- Merged into `develop` by pull request, `--no-ff`, never squashed: the
  commit bodies carry the verification and squashing throws them away.
- Deleted at merge, local and remote. Before deleting any branch, prove it
  landed: `git merge-base --is-ancestor <branch> origin/develop` must succeed
  for the branch's current tip. `git branch --merged` is not proof. If the
  answer is unclear, leave the branch and say so.

## Promotion to `main`

Every step in this section and the next is operator-gated: no standing rule
covers pushing `release/*`, pushing a tag, or promoting to `main`
(operator, 2026-10-13).

When `develop` is at a state worth releasing, cut `release/<x.y>` from
`develop`. It takes only fixes, the version bump and release notes — no new
features, which keep landing on `develop` while the release stabilises. Open
a pull request `release/<x.y> -> main`, review the range, and merge it with
a tagged merge commit:

```sh
git switch main && git pull --ff-only
git merge --no-ff release/<x.y>
git tag -a vX.Y.0 -m "Release X.Y.0"      # tag the merge commit itself; bump pyproject on the release branch
git push origin main vX.Y.0
git switch develop && git merge --no-ff release/<x.y> && git push origin develop
```

No squash anywhere in this chain: `main`'s history is the release branch's
history plus one merge commit per release, so a bisect on `main` lands on the
same atomic commits. The release branch is **kept**, not deleted: it is that
version's maintenance line, and a later patch is a fix landed on it and
re-promoted.

This replaces the earlier rule here (merge `develop` straight into `main`
and tag it). Conventions v4 and v6 make the release a branch fleet-wide,
and a wisenotes rule that contradicted the rendered one would leave both
standing; the same reconciliation was made on the v4 render (de8f0ef, not
landed).

## Hotfixes

A fix that cannot wait for the next release is cut as `hotfix/<slug>` from
the **tag currently on `main`**, never from `main`'s tip: `main` may already
carry a later, unreleased merge, and branching from the tip would drag that
into the patch. It carries the minimal change plus a regression test, merges
into `main` by reviewed pull request (tagged as a patch release), merges back
into `develop`, and merges into the matching `release/<x.y>` branch if one is
still live. A non-critical bug is an ordinary `fix/<slug>` off `develop` and
ships with the next release; it is not a hotfix.

Note what "production" means here today: the preview runs `develop`, not a
tag on `main`. A bug on the live notes is fixed by an ordinary `fix/` branch
landed on `develop`, which redeploys it; the hotfix path applies once
something deploys from `main`.

## Stale branch cleanup

Before deleting any branch, verify `git merge-base --is-ancestor <branch>
origin/develop` (or `origin/main` for a hotfix) succeeds for its current tip,
and ask whether it is on origin by COMMIT, not by name (the fleet section
below);
a name, a closed PR or a prior audit is not verification. A branch whose
content was superseded rather than merged (it will never be an ancestor) is
deleted only with a ticket recording why; `low-js-version` is the precedent.

<!-- devbox-conventions docs__BRANCHING.md v6 BEGIN — generated; edit outside the markers -->
## Branch policy

Every branch name matches `<type>/<kebab-case>`, where type is one of:

    feat feature fix hotfix chore docs refactor perf test release

This is not a style preference. `lane pr` refuses a name that does not match,
at the one moment renaming is free — before the branch is pushed. `gate run
--review` reports it afterwards but does not block, because by merge time the
branch has been reviewed under that name and renaming it helps nobody.

### What each type branches FROM and merges INTO

Most types are ordinary topic branches: cut from the integration branch, merged
back into it, deleted after landing. `feat` `fix` `chore` `docs` `refactor`
`perf` `test` are all this shape. A non-critical bug is a `fix` and ships with
the next release — it is not a hotfix.

Two types are not that shape, and the difference is the whole reason this
section exists:

    release/<x.y>   cut from the integration branch.
                    Merges into `main` (--no-ff, the merge commit TAGGED
                    v<x.y.0>) and BACK into the integration branch.
                    KEPT after release — it is that version's maintenance line.

    hotfix/<name>   cut from the production TAG on `main`, never from the
                    integration branch.
                    Merges into `main` (tagged v<x.y.z+1>), into the integration
                    branch, and into the matching `release/<x.y>` if one is live.

A release branch takes only fixes, the version bump and release notes. NO new
features: the integration branch keeps taking those in parallel, which is the
point of cutting the release at all.

A hotfix is cut from the TAG rather than from `main`'s tip because `main` may
already carry a later release. Branching from the tip fixes a bug in code that
is not the code running in production, and the resulting merge drags the newer
release into the patch.

### Where the merge-back does and does not apply

The two shapes above assume `main` and the integration branch are DIFFERENT
branches. Where they are the same — `.devbox-git-profile` declares
`integration=main`, as a repo whose `main` is both the integration branch and
the deployment surface does — then:

- there is no separate merge-back step, because the branch a release or hotfix
  merges into IS the integration branch;
- a release branch is cut from `main`, since that is the integration branch;
- a hotfix is still cut from the production TAG rather than from `main`'s tip,
  and that distinction matters MORE here, not less: on such a repo every merge
  to the integration branch is a deployment, so `main`'s tip is routinely ahead
  of what was last tagged.

Read the rules above as being about the integration branch, and collapse the
duplicate step when the two names resolve to one branch. A document that
instructs a merge into a branch the repo does not have is drift, and this
section exists so the fleet-wide template does not create it.

### The integration branch is DECLARED, never guessed

`.devbox-git-profile` at the repo root carries `integration=<branch>`. Tools
read it to answer questions they otherwise answer by inference, and a wrong
inference here is expensive: it decides which branch a lane is cut from, what
"behind" means, and which remote ref is quoted as evidence that work landed.

A project without the file gets whatever the inference guesses. That has been
measured wrong in both directions on this box — a status column printing `0`
where the truth was 67, and `132` where the truth was 0 — so there is no safe
default, only the declaration.

### What the branch is compared against

`base-fresh`, `pr-size` and the landed/on-origin checks all diff against the
integration branch. Two axes decide whether a branch is safe to delete, and
they are independent:

    landed     git merge-base --is-ancestor <branch> origin/<integration>
    on-origin  is the branch's TIP COMMIT on any remote ref?

Neither alone is sufficient. A branch that is neither is the only irreversible
case; a dirty worktree and a stash are two further destruction paths that
neither axis can see.

### on-origin is a question about a COMMIT, not about a name

It is tempting to write the second axis as `git ls-remote origin <branch>`. That
spelling has been wrong in both directions, and the second one was found by the
remediation the axis itself prompts:

- **`ls-remote origin <branch>` matches by SUFFIX.** `ls-remote origin develop`
  returns `refs/heads/develop` AND `refs/heads/iosphotos/develop`, so consumed as
  `| wc -l` a suffix match is byte-identical to a real one. That errs
  REASSURING: it reports work as recoverable when nothing of that name is on the
  remote.
- **`ls-remote --exit-code origin refs/heads/<branch>` fixes the suffix match and
  introduces a false NEGATIVE.** Archive a stranded branch to
  `refs/heads/archive/<date>/<name>` — which is what you do once the axis flags
  it — and the exact form reports it not-on-origin while the same SHA sits on the
  remote under the archive name. A safety signal that flips when its subject did
  not.

Both fail for one reason: the axis is written as a question about a NAME and
means a question about a COMMIT. A name-keyed check cannot survive the work being
renamed, moved, or archived under a prefix.

The form that asks the question it means, after a fetch:

    git branch -r --contains "$(git rev-parse <branch>)"

Materialise that rather than piping it into `grep -q`: an early-closing consumer
under `set -o pipefail` reports failure for a successful match at volume, which
would call published work unpublished — the reassuring direction, and the one
this axis exists to avoid.

`lane` already asks it this way. Its on-origin state tries the exact ref first
and then falls back to the commit, reporting `yes:<ref>` so a reader sees the
work is safe AND that it is living under another name.
<!-- devbox-conventions END -->
