#!/usr/bin/env bash
# 发版红线一键验证：任意 step 失败即非零退出（本地与 CI 共用）。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FHD_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"
cd "$FHD_ROOT"

SKIP_DESKTOP="${RELEASE_VERIFY_SKIP_DESKTOP:-0}"
SKIP_E2E="${RELEASE_VERIFY_SKIP_E2E:-0}"
SKIP_PACK="${RELEASE_VERIFY_SKIP_PACK:-0}"

banner() {
  echo ""
  echo "======================================================================"
  echo "  $1"
  echo "======================================================================"
}

run_step() {
  banner "$1"
  shift
  "$@"
}

export PYTHONPATH="${FHD_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
export XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1
export XCAGI_TENANT_STRICT=1

run_step "verify_version_anchors" python3 scripts/dev/verify_version_anchors.py
run_step "check_coverage_ssot" python3 scripts/ci/check_coverage_ssot.py
run_step "coverage_ratchet" python3 scripts/dev/coverage_ratchet.py --check --require-backend --require-frontend
run_step "layer_ratchet" python3 scripts/dev/check_layer_ratchet.py
run_step "ssot_cli gate" python3 scripts/dev/ssot_cli.py gate
run_step "smoke_all" python3 scripts/dev/smoke_all.py
run_step "pytest release_gate" python3 -m pytest tests/release_gate/ -q --tb=short
run_step "pytest (full)" python3 -m pytest tests/ -q --tb=line --cov-fail-under=0

pushd frontend >/dev/null
run_step "frontend eslint" npm run lint
run_step "frontend vitest coverage" npm run test:coverage
run_step "frontend vue-tsc" npm run type-check
run_step "frontend build:strict" npm run build:strict
if [[ "$SKIP_E2E" != "1" ]]; then
  run_step "frontend e2e p0" npm run test:e2e:p0
fi
popd >/dev/null

if [[ "$SKIP_DESKTOP" != "1" ]]; then
  pushd desktop >/dev/null
  run_step "desktop tsc build" npm run build
  popd >/dev/null
fi

if [[ "$SKIP_PACK" != "1" ]]; then
  run_step "pack-verify" bash scripts/deploy/fhd-pack-release.sh
fi

banner "release_verify OK"
