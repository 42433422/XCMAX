#!/usr/bin/env bash
# 权威全量覆盖率快照（与 docs/reports/COVERAGE_RAMP.md 一致）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv-cov/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

echo "=== Backend full app coverage ==="
export COVERAGE_FILE="${ROOT}/.coverage.snapshot"
"$PY" -m pytest tests/ \
  --cov=app \
  --cov-report=xml:"${ROOT}/coverage-full.xml" \
  --cov-report=json:"${ROOT}/coverage.json" \
  --cov-fail-under=0 \
  --ignore=tests/neuro/test_routing_policy.py \
  -q --continue-on-collection-errors \
  "$@" || true

if [[ -f "${ROOT}/coverage-full.xml" ]]; then
  "$PY" "${ROOT}/scripts/coverage_dual_summary.py" \
    --xml "${ROOT}/coverage-full.xml" \
    --json "${ROOT}/coverage.json" \
    --data-file "${COVERAGE_FILE}" \
    --metrics-out "${ROOT}/metrics/coverage-dual-summary.json" \
    --dashboard-out "${ROOT}/../xcmax-pytest-coverage.json"
fi

TOOLS_NODE="${ROOT}/../.tools/node-v22.12.0-darwin-arm64/bin"
if [[ -x "${TOOLS_NODE}/npm" ]]; then
  export PATH="${TOOLS_NODE}:${PATH}"
fi

echo ""
echo "=== Frontend full src coverage ==="
(
  cd "${ROOT}/frontend"
  rm -rf coverage
  # 全量 Vitest + v8 合并报告易触达默认堆上限（见 coverage 阶段 worker OOM）
  export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--max-old-space-size=8192"
  CI=true COVERAGE_PHASE=4 npm run test:coverage -- \
    --exclude 'src/views/views.business.smoke.test.ts' \
    --exclude 'src/app.smoke.test.ts' \
    || true
  if [[ -f coverage/coverage-summary.json ]]; then
    node -e "
const s=require('./coverage/coverage-summary.json').total;
console.log('FRONTEND_FULL_SRC_PCT='+s.pct.toFixed(1)+' covered='+s.covered+' statements='+s.total);
"
  fi
)
