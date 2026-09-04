#!/usr/bin/env bash
# Dispatch one workflow and wait for the uniquely correlated run-name.
set -euo pipefail

workflow="${1:-}"
expected_title="${2:-}"
shift 2 || true

if [[ -z "$workflow" || -z "$expected_title" ]]; then
  echo "usage: dispatch_workflow_and_wait.sh <workflow> <run-title> [gh workflow run args...]" >&2
  exit 2
fi
: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GH_REPO:?GH_REPO is required}"

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gh workflow run "$workflow" --repo "$GH_REPO" --ref main "$@"

run_id=""
for _attempt in $(seq 1 60); do
  runs="$(gh run list \
    --repo "$GH_REPO" \
    --workflow "$workflow" \
    --event workflow_dispatch \
    --branch main \
    --limit 30 \
    --json databaseId,displayTitle,createdAt)"
  run_id="$(jq -r \
    --arg title "$expected_title" \
    --arg started "$started_at" \
    '[.[] | select(.displayTitle == $title and .createdAt >= $started)]
     | sort_by(.createdAt) | last | .databaseId // empty' <<<"$runs")"
  if [[ "$run_id" =~ ^[0-9]+$ ]]; then
    break
  fi
  sleep 5
done

if ! [[ "$run_id" =~ ^[0-9]+$ ]]; then
  echo "Unable to correlate dispatched $workflow with run-title: $expected_title" >&2
  exit 1
fi

echo "Watching $workflow run $run_id ($expected_title)"
gh run watch "$run_id" --repo "$GH_REPO" --exit-status --interval 30
