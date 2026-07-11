#!/usr/bin/env bash
# 发版红线一键验证：任意 step 失败即非零退出（本地与 CI 共用）。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FHD_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"
cd "$FHD_ROOT"

SKIP_DESKTOP="${RELEASE_VERIFY_SKIP_DESKTOP:-0}"
SKIP_E2E="${RELEASE_VERIFY_SKIP_E2E:-0}"
SKIP_PACK="${RELEASE_VERIFY_SKIP_PACK:-0}"
PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$FHD_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$FHD_ROOT/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  echo "[release_verify] Python 3.11+ required; got: $($PYTHON_BIN --version 2>&1)" >&2
  echo "[release_verify] Create FHD/.venv or set PYTHON=/path/to/python3.11." >&2
  exit 2
fi

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

run_step "verify_version_anchors" "$PYTHON_BIN" scripts/dev/verify_version_anchors.py
run_step "check_coverage_ssot" "$PYTHON_BIN" scripts/ci/check_coverage_ssot.py
run_step "layer_ratchet" "$PYTHON_BIN" scripts/dev/check_layer_ratchet.py
run_step "ssot_cli gate" "$PYTHON_BIN" scripts/dev/ssot_cli.py gate
run_step "werkzeug shim smoke" "$PYTHON_BIN" scripts/dev/smoke_werkzeug_shim.py
run_step "fastapi boot smoke" "$PYTHON_BIN" - <<'PY'
import logging

for name in (
    "app",
    "app.fastapi_app",
    "app.fastapi_routes",
    "app.middleware.error_handler",
    "app.neuro_bus.bus",
    "app.neuro_bus.integrations.fastapi_integration",
    "resources.config.intent_config",
):
    logging.getLogger(name).setLevel(logging.ERROR)

from app.fastapi_app import get_fastapi_app

app = get_fastapi_app()
print(f"[FastAPI boot] OK routes={len(app.routes)}")
PY
run_step "paramfree GET route smoke" "$PYTHON_BIN" scripts/smoke_paramfree_get_routes.py
run_step "pytest release_gate" "$PYTHON_BIN" -m pytest tests/release_gate/ -q --tb=short

pushd frontend >/dev/null
run_step "frontend eslint" npm run lint
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
