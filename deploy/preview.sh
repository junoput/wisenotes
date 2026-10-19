#!/usr/bin/env bash
# Keep the preview container on the tip of a branch: poll origin, redeploy on change.
#
#   deploy/preview.sh                 one pass: fetch, compare, deploy if the tip moved
#   deploy/preview.sh --loop [secs]   forever, sleeping <secs> between passes (default 120)
#
# Uses deploy/deploy.sh, so a tip that fails the smoke check is rolled back and the
# previous tip keeps serving; the next pass tries again only when the tip moves on.
# Settings come from deploy/.env or the environment, same names as deploy.sh, plus
# WISENOTES_BRANCH (default develop).
#
# Runs from a checkout of its own that nobody edits by hand, outside any worker
# lane. Before each deploy it moves that checkout (detached) to the tip, so the
# deploy runs with the tip's own deploy.sh, not with whatever deploy.sh the
# checkout held when the loop started. If preview.sh itself changed at the tip,
# it re-executes itself first. A checkout with edits to tracked files is never
# moved, and nothing is deployed from it. deploy/.env and the last-tried marker
# are gitignored, so they survive the move.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/.." && pwd)
[ -f "$here/.env" ] && { set -a; . "$here/.env"; set +a; }
BRANCH=${WISENOTES_BRANCH:-develop}
NAME=${WISENOTES_NAME:-wisenotes}
ARGS=("$@")
LOOP=0; SLEEP=120
case "${1:-}" in
  --loop) LOOP=1; SLEEP=${2:-120} ;;
  "") ;;
  *) echo "preview: unknown argument '$1'" >&2; exit 2 ;;
esac

# Only a RUNNING container serves. A stopped one (after a reboot) still has its
# label, and counting it made a pass report "already serving" with nothing up.
serving_sha() { podman inspect -f '{{if .State.Running}}{{index .Config.Labels "wisenotes.sha"}}{{end}}' "$NAME" 2>/dev/null || true; }
last_tried_file="$here/.preview-last-tried"   # gitignored; a tip that failed smoke is not retried every pass

# Move the checkout to $1, so the deploy below is the tip's own deploy.sh.
# Returns 1 (deploy nothing) if tracked files were edited here.
checkout_tip() {
  local tip=$1 before
  if ! git -C "$repo" diff --quiet HEAD --; then
    echo "preview: $repo has edits to tracked files; not moving it to $tip and not deploying"
    git -C "$repo" diff --stat HEAD -- | sed 's/^/    /'
    return 1
  fi
  before=$(git -C "$repo" rev-parse HEAD)
  git -C "$repo" checkout -q --detach "$tip"
  if [ "$(git -C "$repo" rev-parse "$before:deploy/preview.sh")" != "$(git -C "$repo" rev-parse "$tip:deploy/preview.sh")" ]; then
    # bash keeps reading the old file; run the tip's preview.sh instead
    echo "preview: preview.sh changed at $tip; restarting it"
    exec "$here/preview.sh" "${ARGS[@]}"
  fi
}

pass() {
  local tip serving tried
  git -C "$repo" fetch -q origin "$BRANCH" || { echo "preview: fetch failed; keeping $(serving_sha)"; return 0; }
  tip=$(git -C "$repo" rev-parse --short "origin/$BRANCH")
  serving=$(serving_sha)
  tried=$(cat "$last_tried_file" 2>/dev/null || true)
  if [ -z "$serving" ] && podman image exists "$NAME:current"; then
    # nothing running (a reboot, or a removed container) but a good image exists: serve it
    echo "preview: no container running; starting the current image"
    "$here/deploy.sh" --start || echo "preview: current image failed to start"
    serving=$(serving_sha)
  fi
  if [ "$tip" = "$serving" ]; then echo "preview: $BRANCH at $tip already serving"; return 0; fi
  if [ "$tip" = "$tried" ]; then echo "preview: $BRANCH at $tip failed smoke earlier; still serving ${serving:-nothing}; waiting for the tip to move"; return 0; fi
  echo "preview: $BRANCH moved ${serving:-none} -> $tip; deploying with the deploy scripts at $tip"
  checkout_tip "$tip" || return 0
  printf '%s\n' "$tip" >"$last_tried_file"
  "$here/deploy.sh" --ref "$tip" || echo "preview: $tip refused by smoke; serving $(serving_sha)"
}

if [ "$LOOP" = 1 ]; then
  while true; do pass; sleep "$SLEEP"; done
else
  pass
fi
