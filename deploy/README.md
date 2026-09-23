# Deploying wisenotes

One container, one script, one data directory. `deploy/deploy.sh` runs on the
host that serves and does everything: build the image from a git ref, swap the
container, prove the new one answers, roll back if it does not.

> **Read this before running it on a fresh host: `deploy.sh` deploys
> `origin/main` unless told otherwise, and both `main` and `develop` before
> PR #1 lands serve HTTP 500 on every HTML page.** The smoke check will refuse that release (GET / is not
> 200) and, on a first deploy with nothing to roll back to, nothing serves.
> That is the script working, not the app being broken. Wait for #1 and #2.

## Where it runs

Operator decision, 2026-09-23: the deployment is the **preview on devbox**,
tracking `develop` and redeploying itself when the branch moves. The
agrarius production host was dropped; the script was rehearsed there
(record on ticket 20260923-005) and nothing was left behind, so it can be
picked up again unchanged if that changes.

| | devbox preview |
|---|---|
| runtime | rootless podman 4.3 |
| checkout | a clone the script fetches into; nobody edits it by hand |
| branch | `develop` (`WISENOTES_BRANCH`) |
| data | `$WISENOTES_DATA`, a directory outside every checkout and lane; **location pending a permission decision**, see ticket 20260923-016 |
| bind / URL | `127.0.0.1:20015` (port from `port_alloc`), published on the tailnet by `tailscale serve --http=8094` as `http://devbox.tail499b22.ts.net:8094/` |
| boot | devbox is a container that does not survive a host reboot; restart the preview loop after one |

No compose file: devbox has no compose provider; plain `podman run`.

## The preview loop

`deploy/preview.sh --loop` polls `origin/develop` every two minutes and calls
`deploy.sh --ref origin/develop` when the tip moves. A tip that fails the
smoke check is rolled back, remembered, and not retried until the branch
moves again; the previous tip keeps serving meanwhile. Today `develop` is
a524392, the release that 500s on every page, so the loop keeps serving the
last good image and says so on each pass until PR #1 lands.

## First deploy on a host (or by hand, any ref)

```sh
git clone <repo> wisenotes-src && cd wisenotes-src
cp deploy/env.example deploy/.env && $EDITOR deploy/.env   # port, bind, data dir, branch
deploy/deploy.sh --ref origin/develop
deploy/deploy.sh status
```

`deploy/.env` stays on the host and is gitignored. The app needs no secrets;
if it ever does, they go in that file and `env.example` documents the names.

## Every later deploy

```sh
deploy/preview.sh                               # one pass: redeploy if develop moved
deploy/deploy.sh --ref v1.2.0                   # or by hand: a tag / branch / sha
```

## The data path, and the test that it survives

`$WISENOTES_DATA` on the host is bind-mounted at `/app/data` (`:Z` for
SELinux). The image contains no data and the checkout contains no data, so a
redeploy, a rebuild, an image change or `podman rm` of the container cannot
touch it. That claim is tested, not assumed: the rehearsal writes a note,
redeploys, and reads the note back through the new container (see the
rehearsal record on ticket 20260923-005). Back up by copying the directory;
it is plain JSON and media files.

## What happens on a bad deploy

The script keeps two image tags: `<name>:current` and `<name>:previous`.

1. New image built from `git archive <sha>` in a temp dir (the checkout is
   never moved, so the script survives deploying a ref older than itself)
   and tagged `current`; old `current` becomes `previous`.
2. Old container removed, new one started. This is the only moment nothing
   serves: a few seconds, single container, no overlap.
3. Smoke: `/health` **and** `GET /` must both answer 200 within 60 s.
4. Failure: new container removed, `previous` retagged to `current` and
   started, smoke run again. The old version serves; the script exits 1 and
   says `ROLLED BACK`. If there is no previous image (first deploy), it says
   `NOTHING IS SERVING` and exits 1.

`deploy/deploy.sh --rollback` does step 4 by hand at any time, for a release
that passed smoke and turned out wrong later. Rolling back never touches the
data directory; a release that changed the data format is a migration
problem, not a rollback problem, and there is none today.

## Rehearse before you promote

Anything can be rehearsed under another name, port and data dir on the same
host without touching production:

```sh
WISENOTES_NAME=wisenotes-rehearsal WISENOTES_PORT=8001 WISENOTES_DATA=$HOME/wisenotes-rehearsal \
  deploy/deploy.sh --ref origin/feat/whatever
```

Then remove it: `podman rm -f wisenotes-rehearsal; podman rmi wisenotes-rehearsal:current`.

## What this does not do

No TLS: the tailnet carries it. No multi-instance, no zero-downtime swap, no
migrations. If any of those become needed, that is a design change, not a flag.
