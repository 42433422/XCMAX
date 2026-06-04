#!/usr/bin/env bash
# 每周全量覆盖率 + 测试健康指标（写入 metrics/coverage-weekly.json）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
METRICS_DIR="${ROOT}/metrics"
mkdir -p "$METRICS_DIR"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
WEEK="$(date -u +%Y-W%V)"

PY="${ROOT}/.venv-cov/bin/python"
[[ -x "$PY" ]] || PY=python3

echo "=== pytest health (SKIP_INTEGRATION=1) ==="
export SKIP_INTEGRATION=1
HEALTH_LOG="${METRICS_DIR}/pytest-health-${WEEK}.log"
"$PY" -m pytest tests/ -q --tb=no \
  --continue-on-collection-errors \
  --ignore=tests/neuro/test_routing_policy.py \
  >"$HEALTH_LOG" 2>&1 || true
TAIL="$(tail -1 "$HEALTH_LOG")"
echo "$TAIL"

echo "=== backend coverage snapshot ==="
export COVERAGE_FILE="${ROOT}/.coverage.snapshot"
WEEK_XML="${METRICS_DIR}/coverage-full-${WEEK}.xml"
"$PY" -m pytest tests/ \
  --cov=app \
  --cov-report=xml:"${WEEK_XML}" \
  --cov-report=json:"${METRICS_DIR}/coverage-${WEEK}.json" \
  --cov-fail-under=0 \
  --ignore=tests/neuro/test_routing_policy.py \
  -q --continue-on-collection-errors \
  >/dev/null 2>&1 || true

BE_PCT=""
BE_COV=""
BE_STM=""
BE_CORE_PCT=""
BE_CORE_COV=""
BE_CORE_STM=""
if [[ -f "${WEEK_XML}" ]]; then
  "$PY" "${ROOT}/scripts/coverage_dual_summary.py" \
    --xml "${WEEK_XML}" \
    --json "${METRICS_DIR}/coverage-${WEEK}.json" \
    --data-file "${COVERAGE_FILE}" \
    --metrics-out "${METRICS_DIR}/coverage-dual-${WEEK}.json" \
    --dashboard-out "${ROOT}/../xcmax-pytest-coverage.json" \
    --quiet
  read -r BE_PCT BE_COV BE_STM BE_CORE_PCT BE_CORE_COV BE_CORE_STM < <("$PY" - <<PY
import json
from pathlib import Path
d = json.loads(Path("${METRICS_DIR}/coverage-dual-${WEEK}.json").read_text())
f = d["full_app"]
c = d["measured_core_c1"]
print(f["pct"], f["covered"], f["statements"], c["pct"], c["covered"], c["statements"])
PY
)
fi

FE_PCT=""
if command -v npm >/dev/null 2>&1; then
  (cd "${ROOT}/frontend" && rm -rf coverage && CI=true COVERAGE_PHASE=0 npm run test:coverage -- --run >/dev/null 2>&1) || true
  if [[ -f "${ROOT}/frontend/coverage/coverage-summary.json" ]]; then
    FE_PCT="$(node -e "const t=require('${ROOT}/frontend/coverage/coverage-summary.json').total; console.log(t.pct.toFixed(1))")"
  fi
else
  echo "npm not found; skip frontend coverage"
fi

OUT="${METRICS_DIR}/coverage-weekly.json"
"$PY" - <<PY
import json
from pathlib import Path
p=Path("${OUT}")
rows=[]
if p.is_file():
    rows=json.loads(p.read_text())
rows.append({
    "week": "${WEEK}",
    "timestamp": "${STAMP}",
    "backend_pct": float("${BE_PCT}" or 0),
    "backend_covered": int("${BE_COV}" or 0),
    "backend_statements": int("${BE_STM}" or 0),
    "backend_measured_core_pct": float("${BE_CORE_PCT}" or 0),
    "backend_measured_core_covered": int("${BE_CORE_COV}" or 0),
    "backend_measured_core_statements": int("${BE_CORE_STM}" or 0),
    "frontend_pct": float("${FE_PCT}" or 0),
    "pytest_summary": """${TAIL}""".strip(),
})
p.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
print("Wrote", p)
PY

echo "BACKEND_FULL=${BE_PCT}% BACKEND_MEASURED_CORE=${BE_CORE_PCT}% FRONTEND_FULL=${FE_PCT}%"
echo "Append to docs/reports/COVERAGE_RAMP.md weekly table:"
echo "| ${WEEK} | full ${BE_PCT}% / core ${BE_CORE_PCT}% | frontend ${FE_PCT}% | ${TAIL} |"
