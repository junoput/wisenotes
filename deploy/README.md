# Deploying wisenotes

One container at rest, one script, one data directory. `deploy/deploy.sh` runs
on the host that serves and does everything: build the image from a git ref,
start it beside the serving container, prove it answers, hand over with no
gap on the tailnet URL, roll back if it does not.

> **Read this before running it: `deploy.sh` deploys `origin/develop` unless
> told otherwise (`WISENOTES_REF`, or `--ref`).** On devbox the preview loop
> follows `develop`, so every landing on `develop` is a release onto the
> operator's real notes in `/home/claude/wisenotes` (operator, 2026-10-14).
> Land on `develop` as if releasing.

## Where it runs

Operator decision, 2026-09-23: the deployment is the **preview on devbox**,
tracking `develop` and redeploying itself when the branch moves. The
agrarius production host was dropped; the script was rehearsed there
(record on ticket 20260923-005) and nothing was left behind, so it can be
picked up again unchanged if that changes.

| | devbox preview |
|---|---|
| runtime | rootless podman (5.4.2 on 2026-10-14) |
| checkout | a clone the script fetches into; nobody edits it by hand |
| branch | `develop` (`WISENOTES_BRANCH`) |
| data | `/home/claude/wisenotes` (operator's decision, 2026-09-23): outside every checkout and lane, mounted at `/app/data`; only the container writes there |
| bind / URL | `127.0.0.1:$PORT`, the port `demos status` shows (20250, pinned in the port registry so it is never reassigned), published on the tailnet by `tailscale serve --bg --http=8094 localhost:<port>` as `http://devbox.tail499b22.ts.net:8094/` |
| deploy beside | `WISENOTES_SPARE_PORT` (a second port, pinned as `wisenotes-preview-next`) and `WISENOTES_SERVE_SLOT=8094` in `deploy/.env`. During a deploy the new container stands on the spare port for about a minute and the slot points at it; at rest the slot points at 20250 again. Unset, every deploy replaces in place, with the gap |
| loop | `demos` (dev-agent-tools) runs `deploy/preview.sh --loop 120` as the user unit `demo@wisenotes-preview`, enabled on boot; `journalctl --user -u demo@wisenotes-preview` shows each pass. `demos` exports the port as `$PORT`, which the scripts honour, so `WISENOTES_PORT` is left unset in `deploy/.env`. After a reboot the first pass starts the last good image (`deploy.sh --start`) even when `develop` is still refused |
| restarts and boot | `wisenotes-container.service` (user unit, written and enabled by `deploy.sh`) is the one thing that starts the container: it runs `podman start --attach wisenotes`, restarts it if it dies (`Restart=on-failure`), and starts it at boot. The container has no podman `--restart` policy (20261019-054). Because the unit starts it, the container's conmon and port forwarder live in that unit's cgroup, so restarting `demo@wisenotes-preview` no longer takes the container's networking with it (20261019-014). `deploy.sh` never enables `podman-restart.service`: that unit starts every `restart=always` container of the user, and making other projects' containers persistent is not wisenotes' call (operator, 2026-10-14). On devbox it was already enabled and is left as it is: with no restart policy, wisenotes' container is not one it starts |

No compose file: devbox has no compose provider; plain `podman create` and the unit. The
tailnet has no TLS certs, so the publish is `tailscale serve --bg --http=8094
localhost:<port>`, and `demo.sh up` (HTTPS only) hangs; take it down with
`tailscale serve --http=8094 off`.

Verifying the published URL from this box: `tailscale serve` matches on the
MagicDNS name, so a bare-IP request 404s, and `devbox` resolves to the LAN
address here (`getent hosts devbox`), not the tailnet one, so a request by
name takes a different path than the operator's phone. The honest local
check is an explicit Host header against the tailnet IP:

```sh
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: devbox.tail499b22.ts.net' http://100.123.18.125:8094/
```

The true check is the operator opening it (ticket 20260923-044 aims the fix
at demo.sh).

## The preview loop

`deploy/preview.sh --loop` polls `origin/develop` every two minutes and calls
`deploy.sh --ref origin/develop` when the tip moves. A tip that fails the
smoke check is rolled back, remembered, and not retried until the branch
moves again; the previous tip keeps serving meanwhile. A pass that finds the
container stopped (after a reboot) starts the current image first; a stopped
container is not "serving".

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
# by hand on devbox: pass the port demos assigned, or the container binds 8000 and the serve slot 502s
PORT=$(demos status | awk '/wisenotes-preview/{print $3}') deploy/deploy.sh --ref lane/some-branch
deploy/preview.sh                               # one pass: redeploy if develop moved
deploy/deploy.sh --ref v1.2.0                   # or by hand: a tag / branch / sha
```

## The data path, and the test that it survives

`$WISENOTES_DATA` on the host is bind-mounted at `/app/data` (`:Z` for
SELinux). The image contains no data and the checkout contains no data, so a
redeploy, a rebuild, an image change or `podman rm` of the container cannot
touch it. During a deploy beside, two containers mount the same directory
with `:Z`. Under SELinux, `:Z` relabels the directory for one container at a
time, and the second mount would take it from the first; `:z` (shared) is
what two containers need. This host runs no SELinux, so the label does
nothing here, and the beside deploy was rehearsed only here. On an SELinux
host, change the mount to `:z` before using a spare port. That claim is tested, not assumed: the rehearsal writes a note,
redeploys, and reads the note back through the new container (see the
rehearsal record on ticket 20260923-005). Back up by copying the directory;
it is plain JSON and media files.

## A deploy with no gap (20261022-035)

Until 2026-10-22 every deploy stopped the container before starting the new
one, so the demo was down for 15-30 s on every landing. Now a deploy starts
the new image beside the serving container and moves the tailnet slot over:

1. `<name>-next` is created from `<name>:<sha>` on `WISENOTES_SPARE_PORT` and
   started under a transient unit, `<name>-next-container.service`
   (`Restart=on-failure`, no podman restart policy), so it has one restarter
   and its port forwarder is not in the preview loop's cgroup. `<name>` keeps
   serving and stays the only writer.
2. Smoke on the spare port. Failure: `<name>-next` is removed and the script
   says `ROLLED BACK: <name> served throughout`. Nothing was retagged and the
   slot never moved.
3. Hand over: `<name>-next` becomes the writer, then the slot points at the
   spare port. `current`/`previous` are retagged here, after the smoke.
4. `<name>` is stopped and created again on `$PORT` from the same image,
   unable to write, under `<name>-container.service` as before. Smoke.
5. Hand back: `<name>` becomes the writer, the slot points at `$PORT`, and
   `<name>-next` is stopped and removed. At rest it is one container on one
   port, as before.

If step 4 fails, the new image is deployed but serves from `<name>-next`; the
script says so and exits 1, and the next preview pass (`deploy.sh --start`,
because `<name>` is not running) brings `<name>` back beside it and hands back.
`--start` also points the slot home if it was left on the spare port (a
reboot mid-deploy: the slot's config survives, the transient unit does not).
It never repoints a slot that proxies anywhere else.

The deploy goes beside only when it can keep its guarantees, and otherwise
replaces in place and says why, in the line that starts `replacing container
... in place`: the spare port or the slot is unset; no user systemd, `flock` or
`jq`; `<name>` is not running or does not answer; either image lacks the
`wisenotes.write-fence` label (so **the first deploy of this change still has
the gap**, because the serving image predates it); or the slot does not
proxy to `$PORT`. `--rollback` always replaces in place.

### Two containers, one data directory

The data directory is shared read-write, and two containers must never both
write it. `<data>/.writer` names the one that may: each container gets its
own id in `WISENOTES_WRITER_ID` (also its `wisenotes.writer` label), and
`app/write_fence.py` refuses any POST, PUT, PATCH or DELETE with a 503 and
`Retry-After: 2` unless `.writer` holds that id. Every write holds a shared
`flock` on `<data>/.writer.lock` from the check until its handler returns;
`deploy.sh` changes `.writer` under an exclusive `flock` on the same file
(`flock -x -w $WISENOTES_DRAIN_SECONDS`, default 30). So:

- a change of writer waits for the writes in flight to finish, and a write
  cannot start while the name is being changed;
- the writer changes **before** the slot is repointed. A write that reaches
  the old container in the moment between gets a 503 asking to retry; it is
  never accepted by two containers. Reads are answered throughout;
- a new container is always started while another is named the writer, so
  it cannot write during its smoke. The one write a repository does outside
  a request handler, the legacy `notes.json` migration, also runs only in
  the writer;
- writes still in flight past the drain time abort the hand-over, leaving
  the old container serving and writing.

With `WISENOTES_WRITER_ID` unset (development, the tests, a container started
by hand) there is no fence. With it set and `.writer` or `.writer.lock`
missing, writes are refused: `deploy.sh` writes both before it starts a
container. Every refused write is logged at WARN with its reason (`write
refused: another container is the named writer`, `no writer file`, or the
lock file's errno), never a name or a path. With scripts on, the page shows
the 503's sentence at the top of the screen; without scripts the browser shows
the 503 page itself.

### A hand-over cut short, and how it comes back

A deploy can stop between its steps: `demos restart` or `demos down`, or a
dev-agent-tools upgrade, stops `demo@wisenotes-preview`, whose cgroup holds
`deploy.sh`; the host can reboot. In between, the writer, the slot and the
containers can disagree. `<name>` then still answers `/health` and every
read, and refuses every write. Found in review of MR 20261022-036; each
state below has a test in `tests/test_deploy.py` that reaches it with a real
`SIGKILL` or `SIGTERM` from the stubbed tailscale.

| cut short | left behind |
|---|---|
| after the writer moved to `-next`, before the slot did | `<name>` serves the slot; `.writer` names `-next` |
| in the hand-back, after the writer moved back, before the slot did | the slot points at `-next`, which may not write |
| a reboot after the slot moved | the unit starts `<name>`, unable to write; the slot's config survived and points at a `-next` that is not running |
| a data directory restored from a backup taken mid-hand-over | `.writer` names a container that is gone, or `.writer.lock` is missing |
| a reboot after `:current` was retagged, before `<name>` was swapped | the old image serves while `:current` names the new one (see the last bullet below) |

Three things bring it back:

- **`deploy.sh --check`**, which `preview.sh` runs on every pass, whether or
  not `<name>` serves. While `<name>` serves, it compares the rest state
  (`.writer` equal to `<name>`'s `wisenotes.writer` label, `.writer.lock`
  present, the slot not on the spare port, no `<name>-next`). If any differs, it
  says `NOT AT REST`, lists the differences and settles. **Settling** means:
  `<name>` becomes the writer, the slot points back at `$PORT`, and
  `<name>-next` is removed. `<name>` is never restarted, so nothing that
  serves goes away. At rest it prints nothing. A `<name>` that does not
  serve is left to `--start`, as before.
- **The INT/TERM trap**: a deploy that is stopped settles before it exits
  (status 130). If `<name>` does not serve but `<name>-next` serves the slot,
  `<name>-next` is made the writer instead. A `SIGKILL`, or a stop that runs
  out of time, skips the trap, and then the next preview pass's `--check`
  settles. `demo@wisenotes-preview` has `TimeoutStopUSec=15s` and
  `KillMode=control-group`, so the trap runs on short timeouts: a drain of 3 s
  (not `WISENOTES_DRAIN_SECONDS`), 3 s for the `tailscale serve` command, 2 s
  per slot read, one read after a repoint and 1 s per probe. It does the same
  steps and waits less for each; what it cannot finish says `NOT SETTLED`.
  Its worst case, every step timing out, is longer than 15 s, so a stop can
  still end in `SIGKILL`. After `demos down` nothing runs `--check` until the
  preview unit starts again (`demos up`), and until then a half-finished
  hand-over refuses writes. That is the same state the table lists, and the
  first pass after `demos up` repairs it.
- **`deploy.sh status`** prints `writer: <name>`, or `writer: NOT <name>` with
  the name the file holds.

- **`preview.sh`, after `--check`**, compares the image that serves with the
  image `:current` names. If they differ, a hand-over was cut short after the
  new image passed its smoke, and the tip's "failed smoke earlier" marker would
  keep it from ever being deployed: the marker is cleared and the pass deploys
  the tip again.

A slot repoint is judged by reading the slot again, up to three times, and
never by the command's exit status. A `tailscale serve` that applied and then
timed out has applied, and treating it as not applied put the writer on one
container and the slot on the other. If the slot cannot be confirmed on the
spare port, the deploy settles back on `<name>` and says `NOT deployed`.

The slot read has three answers: a target, `nothing` (the slot exists and
proxies nowhere) and `cannot be read` (no `jq`, `tailscale` failed or timed
out, or its output is not JSON). An unreadable slot is never taken for an
empty one: `<name>-next` is kept, a deploy that ends there prints `NOT
CONFIRMED` and exits 1 instead of claiming `no gap`, and `--check` lists the
slot as a difference. The same holds for a writer: a container whose writer
label cannot be read is not given a name, and `.writer` is never written empty.

### One deploy at a time

Every mode except `status` and `--dry-run` takes a lock for the whole run. The
lock is an `flock` on the file `$XDG_RUNTIME_DIR/wisenotes-deploy-<name>.lock`
(overridden by `WISENOTES_DEPLOY_LOCK`), held on fd 9 for the life of the
script, with the owner's pid written into the file for the message. A second
`deploy.sh`, by hand or from the loop, prints `another deploy.sh for <name> is
running (pid N, lock ...)` and exits 75. `--check` exits 0 quietly while the
lock is held, because a deploy in progress is not a state to repair. The kernel
drops the lock when its process dies, however it dies, so there is no stale
lock to take over and so nothing to race: an earlier version renamed a
directory into place and took over a dead owner's by moving it aside, and two
runs both held the lock in 17 of 300 runs with two racers (review F3). The
file is never removed, which would itself be a race. A flock's descriptor is
inherited by children, and conmon outlives the script by days; the script's
`run` closes fd 9, and the fds that carry its own output, for every command it
starts, and `tests/test_deploy.py` checks that a `podman start` has none of
them open.

## What happens on a bad deploy

The script keeps two image tags: `<name>:current` and `<name>:previous`.

1. New image built from `git archive <sha>` in a temp dir (the checkout is
   never moved, so the script survives deploying a ref older than itself)
   and tagged `<name>:<sha>`. Nothing else is retagged yet.
2. Beside (above), or in place: old container removed, new one started from
   `<name>:<sha>`. In place, this is the moment nothing serves: 15-30 s
   measured on devbox, single container, no overlap.
3. Smoke: `/health` **and** `GET /` must both answer 200 within 60 s.
4. Pass: old `current` becomes `previous`, `<sha>` becomes `current`. So
   `current` only ever names an image that passed the smoke check.
5. Failure, of the start or the smoke: beside, the new container is removed
   and the old one never stopped. In place, the new container is removed and
   `current` (untouched, so the last good image) started and smoked again.
   The script exits 1 and says `ROLLED BACK`. If there is no `current` image
   (first deploy) or it fails too, it says `NOTHING IS SERVING` and exits 1.

`deploy.sh --start` (after a reboot) starts `current` and smokes it. If that
fails, it stops the container rather than leave a failing image serving.

`deploy/deploy.sh --rollback` retags `previous` to `current` and starts it,
for a release that passed smoke and turned out wrong later. Rolling back never touches the
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
A rehearsal of the deploy beside also needs `WISENOTES_SPARE_PORT` and a serve
slot of its own in `WISENOTES_SERVE_SLOT`; never the preview's 8094.

## Accepted risks

**No CSRF protection.** Forms post without tokens, and nothing checks
`Origin`. The operator accepts this (2026-10-14) because the app is reached
only over the tailnet, so a page that could forge a request must already run
on a tailnet device. **The acceptance ends if the app is exposed beyond the
tailnet**, whether by a public bind, `tailscale funnel`, a reverse proxy or a
second user: then CSRF protection is a precondition of that change, not a
follow-up.

## Known behaviour worth knowing before a landing

Changing a note's folder renames its data directory on disk when the
directory name differs from the one the title derives (seen live: a note
stored as `CT1_HS26-2`). The stack review (20261014-139) found no data loss.
It is recorded here so that a directory renaming under a release is not
mistaken for one.

## What this does not do

No TLS: the tailnet carries it. No multi-instance (two containers stand side
by side only during a deploy, and only one writes), no migrations. The local
port `$PORT` still has a gap during a deploy beside (step 4); only the tailnet
URL has none. If any of those become needed, that is a design change, not a flag.
