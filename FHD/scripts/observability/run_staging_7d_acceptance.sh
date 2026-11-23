#!/usr/bin/env bash
# Validate original native k6 evidence. Production SLO is a separate observation.
# SOURCE_SHA=<deployed-sha> K6_EVIDENCE_DIR=<run-dir> bash scripts/observability/run_staging_7d_acceptance.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WINDOW_DAYS="${WINDOW_DAYS:-7}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --window-days) WINDOW_DAYS="$2"; shift 2 ;;
    --prefix) [[ "$2" == staging ]] || { echo "Only staging evidence is accepted" >&2; exit 1; }; shift 2 ;;
    --mode) [[ "$2" == k6_7d ]] || { echo "Only native k6_7d evidence is accepted" >&2; exit 1; }; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done
: "${SOURCE_SHA:?Set the exact deployed source SHA}"
: "${K6_EVIDENCE_DIR:?Set the directory containing k6-7d-summary.json and k6-7d-samples.jsonl}"
python3 "${ROOT}/scripts/loadtest/validate_evidence.py" "${K6_EVIDENCE_DIR}" \
  --source-sha "${SOURCE_SHA}" --chat-soak --window-days "${WINDOW_DAYS}"
printf '%s\n' "Synthetic staging chat soak passed; production SLO and business reconciliation are not certified."
