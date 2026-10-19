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

# Only a RUNNING container that ANSWERS serves. A stopped one (after a reboot)
# still has its label, and counting it made a pass report "already serving"
# with nothing up. A running one can be deaf too: on 2026-10-19 a restart of
# the preview unit killed the container's port forwarder (pasta) while podman
# restarted the container itself, and every pass said "already serving".
# One slow answer is not deafness: treating it as down removes a working
# container from the live notes, so only the second failed pass in a row does.
# `serving_sha --judge` is the one call per pass that counts towards that.
serving_sha() {
  local sha addr code
  sha=$(podman inspect -f '{{if .State.Running}}{{index .Config.Labels "wisenotes.sha"}}{{end}}' "$NAME" 2>/dev/null || true)
  [ -n "$sha" ] || return 0
  addr=$(podman port "$NAME" 8000/tcp 2>/dev/null || true)
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://$addr/health" || true)
  if [ "$code" = 200 ]; then
    rm -f "$deaf_file"
    echo "$sha"
  elif [ "${1:-}" != --judge ]; then
    echo "$sha"
  elif [ -f "$deaf_file" ]; then
    rm -f "$deaf_file"
    echo "preview: $NAME is running $sha but http://$addr/health answers ${code:-nothing}, the second pass in a row; treating it as down" >&2
  else
    : >"$deaf_file"
    echo "preview: $NAME is running $sha but http://$addr/health answers ${code:-nothing}; checking again next pass before treating it as down" >&2
    echo "$sha"
  fi
}
last_tried_file="$here/.preview-last-tried"   # gitignored; a tip that failed smoke is not retried every pass
deaf_file="$here/.preview-deaf"               # gitignored; set by one failed /health pass

# Move the checkout to $1, so the deploy below is the tip's own deploy.sh.
# Returns 1 (deploy nothing) if tracked files were edited here, or if the
# checkout did not end up at $1: deploying then would run the old deploy.sh
# under a log line naming the tip, and re-executing would run the old
# preview.sh again, with no sleep, for as long as the checkout keeps failing.
checkout_tip() {
  local tip=$1 before
  if ! git -C "$repo" diff --quiet HEAD --; then
    echo "preview: $repo has edits to tracked files; not moving it to $tip and not deploying"
    git -C "$repo" diff --stat HEAD -- | sed 's/^/    /'
    return 1
  fi
  before=$(git -C "$repo" rev-parse HEAD)
  if ! git -C "$repo" checkout -q --detach "$tip"; then
    echo "preview: could not move $repo to $tip; not deploying"
    return 1
  fi
  if [ "$(git -C "$repo" rev-parse HEAD)" != "$(git -C "$repo" rev-parse "$tip^{commit}")" ]; then
    echo "preview: $repo is at $(git -C "$repo" rev-parse --short HEAD), not $tip; not deploying"
    return 1
  fi
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
  serving=$(serving_sha --judge)
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
