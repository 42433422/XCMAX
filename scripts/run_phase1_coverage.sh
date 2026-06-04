#!/usr/bin/env bash
# 阶段 1 全量覆盖率（权威口径）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export SKIP_INTEGRATION=1
export COVERAGE_FILE="${ROOT}/.coverage.phase1"
PY="${ROOT}/.venv-cov/bin/python"

echo "=== Phase 1 backend full app ==="
"$PY" -m pytest tests/ \
  --cov=app \
  --cov-report=term-missing:skip-covered \
  --cov-report=json:"${ROOT}/coverage-phase1-full.json" \
  --cov-fail-under=0 \
  --ignore=tests/neuro/test_routing_policy.py \
  -q --continue-on-collection-errors

"$PY" - <<'PY'
import json
from pathlib import Path
p = Path("coverage-phase1-full.json")
if p.is_file():
    t = json.loads(p.read_text())["totals"]
    pct = t["percent_covered"]
    print(f"PHASE1_BACKEND={pct:.1f}% ({t['covered_lines']}/{t['num_statements']})")
    print("TARGET=45%")
PY

if command -v npm >/dev/null 2>&1; then
  echo "=== Phase 1 frontend full src ==="
  (cd frontend && rm -rf coverage && CI=true COVERAGE_PHASE=1 npm run test:coverage -- --run) || true
  if [[ -f frontend/coverage/coverage-summary.json ]]; then
    node -e "const t=require('./frontend/coverage/coverage-summary.json').total; console.log('PHASE1_FRONTEND='+t.pct.toFixed(1)+'% TARGET=25%')"
  fi
else
  echo "npm not found; skip frontend"
fi
