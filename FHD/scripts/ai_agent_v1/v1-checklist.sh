#!/usr/bin/env bash
# AI Agent V1 demo 证据校验
#   bash scripts/ai_agent_v1/v1-checklist.sh --check-only
#   bash scripts/ai_agent_v1/v1-checklist.sh --verify
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EVIDENCE="${ROOT}/docs/evidence/ai-agent-v1"
PLAN="${ROOT}/docs/ai-agent-v1-plan.md"
RUN_DEMO="${ROOT}/scripts/ai_agent_v1/run_demo_create_order.py"
RUN_V1="${ROOT}/scripts/ai_agent_v1/run_demo_v1.py"

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
else
  PYTHON="python3"
fi

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

verify_phase1() {
  local missing=0
  for tag in auto interactive reject; do
    if ! ls "${EVIDENCE}"/create-order-${tag}-*.json >/dev/null 2>&1; then
      echo "FAIL: missing create-order-${tag}-*.json evidence" >&2
      missing=1
    fi
  done
  return "$missing"
}

verify_phase2() {
  local missing=0
  for n in 1 2 3 4 5 6 7; do
    if ! ls "${EVIDENCE}"/scenario-${n}-*.json >/dev/null 2>&1; then
      echo "WARN: missing scenario-${n}-*.json evidence (Phase 2 未跑全)" >&2
    fi
  done
  return "$missing"
}

verify_evidence_json() {
  local file="$1"
  local required=("input_message" "plan_id" "intent" "success" "gated_decision")
  "$PYTHON" - "$file" <<'PY' || return 1
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
required = ("input_message", "plan_id", "intent", "success", "gated_decision")
missing = [k for k in required if k not in data]
if missing:
    raise SystemExit(f"FAIL: {path} missing keys: {missing}")
print(f"OK  {path}")
PY
}

case "$mode" in
  --check-only)
    check_paths
    for f in "$RUN_DEMO" "$RUN_V1"; do
      if [[ -f "$f" ]]; then
        echo "OK  $f (present)"
      else
        echo "PENDING  $f (待补)"
      fi
    done
    echo "check-only passed"
    ;;
  --verify)
    check_paths
    verify_phase1
    verify_phase2
    # 校验所有 JSON 结构
    failed=0
    while IFS= read -r json_file; do
      if ! verify_evidence_json "$json_file"; then
        failed=1
      fi
    done < <(find "$EVIDENCE" -maxdepth 1 -name '*.json' 2>/dev/null)
    if [[ "$failed" -eq 0 ]]; then
      echo "verify passed"
    else
      echo "verify failed" >&2
      exit 1
    fi
    ;;
  --paths)
    echo "PLAN=$PLAN"
    echo "EVIDENCE=$EVIDENCE"
    echo "RUN_DEMO=$RUN_DEMO"
    echo "RUN_V1=$RUN_V1"
    ;;
  *)
    echo "Usage: $0 [--check-only|--verify|--paths]" >&2
    exit 2
    ;;
esac
