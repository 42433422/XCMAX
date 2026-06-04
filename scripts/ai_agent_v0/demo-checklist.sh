#!/usr/bin/env bash
# AI Agent V0 demo 证据校验（M2-W2）
#   bash scripts/ai_agent_v0/demo-checklist.sh --check-only
#   bash scripts/ai_agent_v0/demo-checklist.sh --verify
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EVIDENCE="${ROOT}/docs/evidence/ai-agent-v0"
PLAN="${ROOT}/docs/ai-agent-v0-plan.md"
RUN_DEMO="${ROOT}/scripts/ai_agent_v0/run_demo.py"

mode="${1:---check-only}"

check_paths() {
  local ok=0
  for f in "$PLAN" "${EVIDENCE}/README.md"; do
    if [[ -f "$f" ]]; then
      echo "OK  $f"
    else
      echo "MISS $f" >&2
      ok=1
    fi
  done
  if [[ ! -d "$EVIDENCE" ]]; then
    echo "MISS directory $EVIDENCE" >&2
    ok=1
  fi
  return "$ok"
}

verify_evidence() {
  local json_count
  json_count="$(find "$EVIDENCE" -maxdepth 1 -name 'demo-run-*.json' 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$json_count" -lt 1 ]]; then
    echo "FAIL: need at least one demo-run-*.json under $EVIDENCE" >&2
    return 1
  fi
  local latest
  latest="$(find "$EVIDENCE" -maxdepth 1 -name 'demo-run-*.json' -print | sort | tail -1)"
  python3 - "$latest" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
required = ("input_message", "plan_id", "intent", "success")
missing = [k for k in required if k not in data]
if missing:
    raise SystemExit(f"FAIL: {path} missing keys: {missing}")
if data.get("success") is not True:
    raise SystemExit(f"FAIL: {path} success != true")
print(f"OK  {path}")
PY
}

case "$mode" in
  --check-only)
    check_paths
    if [[ -f "$RUN_DEMO" ]]; then
      echo "OK  $RUN_DEMO (present)"
    else
      echo "PENDING  $RUN_DEMO (stub — implement per ai-agent-v0-plan.md)"
    fi
    echo "check-only passed"
    ;;
  --verify)
    check_paths
    verify_evidence
    echo "verify passed"
    ;;
  --paths)
    echo "PLAN=$PLAN"
    echo "EVIDENCE=$EVIDENCE"
    echo "RUN_DEMO=$RUN_DEMO"
    ;;
  *)
    echo "Usage: $0 [--check-only|--verify|--paths]" >&2
    exit 2
    ;;
esac
