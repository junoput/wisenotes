#!/usr/bin/env bash
# Keep the preview container on the tip of a branch: poll origin, redeploy on change.
#
#   deploy/preview.sh                 one pass: fetch, compare, deploy if the tip moved
#   deploy/preview.sh --loop [secs]   forever, sleeping <secs> between passes (default 120)
#
# Uses deploy/deploy.sh, so a tip that fails the smoke check is rolled back and the
# previous tip keeps serving; the next pass tries again only when the tip moves on.
# Settings come from deploy/.env or the environment, same names as deploy.sh, plus
# WISENOTES_BRANCH (default develop). Runs from a checkout that the operator does
# not edit by hand: it only fetches.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/.." && pwd)
[ -f "$here/.env" ] && { set -a; . "$here/.env"; set +a; }
BRANCH=${WISENOTES_BRANCH:-develop}
NAME=${WISENOTES_NAME:-wisenotes}
LOOP=0; SLEEP=120
case "${1:-}" in
  --loop) LOOP=1; SLEEP=${2:-120} ;;
  "") ;;
  *) echo "preview: unknown argument '$1'" >&2; exit 2 ;;
esac

serving_sha() { podman inspect -f '{{index .Config.Labels "wisenotes.sha"}}' "$NAME" 2>/dev/null || true; }
last_tried_file="$here/.preview-last-tried"   # gitignored; a tip that failed smoke is not retried every pass

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
  echo "preview: $BRANCH moved ${serving:-none} -> $tip; deploying"
  printf '%s\n' "$tip" >"$last_tried_file"
  "$here/deploy.sh" --ref "origin/$BRANCH" || echo "preview: $tip refused by smoke; serving $(serving_sha)"
}

if [ "$LOOP" = 1 ]; then
  while true; do pass; sleep "$SLEEP"; done
else
  pass
fi
