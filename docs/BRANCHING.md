# BRANCHING.md — Branch Policy

> Companion to [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) (commits, gates, review)
> and [`CONTRIBUTING.md`](../CONTRIBUTING.md) (start here). Same layout as
> nexora's, on purpose; the differences are listed in `GIT_WORKFLOW.md` §4.

## Branch model

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
