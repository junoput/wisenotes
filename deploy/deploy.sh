#!/usr/bin/env bash
# Deploy wisenotes as one rootless podman container, with rollback.
#
#   deploy/deploy.sh                 build+start from $WISENOTES_REF (default origin/develop)
#   deploy/deploy.sh --ref <ref>     any git ref: a branch, tag or sha (rehearsals)
#   deploy/deploy.sh --rollback      put the previous image back and start it
#   deploy/deploy.sh --start         start the current image again (after a reboot); no build
#   deploy/deploy.sh status          what is running, from which image
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
DRY=0; MODE=deploy

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF=$2; shift 2 ;;
    --rollback) MODE=rollback; shift ;;
    --start) MODE=start; shift ;;
    status) MODE=status; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,56p' "$0"; exit 0 ;;
    *) echo "deploy: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "deploy: $*"; }
run() { if [ "$DRY" = 1 ]; then printf '  + %s\n' "$*"; else "$@"; fi; }
have_image() { podman image exists "$1"; }
have_container() { podman container exists "$1"; }
image_of_running() { podman inspect -f '{{.ImageName}}' "$NAME" 2>/dev/null || true; }

probe() { # $1 path, $2 port (default $PORT) -> prints http status or 000
  curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://$BIND:${2:-$PORT}$1" || true  # prints 000 on no answer
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
  local write='printf "%s\n" "$1" >"$2.tmp" && mv -f "$2.tmp" "$2"'
  if command -v flock >/dev/null; then
    run flock -x -w "$DRAIN_SECONDS" "$FENCE_LOCK" sh -c "$write" set_writer "$1" "$FENCE"
  else
    run touch "$FENCE_LOCK" && run sh -c "$write" set_writer "$1" "$FENCE"
  fi
}

slot_target() { # what the tailnet slot's "/" proxies to, or nothing
  command -v jq >/dev/null || return 0
  timeout 10 tailscale serve status --json 2>/dev/null \
    | jq -r --arg p ":$SERVE_SLOT" '(.Web // {}) | to_entries[] | select(.key | endswith($p)) | .value.Handlers["/"].Proxy // empty' 2>/dev/null \
    | head -1 || true
}

slot_points_at() { # $1 port
  case "$(slot_target)" in
    "http://localhost:$1"|"http://127.0.0.1:$1"|"http://$BIND:$1") return 0 ;;
  esac
  return 1
}

route() { # $1 port: point the tailnet slot at it. The slot's URL does not change.
  run timeout 20 tailscale serve --bg --http="$SERVE_SLOT" "http://$BIND:$1" >/dev/null || return 1
  [ "$DRY" = 1 ] || slot_points_at "$1"
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
  if have_container "$NEXT"; then stop_next; fi
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
  slot_points_at "$PORT" || { echo "tailnet slot $SERVE_SLOT proxies to $(slot_target | grep . || echo nothing), not to $PORT"; return; }
}

hand_back() { # $NEXT serves and writes; make $NAME (running fenced on $PORT) the writer and the slot's target
  local next_id
  next_id=$(writer_of "$NEXT")
  set_writer "$(writer_of "$NAME")" || { say "writes on $NEXT did not finish within ${DRAIN_SECONDS}s"; return 1; }
  if ! route "$PORT"; then
    say "could not point tailnet slot $SERVE_SLOT back at $PORT; $NEXT stays the writer"
    set_writer "$next_id" || say "AND could not make $NEXT the writer again: NOTHING CAN WRITE until a deploy or --start"
    return 1
  fi
  stop_next
}

deploy_beside() { # $1 sha; 0 deployed, 1 not deployed
  local img="$NAME:$1" old_id id
  old_id=$(writer_of "$NAME")
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
    set_writer "$old_id" || say "AND could not make $NAME the writer again: NOTHING CAN WRITE until a deploy or --start"
    stop_next
    say "could not point tailnet slot $SERVE_SLOT at $SPARE_PORT; $NAME still serves; $1 was NOT deployed"
    return 1
  fi
  # $1 passed the smoke and serves the slot: it is the current image from here on.
  if have_image "$NAME:current"; then podman tag "$NAME:current" "$NAME:previous"; fi
  podman tag "$img" "$NAME:current"
  say "$NEXT ($1) serves tailnet slot $SERVE_SLOT and is the writer; replacing $NAME on $PORT"
  stop_container
  if start_container "$img" fenced && smoke && hand_back; then
    say "deployed $NAME from $1 on http://$BIND:$PORT/ with no gap on tailnet slot $SERVE_SLOT (data: $DATA)"
    return 0
  fi
  say "$NAME did not come back on $PORT; last log lines:"
  podman logs --tail 20 "$NAME" 2>&1 | sed 's/^/    /' || true
  stop_container
  say "$1 IS DEPLOYED but serves from $NEXT on $SPARE_PORT (tailnet slot $SERVE_SLOT); $PORT is down. deploy.sh --start moves it back."
  return 1
}

case "$MODE" in
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
      [ -z "$SERVE_SLOT" ] || printf 'tailnet slot %s -> %s\n' "$SERVE_SLOT" "$(slot_target | grep . || echo nothing)"
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
      if start_container "$NAME:current" fenced && smoke && hand_back; then exit 0; fi
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
ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
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
