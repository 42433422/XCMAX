#!/usr/bin/env bash
# 四项风险治理交付自检（文档 + 前端结构 + legacy 遥测 + pytest 稳定子集提示）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
FAIL=0

note() { echo "[verify-governance] $*"; }
fail() { echo "[verify-governance] FAIL: $*" >&2; FAIL=1; }

note "== 1. 治理文档 =="
for f in \
  docs/NEW_FEATURE_PLACEMENT.md \
  docs/MIGRATION_REGISTRY.md \
  docs/reports/LEGACY_CLEANUP_TRACKING.md \
  docs/reports/legacy_usage_snapshot.json \
  docs/reports/COVERAGE_RAMP.md
do
  if [[ -f "$f" ]]; then note "  ok $f"; else fail "missing $f"; fi
done

note "== 2. 前端 orphan / legacy pro-mode =="
for bad in \
  frontend/src/views/ApprovalHubView.vue.new \
  frontend/src/components/Sidebar.vue.single \
  frontend/src/router/index.ts.nested \
  frontend/src/legacy/pro-mode
do
  if [[ -e "$bad" ]]; then fail "should be removed: $bad"; else note "  absent $bad"; fi
done
for need in \
  frontend/src/composables/useProMode.ts \
  frontend/src/stores/proMode.ts \
  frontend/src/components/ProMode.vue
do
  if [[ -f "$need" ]]; then note "  ok $need"; else fail "missing $need"; fi
done

note "== 2. 版本锚点 =="
if python3 scripts/dev/verify_version_anchors.py >/dev/null; then
  note "  VERSION.md anchors aligned"
else
  python3 scripts/dev/verify_version_anchors.py || fail "version anchor drift"
fi

note "== 3. CI 门禁配置 =="
if grep -q 'fail_under = 77' pyproject.toml \
  && grep -q 'cov-fail-under=77' .github/workflows/test.yml \
  && grep -q 'cov-fail-under=77' .github/workflows/ci-cd.yml; then
  note "  fail_under 77 aligned (pyproject + test.yml + ci-cd.yml)"
else
  fail "fail_under 77 not aligned in pyproject.toml / test.yml / ci-cd.yml"
fi

PY=""
if [[ -x "${ROOT}/.venv/bin/python" ]] && "${ROOT}/.venv/bin/python" -c "import fastapi" 2>/dev/null; then
  PY="${ROOT}/.venv/bin/python"
elif [[ -x "${ROOT}/.venv-governance/bin/python" ]]; then
  PY="${ROOT}/.venv-governance/bin/python"
elif command -v python3.11 >/dev/null 2>&1; then
  PY=python3.11
elif python3 -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then
  PY=python3
fi

note "== 4. Legacy 遥测预检 =="
bash scripts/dev/legacy_gaps_retire_precheck.sh || fail "legacy_gaps_retire_precheck failed"

note "== 4b. OpenAPI 路由一致性 =="
if [[ -n "${PY:-}" ]] && "$PY" -c "import fastapi" 2>/dev/null; then
  PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}" "$PY" scripts/ci/check_openapi_consistency.py --quiet \
    && note "  ok check_openapi_consistency (error=0)" \
    || fail "check_openapi_consistency failed"
else
  note "  skip OpenAPI check (no Python/fastapi)"
fi

note "== 4c. v10.0 双入口 / shim 守护 =="
if command -v rg >/dev/null 2>&1; then
  DUAL_HITS=$(rg -n "\bget_shipment_app_service\b" app mods tests \
    --glob '!**/__pycache__/**' 2>/dev/null | grep -v '_v2' || true)
else
  DUAL_HITS=$(grep -Rn "\bget_shipment_app_service\b" app mods tests 2>/dev/null \
    | grep -v '_v2' | grep -v __pycache__ || true)
fi
if [[ -n "$DUAL_HITS" ]]; then
  echo "$DUAL_HITS" >&2
  fail "v10: 禁止 get_shipment_app_service（非 _v2）；请用 get_shipment_application_service_core()"
else
  note "  ok 无 bootstrap 双入口 get_shipment_app_service"
fi
V2_COUNT=$(find app/application -name '*_app_service_v2.py' 2>/dev/null | wc -l | tr -d ' ')
if [[ "$V2_COUNT" -lt 23 ]]; then
  fail "CLAIMED_VS_ACTUAL: 期望 ≥23 个 *_app_service_v2.py，实际 ${V2_COUNT}"
else
  note "  ok application/*_app_service_v2.py 已登记（${V2_COUNT} 个，见 docs/CLAIMED_VS_ACTUAL.md）"
fi
if ! grep -qE '_v2.*应用服务实际清单' docs/CLAIMED_VS_ACTUAL.md 2>/dev/null; then
  fail "docs/CLAIMED_VS_ACTUAL.md 缺少「_v2 应用服务实际清单」节"
else
  note "  ok CLAIMED_VS_ACTUAL _v2 清单存在"
fi

note "== 5. Pytest + 覆盖率（需 Python 3.11+ 与依赖） =="
if [[ -z "${PY}" ]]; then
  note "  skip pytest (no Python 3.11+); CI uses 3.11 — push 后见 test.yml backend-test"
elif [[ -n "${PY}" ]]; then
  if ! "$PY" -c "import fastapi" 2>/dev/null; then
    note "  skip pytest (fastapi not installed); CI installs XCAGI/requirements.lock.txt"
  elif [[ "${VERIFY_FULL_PYTEST:-}" == "1" ]]; then
    "$PY" -m pytest tests/ -q \
      --cov=app.neuro_bus --cov=app.middleware --cov=app.fastapi_routes \
      --cov=app.utils.rate_limiter --cov=app.utils.password_hash --cov=app.config \
      --cov=app.infrastructure.auth --cov=app.utils \
      --cov-report=term --cov-fail-under=70 \
      --ignore=tests/test_intent.py \
      && note "  pytest full suite + coverage >= 70%" \
      || fail "pytest full suite or coverage gate failed"
  else
    # v10：CI 已跑全量 pytest；本地默认全量 0 failed，覆盖率门禁见 VERIFY_FULL_PYTEST=1 或 CI
    CI_STABLE_ONLY=1 "$PY" -m pytest tests/ -q --tb=no --ignore=tests/test_intent.py \
      && note "  pytest CI_STABLE_ONLY ok (全量请 omit CI_STABLE_ONLY 或见 test.yml backend-full-pytest)" \
      || fail "pytest CI_STABLE_ONLY failed"
  fi
fi

note "== 6. 前端构建（可选，需 node + frontend/node_modules） =="
if [[ ! -d frontend/node_modules ]]; then
  note "  skip frontend build (no node_modules); CI: test.yml frontend-build job"
elif ! command -v npm >/dev/null 2>&1; then
  note "  skip frontend build (npm not in PATH); CI: test.yml frontend-build job"
else
  (cd frontend && npm run build:generic) && note "  frontend build:generic ok" \
    || fail "frontend build failed"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "[verify-governance] 交付自检未通过" >&2
  exit 1
fi
note "交付自检通过（本地跳项请在 CI 复核）"
