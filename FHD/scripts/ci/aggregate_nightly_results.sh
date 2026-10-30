#!/usr/bin/env bash
# Aggregate real downstream conclusions for Nightly Full CI.
# Must not succeed only because dispatch was accepted.
set -euo pipefail

: "${GH_TOKEN:?required}"
: "${REF:?required}"
: "${RELEASE_SHA:?required}"
: "${GITHUB_REPOSITORY:?required}"

REPO="${GITHUB_REPOSITORY}"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
failed_dispatch=(); failed_runs=(); watched=()

dispatch_one() {
  local wf="$1"; shift || true
  echo "==> dispatch ${wf} @ ${REF}"
  if ! gh workflow run "${wf}" --repo "${REPO}" --ref "${REF}" "$@"; then
    failed_dispatch+=("${wf}"); return 1
  fi
  return 0
}

wait_one() {
  local wf="$1" run_id="" attempt
  for attempt in $(seq 1 90); do
    runs="$(gh run list --repo "${REPO}" --workflow "${wf}" --branch "${REF}" --limit 30 --json databaseId,createdAt,headSha,status,conclusion,event)"
    run_id="$(jq -r --arg sha "${RELEASE_SHA}" --arg started "${started_at}" '[.[] | select(.headSha == $sha and .createdAt >= $started and .event == "workflow_dispatch")] | sort_by(.createdAt) | last | .databaseId // empty' <<<"${runs}")"
    if [[ "${run_id}" =~ ^[0-9]+$ ]]; then break; fi
    sleep 5
  done
  if ! [[ "${run_id}" =~ ^[0-9]+$ ]]; then
    echo "::error::Unable to correlate downstream run for ${wf}"
    failed_runs+=("${wf}:uncorrelated"); return 1
  fi
  echo "Watching ${wf} run ${run_id}"
  watched+=("${wf}:${run_id}")
  if ! gh run watch "${run_id}" --repo "${REPO}" --exit-status --interval 30; then
    conclusion="$(gh run view "${run_id}" --repo "${REPO}" --json conclusion -q .conclusion)"
    failed_runs+=("${wf}:${run_id}:${conclusion:-failed}"); return 1
  fi
  return 0
}

workflows=(
  fhd-release-gate-ci.yml
  fhd-mutation-smoke.yml
  codeql.yml
  fhd-alembic-ssot.yml
  desktop-macos-smoke.yml
  fhd-ci-mobile-flutter.yml
)
for wf in "${workflows[@]}"; do dispatch_one "${wf}" || true; done
dispatch_one fhd-security-full-scan.yml -f "release_sha=${RELEASE_SHA}" || true

if ((${#failed_dispatch[@]} > 0)); then echo "::error::Nightly dispatch failed:${failed_dispatch[*]}"; exit 1; fi

for wf in "${workflows[@]}" fhd-security-full-scan.yml; do wait_one "${wf}" || true; done

echo "Nightly watched runs: ${watched[*]:-none}"
if ((${#failed_runs[@]} > 0)); then echo "::error::Nightly downstream failures:${failed_runs[*]}"; exit 1; fi
echo "Nightly aggregate PASS: all downstream suites concluded successfully."
