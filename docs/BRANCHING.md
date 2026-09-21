# BRANCHING.md — Branch Policy

> Companion to [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) (commits, gates, review)
> and [`CONTRIBUTING.md`](../CONTRIBUTING.md) (start here). Same layout as
> nexora's, on purpose; the differences are listed in `GIT_WORKFLOW.md` §4.

## Permanent branches

Exactly two:

- **`main`** — the deployment surface: what `docker compose up --build`
  serves. Advances only by promoting `develop` (below). Every commit on it
  is deployable and the promotions are tagged.
- **`develop`** — integration. Every topic branch lands here first.

Nobody pushes to either directly, force-pushes them, or rewrites them.

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
  `fix/`, `chore/`, `docs/`, `test/`, `refactor/`. The name should let a
  reader guess the content. One branch, one logical change; if it grows a
  second purpose, split it.
- Short-lived: days, not weeks. Push the branch the day it is created.
- Rebase, do not merge `develop` into a topic branch: `git fetch origin &&
  git rebase origin/develop`. Force-push your own unshared branch with
  `--force-with-lease` only, and never after review has started without
  saying so.
- Merged into `develop` by pull request, `--no-ff`, never squashed: the
  commit bodies carry the verification and squashing throws them away.
- Deleted at merge, local and remote. Before deleting any branch, prove it
  landed: `git merge-base --is-ancestor <branch> origin/develop` must succeed
  for the branch's current tip. `git branch --merged` is not proof. If the
  answer is unclear, leave the branch and say so.

## Promotion to `main`

When `develop` is at a state worth deploying, open a pull request
`develop -> main`, review the range, and merge it with a merge commit:

```sh
git switch main && git pull --ff-only
git merge --no-ff develop
git tag -a vX.Y.Z -m "Release X.Y.Z"      # semantic versioning; bump pyproject in the same change
git push origin main vX.Y.Z
```

No squash at promotion either: `main`'s history is `develop`'s history plus
one merge commit per release, so a bisect on `main` lands on the same atomic
commits. The container is rebuilt from the tag.

## Hotfixes

A fix that cannot wait for the next promotion branches from `main` as
`fix/<slug>`, carries the minimal change plus a regression test, merges into
`main` by reviewed pull request, is tagged as a patch release, and is then
merged back into `develop` (`git merge --no-ff main` on `develop`) so the
next promotion does not silently regress it. Everything else is a normal
topic branch off `develop`.

## Stale branch cleanup

Before deleting any branch, verify `git merge-base --is-ancestor <branch>
origin/develop` (or `origin/main` for a hotfix) succeeds for its current tip;
a name, a closed PR or a prior audit is not verification. A branch whose
content was superseded rather than merged (it will never be an ancestor) is
deleted only with a ticket recording why; `low-js-version` is the precedent.
