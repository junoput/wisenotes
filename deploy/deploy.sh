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
#   3. retag: current -> previous, <sha> -> current
#   4. replace the container: stop+rm the old one, run the new one
#   5. smoke: /health must answer 200 AND GET / must answer 200 within 60s
#      (GET / is the check that would have caught the "every page 500s"
#      release; /health alone was green through it)
#   6. on smoke failure: remove the new container, retag previous -> current,
#      start previous again, exit 1. If there is no previous, nothing serves
#      and the exit says so.
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

start_container() { # $1 image
  # keep-id: the process runs as the host user, so it can write the bind-mounted
  # data dir; without it rootless podman maps the image user to a subuid and
  # every write to /app/data is EACCES (found in rehearsal).
  run podman run -d --name "$NAME" --restart=always \
    --userns=keep-id --user "$(id -u):$(id -g)" \
    -p "$BIND:$PORT:8000" \
    -v "$DATA:/app/data:Z" \
    -e WISENOTES_DATA_DIR=/app/data \
    "$1" >/dev/null
}

stop_container() {
  if have_container "$NAME"; then run podman rm -f "$NAME" >/dev/null; fi
}

ensure_boot_persistence() {
  # rootless containers restart on boot only through the user's podman-restart unit
  # is-system-running exits non-zero for "degraded" (a failed unit somewhere), which is
  # still a running user manager; only offline/unknown/missing mean no systemd
  local state; state=$(systemctl --user is-system-running 2>/dev/null || true)
  if [ "$state" = running ] || [ "$state" = degraded ] || [ "$state" = starting ]; then
    if ! systemctl --user is-enabled podman-restart >/dev/null 2>&1; then
      say "enabling podman-restart.service (user) so the container returns after a reboot"
      run systemctl --user enable --now podman-restart.service || say "could not enable podman-restart; run it by hand"
    fi
  else
    say "no user systemd here: the container will not return after a reboot on this host"
  fi
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
    stop_container; start_container "$NAME:current"; ensure_boot_persistence
    smoke || { say "current image failed smoke; container left running for inspection"; exit 1; }
    exit 0 ;;
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
  podman build -q -t "$NAME:$sha" --label "wisenotes.sha=$sha" -f "$ctx/Dockerfile" "$ctx" >/dev/null
fi

if have_image "$NAME:current"; then run podman tag "$NAME:current" "$NAME:previous"; fi
run podman tag "$NAME:$sha" "$NAME:current"

say "replacing container $NAME (was: $(image_of_running || echo none))"
stop_container
start_container "$NAME:current"
ensure_boot_persistence
if [ "$DRY" = 1 ]; then say "dry run ends here (smoke, rollback not simulated)"; exit 0; fi

if smoke; then
  say "deployed $NAME from $sha on http://$BIND:$PORT/ (data: $DATA)"
  exit 0
fi

say "new image failed smoke; last log lines:"
podman logs --tail 20 "$NAME" 2>&1 | sed 's/^/    /' || true
stop_container
if have_image "$NAME:previous"; then
  say "rolling back to previous image"
  run podman tag "$NAME:previous" "$NAME:current"
  start_container "$NAME:current"
  if smoke; then say "ROLLED BACK: previous image is serving; $sha was NOT deployed"; else say "previous image also fails smoke; NOTHING IS SERVING"; fi
else
  say "no previous image: NOTHING IS SERVING (first deploy failed)"
fi
exit 1
