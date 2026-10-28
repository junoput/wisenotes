#!/usr/bin/env bash
# Deploy wisenotes as one rootless podman container, with rollback.
#
#   deploy/deploy.sh                 build+start from $WISENOTES_REF (default origin/develop)
#   deploy/deploy.sh --ref <ref>     any git ref: a branch, tag or sha (rehearsals)
#   deploy/deploy.sh --rollback      put the previous image back and start it
#   deploy/deploy.sh --start         start the current image again (after a reboot); no build
#   deploy/deploy.sh --check         repair a container, writer or slot left mid-hand-over
#                                    (preview.sh runs it every pass); quiet when at rest
#   deploy/deploy.sh status          what is running, from which image, and who may write
#   deploy/deploy.sh --dry-run ...   print the plan, change nothing
#
# Runs ON the host that serves (devbox preview; any podman host), from a
# checkout of the repo. Reads deploy/.env if present (see deploy/env.example).
#
# What a deploy does, in order:
#   1. git fetch; resolve the ref to a sha (this checkout is NOT moved: the
#      script must survive deploying an old ref that predates it)
#   2. git archive <sha> into a temp dir; podman build -> image wisenotes:<sha>
#   3. start wisenotes:<sha> BESIDE the serving container, as <NAME>-next on
#      $WISENOTES_SPARE_PORT, unable to write (see "Two containers, one data
#      dir" below); or, when that is not possible, replace the container in
#      place (stop+rm the old one, run the new), which leaves a gap
#   4. smoke: /health must answer 200 AND GET / must answer 200 within 60s
#      (GET / is the check that would have caught the "every page 500s"
#      release; /health alone was green through it)
#   5. only after the smoke passes, retag: current -> previous, <sha> -> current.
#      So `current` only ever names an image that passed the smoke check.
#   6. if the run or the smoke fails: beside, remove the new container (the
#      old one served throughout); in place, remove it and start `current`
#      again (untouched, so still the last good image). Exit 1 either way. If
#      there is no current image, nothing serves and the exit says so.
#
# Beside, with no gap (20261022-035): after the smoke, hand over to <NAME>-next
# (it becomes the writer, then the tailnet slot $WISENOTES_SERVE_SLOT points at
# it), stop the old container, start <NAME> again on $PORT from the same image,
# smoke it, and hand back. At rest there is one container, <NAME> on $PORT,
# exactly as before; only the tailnet slot never stops answering. A deploy
# goes beside only when the serving container answers, both images carry the
# wisenotes.write-fence label, and the slot proxies to $PORT; otherwise it
# says why and replaces in place.
#
# Two containers, one data dir: <data>/.writer names the one container that
# may write, and is changed only under an exclusive flock on <data>/.writer.lock
# that waits for writes in flight (app/write_fence.py). The writer changes
# BEFORE the slot is repointed, so a write never reaches a container while
# another may write; one arriving at the old container in that moment gets a
# 503 asking to retry. Reads are served throughout.
#
# Interrupted, or rebooted, mid-hand-over (20261022-036 review): the writer, the
# slot and the containers can disagree, and the notes then refuse every write
# while still answering reads. Three things bring them back: an INT/TERM trap
# that settles before exiting; `--check`, which preview.sh runs every pass and
# which settles whenever $NAME serves but the writer file, the slot or a
# leftover <NAME>-next say otherwise; and --start. Settling makes $NAME the
# writer and the slot's target and removes <NAME>-next, without restarting $NAME.
#
# One deploy at a time: every mode but status takes a lock for the whole run
# (an flock on $XDG_RUNTIME_DIR/wisenotes-deploy-<NAME>.lock, held on fd 9 until
# the process ends, so a dead owner's lock is simply free; the file holds the
# owner's pid for the message). A second run says who holds it and exits 75;
# --check skips quietly while a deploy holds it, because a deploy in progress is
# not a state to repair.
#
# Boot: a wisenotes-only user unit, <NAME>-container.service, runs
# `podman start <NAME>` at boot. It never enables podman-restart.service,
# which would bring back every other restart=always container on the host.
#
# Data: the host directory $WISENOTES_DATA (default ~/wisenotes) is bind-mounted
# at /app/data. It is never inside the checkout and never inside the image, so
# it survives a redeploy, a rebuild and an image change. The container runs
# as the image's non-root user; rootless podman maps that to your uid.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/.." && pwd)
[ -f "$here/.env" ] && { set -a; . "$here/.env"; set +a; }

NAME=${WISENOTES_NAME:-wisenotes}            # container name; image tags are <NAME>:current/previous/<sha>
REF=${WISENOTES_REF:-origin/develop}
PORT=${WISENOTES_PORT:-${PORT:-8000}}          # $PORT is what a supervisor like `demos` hands out
BIND=${WISENOTES_BIND:-127.0.0.1}            # 100.x.y.z to serve on the tailnet only
DATA=${WISENOTES_DATA:-$HOME/wisenotes}
SMOKE_SECONDS=${WISENOTES_SMOKE_SECONDS:-60}
SPARE_PORT=${WISENOTES_SPARE_PORT:-}         # second pinned port: the new container is smoked there, beside the old
SERVE_SLOT=${WISENOTES_SERVE_SLOT:-}         # the tailscale serve port that proxies to $PORT (8094 on devbox)
DRAIN_SECONDS=${WISENOTES_DRAIN_SECONDS:-30} # how long a change of writer waits for writes in flight
TS_SECONDS=20; READ_SECONDS=10; PROBE_SECONDS=5; ROUTE_READS=3  # on_signal shortens all of these
DRY=0; MODE=deploy

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF=$2; shift 2 ;;
    --rollback) MODE=rollback; shift ;;
    --start) MODE=start; shift ;;
    --check) MODE=check; shift ;;
    status) MODE=status; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,74p' "$0"; exit 0 ;;
    *) echo "deploy: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "deploy: $*"; }
# The deploy lock is on fd 9, and fds 3 and 4 hold the script's own stdout and stderr
# for the signal trap. A command that can start a daemon (podman start leaves conmon
# behind for days) must inherit none of them: a daemon holding fd 9 holds the lock,
# and one holding fd 3 keeps the caller's pipe open after this script has exited.
run() { if [ "$DRY" = 1 ]; then printf '  + %s\n' "$*"; else "$@" 9>&- 3>&- 4>&-; fi; }
have_image() { podman image exists "$1"; }
have_container() { podman container exists "$1"; }
image_of_running() { podman inspect -f '{{.ImageName}}' "$NAME" 2>/dev/null || true; }

probe() { # $1 path, $2 port (default $PORT) -> prints http status or 000
  curl -s -o /dev/null -w '%{http_code}' --max-time "$PROBE_SECONDS" "http://$BIND:${2:-$PORT}$1" || true  # prints 000 on no answer
}

smoke() { # $1 port (default $PORT); wait until both probes answer 200; return 1 on timeout
  local deadline=$((SECONDS + SMOKE_SECONDS)) h p
  while [ $SECONDS -lt $deadline ]; do
    h=$(probe /health "${1:-}"); p=$(probe / "${1:-}")
    if [ "$h" = 200 ] && [ "$p" = 200 ]; then say "smoke ok: /health $h, GET / $p"; return 0; fi
    sleep 2
  done
  say "smoke FAILED after ${SMOKE_SECONDS}s: /health ${h:-?}, GET / ${p:-?} (need 200 and 200)"
  return 1
}

port_move_warning() { # say so when the container about to be replaced published another host port
  local old
  # from the container's config, not `podman port`, which says nothing once it stopped
  old=$(podman inspect -f '{{range (index .HostConfig.PortBindings "8000/tcp")}}{{.HostPort}}{{end}}' "$NAME" 2>/dev/null || true)
  if [ -n "$old" ] && [ "$old" != "$PORT" ]; then
    say "PORT MOVES: $NAME served on $old and will serve on $PORT. Anything proxying to $old (a tailscale serve slot) must be repointed. The port comes from WISENOTES_PORT, else \$PORT from the supervisor."
  fi
}

DEPLOY_LOCK=${WISENOTES_DEPLOY_LOCK:-${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/wisenotes-deploy-$NAME.lock}
CLEANUP=()

on_exit() {
  local f
  for f in "${CLEANUP[@]}"; do rm -rf "$f"; done
}
trap on_exit EXIT

LOCK_HOLDER=
take_deploy_lock() { # 0 taken; 1 another live run holds it (its pid in LOCK_HOLDER)
  # An flock on a lock FILE, held on fd 9 for the life of this process. The
  # kernel drops it when the process dies, however it dies, so there is no stale
  # lock to take over and no takeover to race (a directory renamed into place
  # let two runs both win, 17 of 300 times with two racers, 20261022-036 F3).
  # The one cost of a flock is that a child inherits the descriptor: run() closes
  # it for every command that could outlive this script. The file is never
  # removed: removing a lock file is itself a race.
  if ! command -v flock >/dev/null; then
    say "no flock on this host: running without the one-deploy-at-a-time lock"
    return 0
  fi
  mkdir -p "$(dirname "$DEPLOY_LOCK")"
  exec 9>>"$DEPLOY_LOCK"
  if ! flock -n 9; then
    LOCK_HOLDER=$(head -n 1 "$DEPLOY_LOCK" 2>/dev/null || true)
    LOCK_HOLDER=${LOCK_HOLDER:-unknown}
    exec 9>&-
    return 1
  fi
  : >"$DEPLOY_LOCK"; printf '%s\n' "$$" >&9  # for the message of the next run; the lock is the flock
  return 0
}

UNIT_NAME="$NAME-container.service"
NEXT="$NAME-next"                       # the new container while it stands beside the old one
NEXT_UNIT="$NEXT-container.service"     # transient: it supervises $NEXT for the minute it lives
FENCE="$DATA/.writer"
FENCE_LOCK="$DATA/.writer.lock"

have_systemd() {
  # is-system-running exits non-zero for "degraded" (a failed unit somewhere), which is
  # still a running user manager; only offline/unknown/missing mean no systemd
  local state
  state=$(systemctl --user is-system-running 2>/dev/null || true)
  [ "$state" = running ] || [ "$state" = degraded ] || [ "$state" = starting ]
}

container_unit() { # the unit text: run this one container, restart it if it dies, nothing else
  # --attach keeps `podman start` in the foreground, so the unit sees the
  # container exit, and conmon and the port forwarder start in this unit's
  # cgroup rather than in the caller's. A crash exits non-zero and is
  # restarted; `systemctl stop` (ExecStop) is a clean stop and is not.
  # The attached output is dropped: conmon already sends the container's
  # output to the journal, and keeping both doubles every log line.
  local podman
  podman=$(command -v podman)
  cat <<UNIT
# Written by wisenotes deploy/deploy.sh. Runs only the $NAME container.
[Unit]
Description=wisenotes container $NAME
Wants=network-online.target
After=network-online.target

[Service]
ExecStart=$podman start --attach $NAME
ExecStop=$podman stop -t 10 $NAME
Restart=on-failure
RestartSec=2
StandardOutput=null
StandardError=null

[Install]
WantedBy=default.target
UNIT
}

ensure_unit() {
  # Rootless containers do not come back after a reboot by themselves. The
  # box-wide answer, podman-restart.service, starts EVERY restart=always
  # container of this user, so it is not ours to enable (operator, 2026-10-14).
  local dir
  dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  if [ "$(cat "$dir/$UNIT_NAME" 2>/dev/null)" != "$(container_unit)" ]; then
    say "writing $dir/$UNIT_NAME: it runs $NAME, restarts it if it dies, and starts it at boot"
    run mkdir -p "$dir"
    if [ "$DRY" = 1 ]; then printf '  + write %s\n' "$dir/$UNIT_NAME"; else container_unit >"$dir/$UNIT_NAME"; fi
    run systemctl --user daemon-reload || true
  fi
  if ! systemctl --user is-enabled "$UNIT_NAME" >/dev/null 2>&1; then
    run systemctl --user enable "$UNIT_NAME" || say "could not enable $UNIT_NAME; run: systemctl --user enable $UNIT_NAME"
  fi
}

new_writer_id() { printf '%s.%s.%s%s' "$1" "$(date +%s)" "$$" "$RANDOM"; }
writer_of() { podman inspect -f '{{index .Config.Labels "wisenotes.writer"}}' "$1" 2>/dev/null || true; }
is_running() { [ "$(podman inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
fence_image() { [ "$(podman image inspect -f '{{index .Labels "wisenotes.write-fence"}}' "$1" 2>/dev/null)" = 1 ]; }
fence_container() { [ "$(podman inspect -f '{{index .Config.Labels "wisenotes.write-fence"}}' "$1" 2>/dev/null)" = 1 ]; }

set_writer() { # $1 writer id: wait for writes in flight, then name the one container that may write
  # The lock file is created by flock if missing; the container only reads it.
  # With no flock on the host, only an in-place replace runs (beside_blocker),
  # and there nothing else is running to write: the name is written unlocked.
  # An empty id would name nobody, and every container would refuse every write.
  [ -n "${1:-}" ] || { say "refusing to name an empty writer; the writer is left as it is"; return 1; }
  local write='printf "%s\n" "$1" >"$2.tmp" && mv -f "$2.tmp" "$2"'
  if command -v flock >/dev/null; then
    run flock -x -w "$DRAIN_SECONDS" "$FENCE_LOCK" sh -c "$write" set_writer "$1" "$FENCE"
  else
    run touch "$FENCE_LOCK" && run sh -c "$write" set_writer "$1" "$FENCE"
  fi
}

slot_target() { # what the slot's "/" proxies to; "-" when it proxies nothing; "?" when it cannot be read
  # Three answers, not two: an unreadable slot is not an empty one (20261022-036 F1).
  local json out
  command -v jq >/dev/null || { echo '?'; return 0; }
  json=$(timeout "$READ_SECONDS" tailscale serve status --json 2>/dev/null) || { echo '?'; return 0; }
  out=$(printf '%s' "$json" | jq -r --arg p ":$SERVE_SLOT" \
    '[(.Web // {}) | to_entries[] | select(.key | endswith($p)) | .value.Handlers["/"].Proxy // empty] | (.[0] // "-")' 2>/dev/null) \
    || { echo '?'; return 0; }
  [ -n "$out" ] && echo "$out" || echo '?'
}

slot_says() { # the slot's target for a message
  local t
  t=$(slot_target)
  case "$t" in '?') echo "cannot be read" ;; -) echo "nothing" ;; *) echo "$t" ;; esac
}

target_is() { # $1 a slot_target answer, $2 port
  case "$1" in
    "http://localhost:$2"|"http://127.0.0.1:$2"|"http://$BIND:$2") return 0 ;;
  esac
  return 1
}

slot_points_at() { target_is "$(slot_target)" "$1"; }  # $1 port

slot_unreadable() { [ "$(slot_target)" = '?' ]; }

route() { # $1 port: point the tailnet slot at it; 0 only when the slot is SEEN pointing there.
  # The slot's URL does not change. A failed or timed-out command may still have
  # applied, and one failed read is not a verdict, so the slot is read again
  # either way; a caller that gets 1 must look at slot_target, not assume.
  local i
  run timeout "$TS_SECONDS" tailscale serve --bg --http="$SERVE_SLOT" "http://$BIND:$1" >/dev/null || true
  [ "$DRY" = 1 ] && return 0
  for ((i = 1; i <= ROUTE_READS; i++)); do
    slot_points_at "$1" && return 0
    [ "$i" = "$ROUTE_READS" ] || sleep 1
  done
  return 1
}

create_container() { # $1 container, $2 image, $3 host port, $4 writer id
  # keep-id: the process runs as the host user, so it can write the bind-mounted
  # data dir; without it rootless podman maps the image user to a subuid and
  # every write to /app/data is EACCES (found in rehearsal).
  # No --restart: a unit is the one restarter. A podman policy as well would
  # put a second, box-wide restarter (podman-restart.service) back in play.
  run podman create --name "$1" \
    --userns=keep-id --user "$(id -u):$(id -g)" \
    -p "$BIND:$3:8000" \
    -v "$DATA:/app/data:Z" \
    -e WISENOTES_DATA_DIR=/app/data \
    -e WISENOTES_WRITER_ID="$4" --label "wisenotes.writer=$4" \
    "$2" >/dev/null
}

start_container() { # $1 image; $2 "fenced": start it unable to write (another container serves)
  local id
  id=$(new_writer_id "$NAME")
  create_container "$NAME" "$1" "$PORT" "$id" || return 1
  if [ "${2:-}" != fenced ]; then set_writer "$id" || return 1; fi
  if have_systemd; then
    ensure_unit
    run systemctl --user restart "$UNIT_NAME"
  else
    say "no user systemd here: nothing restarts $NAME if it dies, and it will not return after a reboot"
    run podman start "$NAME" >/dev/null
  fi
}

stop_container() {
  # Stop the unit first: removing the container under a running unit counts as
  # a crash, and the unit would try to start a container that is gone.
  # Always, not only when is-active says so: is-active is false while the unit
  # is activating or deactivating (its RestartSec=2 wait), and a start is then
  # still pending. Nor gated on have_systemd: during a manager state such as
  # "stopping" it says no while the unit still runs. Stopping an inactive or
  # unknown unit, or with no systemctl at all, fails harmlessly.
  run systemctl --user stop "$UNIT_NAME" 2>/dev/null || true
  if have_container "$NAME"; then run podman rm -f "$NAME" >/dev/null; fi
}

start_next() { # under a transient unit, so its conmon and port forwarder are not in the caller's cgroup
  run systemd-run --user --quiet --collect --unit="$NEXT_UNIT" \
    -p Restart=on-failure -p RestartSec=2 -p StandardOutput=null -p StandardError=null \
    "$(command -v podman)" start --attach "$NEXT"
}

stop_next() { # same order as stop_container: the unit first
  run systemctl --user stop "$NEXT_UNIT" 2>/dev/null || true
  if have_container "$NEXT"; then run podman rm -f "$NEXT" >/dev/null; fi
}

route_home() { # after $NAME serves on $PORT as the writer: a slot left on $NEXT comes back, $NEXT goes
  if [ -n "$SERVE_SLOT" ] && [ -n "$SPARE_PORT" ] && slot_points_at "$SPARE_PORT"; then
    say "tailnet slot $SERVE_SLOT points at $NEXT on $SPARE_PORT; pointing it back at $PORT"
    route "$PORT" || say "could not point tailnet slot $SERVE_SLOT at $PORT; it still points at $SPARE_PORT"
  fi
  if slot_may_need_next; then
    if have_container "$NEXT"; then
      say "tailnet slot $SERVE_SLOT may still point at $NEXT (it reads: $(slot_says)); keeping $NEXT"
    else
      say "tailnet slot $SERVE_SLOT cannot be read (it reads: $(slot_says)); there is no $NEXT to keep"
    fi
  elif have_container "$NEXT"; then
    stop_next
  fi
}

slot_may_need_next() { # the slot is on the spare port or cannot be read: $NEXT must not be removed
  [ -n "$SERVE_SLOT" ] && [ -n "$SPARE_PORT" ] || return 1
  local t
  t=$(slot_target)
  [ "$t" = '?' ] || target_is "$t" "$SPARE_PORT"
}

rest_problems() { # what differs from the rest state while $NAME serves; nothing when at rest
  local want got t
  if fence_container "$NAME"; then
    want=$(writer_of "$NAME"); got=$(head -n 1 "$FENCE" 2>/dev/null || true)
    if [ -z "$want" ]; then
      echo "$NAME's writer label cannot be read, so the writer file cannot be checked"
    else
      [ "$got" = "$want" ] || echo "the writer file names ${got:-nobody}, not $NAME, so $NAME refuses every write"
    fi
    [ -e "$FENCE_LOCK" ] || echo "the writer lock file is missing, so $NAME refuses every write"
  fi
  if [ -n "$SERVE_SLOT" ] && [ -n "$SPARE_PORT" ]; then
    t=$(slot_target)
    if [ "$t" = '?' ]; then
      echo "tailnet slot $SERVE_SLOT cannot be read, so it cannot be confirmed to point at $NAME on $PORT"
    elif target_is "$t" "$SPARE_PORT"; then
      echo "tailnet slot $SERVE_SLOT points at the spare port $SPARE_PORT, not at $NAME on $PORT"
    fi
  fi
  if have_container "$NEXT"; then echo "$NEXT is left over from a deploy"; fi
}

serves() { is_running "$1" && [ "$(probe /health "${2:-}")" = 200 ]; }

settle() { # $NAME serves: make it the writer and the slot's target, then remove $NEXT. 0 at rest.
  # $NAME is not restarted, so nothing serving goes away. Every step is safe to
  # repeat, and a failed step leaves the writer where the slot points. $NEXT is
  # removed only when the slot is SEEN off the spare port: unreadable is not off.
  local id t=""
  if [ -n "$SERVE_SLOT" ] && [ -n "$SPARE_PORT" ]; then
    # Read the slot before the writer moves: with the slot unreadable it may point
    # at $NEXT, and the writer stays where the last confirmed route left it.
    t=$(slot_target)
    if [ "$t" = '?' ]; then
      say "tailnet slot $SERVE_SLOT cannot be read; the writer is left as it is and any $NEXT is kept; not settled; the next --check looks again"
      return 1
    fi
  fi
  if fence_container "$NAME"; then
    id=$(writer_of "$NAME")
    if [ -z "$id" ]; then
      say "cannot read $NAME's writer label; the writer is left as it is; not settled"
      return 1
    fi
    set_writer "$id" || { say "writes in flight did not finish within ${DRAIN_SECONDS}s; not settled"; return 1; }
  fi
  if [ -n "$SERVE_SLOT" ] && [ -n "$SPARE_PORT" ]; then
    if target_is "$t" "$SPARE_PORT"; then
      say "tailnet slot $SERVE_SLOT points at $SPARE_PORT; pointing it at $NAME on $PORT"
      if ! route "$PORT"; then
        t=$(slot_target)
        if target_is "$t" "$SPARE_PORT" && serves "$NEXT" "$SPARE_PORT"; then
          id=$(writer_of "$NEXT")
          set_writer "$id" || say "AND could not make $NEXT the writer again: NOTHING CAN WRITE until deploy.sh --check"
          say "could not point tailnet slot $SERVE_SLOT at $PORT; $NEXT keeps serving it and is the writer again"
          return 1
        fi
        say "could not confirm tailnet slot $SERVE_SLOT points at $PORT (it reads: $(slot_says)); the next --check looks again"
      fi
    fi
    if slot_may_need_next; then
      say "tailnet slot $SERVE_SLOT cannot be read or is on $SPARE_PORT; keeping $NEXT; the next --check looks again"
      return 1
    fi
  fi
  stop_next
  [ -z "$(rest_problems)" ]
}

on_signal() { # INT/TERM mid-run: leave a state that writes, then exit
  # The trap runs inside whatever redirection the interrupted command had
  # (route's >/dev/null): write to the script's own output, saved as fd 3.
  trap - INT TERM
  exec 1>&3 2>&4
  # systemd gives a stopped unit TimeoutStopUSec (15 s on demo@wisenotes-preview)
  # before SIGKILL, so the repair runs on short timeouts: it does the same steps,
  # waits less for each, and whatever it cannot finish the next --check does.
  DRAIN_SECONDS=3; TS_SECONDS=3; READ_SECONDS=2; PROBE_SECONDS=1; ROUTE_READS=1
  say "interrupted; returning to a state where the notes can be written"
  if serves "$NAME"; then
    settle || say "NOT SETTLED: run deploy.sh --check"
  elif [ -n "$SPARE_PORT" ] && serves "$NEXT" "$SPARE_PORT" && [ -n "$SERVE_SLOT" ] && slot_points_at "$SPARE_PORT"; then
    set_writer "$(writer_of "$NEXT")" || say "could not name $NEXT the writer; deploy.sh --check looks again"
    say "$NEXT serves tailnet slot $SERVE_SLOT and is the writer; deploy.sh --start moves it back to $PORT"
  else
    say "$NAME does not serve; the next preview pass (or deploy.sh --start) starts it"
  fi
  exit 130
}

beside_blocker() { # $1 new image; prints why it cannot start beside the serving container, nothing if it can
  [ -n "$SPARE_PORT" ] || { echo "WISENOTES_SPARE_PORT is unset"; return; }
  [ -n "$SERVE_SLOT" ] || { echo "WISENOTES_SERVE_SLOT is unset"; return; }
  [ "$SPARE_PORT" != "$PORT" ] || { echo "WISENOTES_SPARE_PORT is the serving port $PORT"; return; }
  have_systemd || { echo "no user systemd to supervise a second container"; return; }
  command -v flock >/dev/null || { echo "no flock to change the writer"; return; }
  command -v jq >/dev/null || { echo "no jq to read the tailnet slot"; return; }
  is_running "$NAME" || { echo "$NAME is not running, so there is no service to keep up"; return; }
  [ "$(probe /health)" = 200 ] || { echo "$NAME does not answer on $PORT, so there is no service to keep up"; return; }
  fence_container "$NAME" || { echo "the serving image predates the write fence"; return; }
  fence_image "$1" || { echo "the new image has no write fence"; return; }
  slot_points_at "$PORT" || {
    if slot_unreadable; then echo "tailnet slot $SERVE_SLOT cannot be read"; else echo "tailnet slot $SERVE_SLOT proxies to $(slot_says), not to $PORT"; fi
    return
  }
}

hand_back() { # $NEXT serves and writes; make $NAME (running fenced on $PORT) the writer and the slot's target
  # Returns 0 when done. 1 when $NEXT keeps the slot and is the writer (NAME did not
  # take over). 2 when it cannot be told: $NAME is the writer, but the slot could not
  # be confirmed at $PORT (it reads nothing, something else, or cannot be read).
  # Success is never reported for a 2 (20261022-036 F1).
  local next_id name_id t
  next_id=$(writer_of "$NEXT"); name_id=$(writer_of "$NAME")
  if [ -z "$next_id" ] || [ -z "$name_id" ]; then
    say "cannot read the writer label of $NAME or $NEXT; nothing changed and $NEXT keeps serving"
    return 1
  fi
  set_writer "$name_id" || { say "writes on $NEXT did not finish within ${DRAIN_SECONDS}s"; return 1; }
  if ! route "$PORT"; then
    t=$(slot_target)
    if target_is "$t" "$SPARE_PORT"; then
      say "could not point tailnet slot $SERVE_SLOT back at $PORT; $NEXT stays the writer"
      set_writer "$next_id" || say "AND could not make $NEXT the writer again: NOTHING CAN WRITE until deploy.sh --check"
      return 1
    fi
    if [ "$t" = '?' ]; then
      # $NEXT may still be the slot's target: it stays, and so does the writer it
      # had (the last confirmed route); --check moves both once the slot reads.
      say "could not read tailnet slot $SERVE_SLOT after pointing it at $PORT; $NEXT is kept and stays the writer; run deploy.sh --check"
      set_writer "$next_id" || say "AND could not make $NEXT the writer again: NOTHING CAN WRITE until deploy.sh --check"
      return 2
    fi
    say "could not confirm tailnet slot $SERVE_SLOT points at $PORT (it reads: $(slot_says)); $NAME is the writer"
    stop_next
    return 2
  fi
  stop_next
}

deploy_beside() { # $1 sha; 0 deployed, 1 not deployed
  local img="$NAME:$1" id rc
  say "starting $1 as $NEXT on $SPARE_PORT beside $NAME, which keeps serving; $NEXT cannot write until it serves"
  stop_next
  id=$(new_writer_id "$NEXT")
  if ! { create_container "$NEXT" "$img" "$SPARE_PORT" "$id" && start_next && smoke "$SPARE_PORT"; }; then
    say "$1 failed to start or failed smoke on $SPARE_PORT; last log lines:"
    podman logs --tail 20 "$NEXT" 2>&1 | sed 's/^/    /' || true
    stop_next
    say "ROLLED BACK: $NAME served throughout and is still the writer; $1 was NOT deployed"
    return 1
  fi
  if ! set_writer "$id"; then
    stop_next
    say "writes on $NAME did not finish within ${DRAIN_SECONDS}s; it is still the writer and serving; $1 was NOT deployed"
    return 1
  fi
  if ! route "$SPARE_PORT"; then
    # The slot may have moved after all; settle on what it reads, never on the
    # exit status (a route that applied and timed out is a route that applied).
    say "could not confirm tailnet slot $SERVE_SLOT points at $SPARE_PORT (it reads: $(slot_says)); bringing everything back to $NAME"
    settle || say "NOT SETTLED: run deploy.sh --check"
    say "$NAME serves and is the writer; $1 was NOT deployed"
    return 1
  fi
  # $1 passed the smoke and serves the slot: it is the current image from here on.
  if have_image "$NAME:current"; then podman tag "$NAME:current" "$NAME:previous"; fi
  podman tag "$img" "$NAME:current"
  say "$NEXT ($1) serves tailnet slot $SERVE_SLOT and is the writer; replacing $NAME on $PORT"
  stop_container
  if start_container "$img" fenced && smoke; then
    rc=0; hand_back || rc=$?
    if [ "$rc" = 0 ]; then
      say "deployed $NAME from $1 on http://$BIND:$PORT/ with no gap on tailnet slot $SERVE_SLOT (data: $DATA)"
      return 0
    fi
    if [ "$rc" = 2 ]; then
      say "$1 is running as $NAME on $PORT, but tailnet slot $SERVE_SLOT is NOT CONFIRMED there; this is not a clean deploy. deploy.sh --check settles it"
      return 1
    fi
    # rc 1: $NAME passed its smoke and is left running; $NEXT keeps the slot and the writer
    say "$1 IS DEPLOYED and $NAME runs on $PORT, but $NEXT keeps tailnet slot $SERVE_SLOT and is the writer (the hand-back did not happen); deploy.sh --check hands it back"
    return 1
  fi
  say "$NAME did not come back on $PORT; last log lines:"
  podman logs --tail 20 "$NAME" 2>&1 | sed 's/^/    /' || true
  stop_container
  say "$1 IS DEPLOYED but serves from $NEXT on $SPARE_PORT (tailnet slot $SERVE_SLOT); $PORT is down. deploy.sh --start moves it back."
  return 1
}

if [ "$MODE" != status ] && [ "$DRY" != 1 ]; then
  if ! take_deploy_lock; then
    if [ "$MODE" = check ]; then exit 0; fi  # a deploy in progress is not a state to repair
    say "another deploy.sh for $NAME is running (pid $LOCK_HOLDER, lock $DEPLOY_LOCK); not starting a second"
    exit 75
  fi
  exec 3>&1 4>&2
  trap on_signal INT TERM
fi

case "$MODE" in
  check)
    # Only while $NAME serves: a $NAME that does not serve is preview.sh's
    # --start, which restarts it; this never restarts anything.
    serves "$NAME" || exit 0
    problems=$(rest_problems)
    [ -n "$problems" ] || exit 0
    say "NOT AT REST, repairing:"; printf '%s\n' "$problems" | sed 's/^/    /'
    if settle; then say "at rest: $NAME serves on $PORT and is the writer"; exit 0; fi
    say "NOT REPAIRED; still:"; rest_problems | sed 's/^/    /'
    exit 1 ;;
  status)
    if have_container "$NAME"; then
      podman ps -a --filter "name=^$NAME$" --format 'container {{.Names}}  {{.Status}}  image {{.Image}}'
      printf 'current  -> commit %s\nprevious -> commit %s  (equal right after a rollback)\n' \
        "$(podman inspect -f '{{index .Labels "wisenotes.sha"}}' "$NAME:current" 2>/dev/null || echo none)" \
        "$(podman inspect -f '{{index .Labels "wisenotes.sha"}}' "$NAME:previous" 2>/dev/null || echo none)"
      printf 'serving commit: %s\nprobe: /health %s  GET / %s\n' \
        "$(podman inspect -f '{{index .Config.Labels "wisenotes.sha"}}' "$NAME")" "$(probe /health)" "$(probe /)"
      if have_container "$NEXT"; then
        podman ps -a --filter "name=^$NEXT$" --format 'beside: container {{.Names}}  {{.Status}}  image {{.Image}}'
      fi
      [ -z "$SERVE_SLOT" ] || printf 'tailnet slot %s -> %s\n' "$SERVE_SLOT" "$(slot_says)"
      if fence_container "$NAME"; then
        if [ "$(head -n 1 "$FENCE" 2>/dev/null)" = "$(writer_of "$NAME")" ]; then
          echo "writer: $NAME"
        else
          echo "writer: NOT $NAME (the file names $(head -n 1 "$FENCE" 2>/dev/null || echo nobody)); $NAME refuses writes; run deploy.sh --check"
        fi
      fi
    else
      say "no container named $NAME"; exit 1
    fi
    exit 0 ;;
  start)
    have_image "$NAME:current" || { say "no $NAME:current image; run a deploy first"; exit 1; }
    [ -d "$DATA" ] || { say "creating data dir $DATA"; run mkdir -p "$DATA"; }
    say "starting $NAME from the current image"
    port_move_warning
    stop_container
    if [ -n "$SERVE_SLOT" ] && is_running "$NEXT"; then
      # a deploy left $NEXT serving: start $NAME unable to write, then hand back
      say "$NEXT serves tailnet slot $SERVE_SLOT; starting $NAME beside it"
      if start_container "$NAME:current" fenced && smoke; then
        rc=0; hand_back || rc=$?
        [ "$rc" = 0 ] && exit 0
        if [ "$rc" = 2 ]; then
          say "$NAME serves on $PORT as the writer, but tailnet slot $SERVE_SLOT is NOT CONFIRMED there; deploy.sh --check settles it"
          exit 1
        fi
      fi
      say "current image failed to start, failed smoke or could not take over; $NEXT keeps serving; last log lines:"
      podman logs --tail 20 "$NAME" 2>&1 | sed 's/^/    /' || true
      stop_container
      exit 1
    fi
    if start_container "$NAME:current" && smoke; then route_home; exit 0; fi
    # Never leave serving an image that fails the smoke check.
    say "current image failed to start or failed smoke: NOTHING IS SERVING; last log lines:"
    podman logs --tail 20 "$NAME" 2>&1 | sed 's/^/    /' || true
    stop_container
    exit 1 ;;
  rollback)
    have_image "$NAME:previous" || { say "no $NAME:previous image; nothing to roll back to"; exit 1; }
    say "rolling back: previous -> current"
    run podman tag "$NAME:previous" "$NAME:current"
    stop_container; start_container "$NAME:current"
    smoke || { say "previous image failed smoke too; container left running for inspection"; exit 1; }
    route_home
    exit 0 ;;
esac

# ---- deploy
[ -d "$DATA" ] || { say "creating data dir $DATA"; run mkdir -p "$DATA"; }
say "ref $REF -> fetch"
run git -C "$repo" fetch -q origin
sha=$(git -C "$repo" rev-parse --short "$REF") || { say "unknown ref $REF"; exit 2; }
say "building $NAME:$sha from git archive"
ctx=$(mktemp -d); CLEANUP+=("$ctx")
if [ "$DRY" = 1 ]; then
  printf '  + git archive %s | tar -x -C %s && podman build -t %s:%s %s\n' "$sha" "$ctx" "$NAME" "$sha" "$ctx"
else
  git -C "$repo" archive "$sha" | tar -x -C "$ctx"
  podman build -q -t "$NAME:$sha" --label "wisenotes.sha=$sha" --build-arg "WISENOTES_VERSION=$sha" \
    -f "$ctx/Dockerfile" "$ctx" >/dev/null
fi

blocker=$(beside_blocker "$NAME:$sha")
if [ -z "$blocker" ]; then
  if [ "$DRY" = 1 ]; then
    say "would start $sha as $NEXT on $SPARE_PORT beside $NAME, smoke it, make it the writer, point tailnet slot $SERVE_SLOT at it, then bring $NAME back on $PORT from $sha and hand back"
    say "dry run ends here (smoke, hand-over not simulated)"; exit 0
  fi
  deploy_beside "$sha"; exit $?
fi

say "replacing container $NAME in place (was: $(image_of_running || echo none)); it is down until the new one answers, because $blocker"
port_move_warning
stop_container
if [ "$DRY" = 1 ]; then
  start_container "$NAME:$sha"
  printf '  + (after smoke ok) podman tag %s:current %s:previous; podman tag %s:%s %s:current\n' \
    "$NAME" "$NAME" "$NAME" "$sha" "$NAME"
  say "dry run ends here (smoke, rollback not simulated)"; exit 0
fi

# `current` is retagged only after the new image has started AND passed the smoke
# check, so on any failure below it still names the last good image.
if start_container "$NAME:$sha" && smoke; then
  if have_image "$NAME:current"; then podman tag "$NAME:current" "$NAME:previous"; fi
  podman tag "$NAME:$sha" "$NAME:current"
  say "deployed $NAME from $sha on http://$BIND:$PORT/ (data: $DATA)"
  route_home
  exit 0
fi

say "$sha failed to start or failed smoke; last log lines:"
podman logs --tail 20 "$NAME" 2>&1 | sed 's/^/    /' || true
stop_container
if have_image "$NAME:current"; then
  say "restarting the current (last good) image"
  if start_container "$NAME:current" && smoke; then
    say "ROLLED BACK: the current image is serving; $sha was NOT deployed"
    route_home
  else
    stop_container
    say "the current image also fails: NOTHING IS SERVING"
  fi
else
  say "no current image: NOTHING IS SERVING (first deploy failed)"
fi
exit 1
