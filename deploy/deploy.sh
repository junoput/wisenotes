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
#   3. replace the container: stop+rm the old one, run wisenotes:<sha>
#   4. smoke: /health must answer 200 AND GET / must answer 200 within 60s
#      (GET / is the check that would have caught the "every page 500s"
#      release; /health alone was green through it)
#   5. only after the smoke passes, retag: current -> previous, <sha> -> current.
#      So `current` only ever names an image that passed the smoke check.
#   6. if the run or the smoke fails: remove the new container and start
#      `current` again (untouched, so still the last good image), exit 1. If
#      there is no current image, nothing serves and the exit says so.
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
DRY=0; MODE=deploy

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF=$2; shift 2 ;;
    --rollback) MODE=rollback; shift ;;
    --start) MODE=start; shift ;;
    status) MODE=status; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "deploy: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "deploy: $*"; }
run() { if [ "$DRY" = 1 ]; then printf '  + %s\n' "$*"; else "$@"; fi; }
have_image() { podman image exists "$1"; }
have_container() { podman container exists "$1"; }
image_of_running() { podman inspect -f '{{.ImageName}}' "$NAME" 2>/dev/null || true; }

probe() { # $1 path -> prints http status or 000
  curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://$BIND:$PORT$1" || true  # prints 000 on no answer
}

smoke() { # wait until both probes answer 200; return 1 on timeout
  local deadline=$((SECONDS + SMOKE_SECONDS)) h p
  while [ $SECONDS -lt $deadline ]; do
    h=$(probe /health); p=$(probe /)
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

start_container() { # $1 image
  # keep-id: the process runs as the host user, so it can write the bind-mounted
  # data dir; without it rootless podman maps the image user to a subuid and
  # every write to /app/data is EACCES (found in rehearsal).
  # No --restart: the unit is the one restarter. A podman policy as well would
  # put a second, box-wide restarter (podman-restart.service) back in play.
  run podman create --name "$NAME" \
    --userns=keep-id --user "$(id -u):$(id -g)" \
    -p "$BIND:$PORT:8000" \
    -v "$DATA:/app/data:Z" \
    -e WISENOTES_DATA_DIR=/app/data \
    "$1" >/dev/null || return 1
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

case "$MODE" in
  status)
    if have_container "$NAME"; then
      podman ps -a --filter "name=^$NAME$" --format 'container {{.Names}}  {{.Status}}  image {{.Image}}'
      printf 'current  -> commit %s\nprevious -> commit %s  (equal right after a rollback)\n' \
        "$(podman inspect -f '{{index .Labels "wisenotes.sha"}}' "$NAME:current" 2>/dev/null || echo none)" \
        "$(podman inspect -f '{{index .Labels "wisenotes.sha"}}' "$NAME:previous" 2>/dev/null || echo none)"
      printf 'serving commit: %s\nprobe: /health %s  GET / %s\n' \
        "$(podman inspect -f '{{index .Config.Labels "wisenotes.sha"}}' "$NAME")" "$(probe /health)" "$(probe /)"
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
    if start_container "$NAME:current" && smoke; then exit 0; fi
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

say "replacing container $NAME (was: $(image_of_running || echo none))"
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
  exit 0
fi

say "$sha failed to start or failed smoke; last log lines:"
podman logs --tail 20 "$NAME" 2>&1 | sed 's/^/    /' || true
stop_container
if have_image "$NAME:current"; then
  say "restarting the current (last good) image"
  if start_container "$NAME:current" && smoke; then
    say "ROLLED BACK: the current image is serving; $sha was NOT deployed"
  else
    stop_container
    say "the current image also fails: NOTHING IS SERVING"
  fi
else
  say "no current image: NOTHING IS SERVING (first deploy failed)"
fi
exit 1
