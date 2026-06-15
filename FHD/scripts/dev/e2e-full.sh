#!/usr/bin/env bash
# 全量 Playwright e2e：编排 FastAPI :5000 + Vite :5001，跑 P0 套件（14 用例）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FRONTEND="${FHD_ROOT}/frontend"
PY="${FHD_ROOT}/.venv/bin/python"
API_PORT="${E2E_API_PORT:-5000}"
WEB_PORT="${E2E_WEB_PORT:-5001}"
API_URL="http://127.0.0.1:${API_PORT}"
WEB_URL="http://127.0.0.1:${WEB_PORT}"

log() { printf '[e2e-full] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  local code=$?
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
    wait "${FRONTEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
  return "${code}"
}
trap cleanup EXIT INT TERM

[[ -x "${PY}" ]] || fail "缺少 ${PY}，请先 make setup"

export LAN_GUARD_ENABLED="${LAN_GUARD_ENABLED:-0}"
export XCAGI_NEURO_INTENT="${XCAGI_NEURO_INTENT:-1}"
export XCAGI_PRODUCT_SKU="${XCAGI_PRODUCT_SKU:-personal}"
export VITE_XCAGI_PRODUCT_SKU="${VITE_XCAGI_PRODUCT_SKU:-personal}"
export PYTHONPATH="${FHD_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

wait_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-60}"
  for _ in $(seq 1 "${attempts}"); do
    if curl -sf "${url}" >/dev/null 2>&1; then
      log "${label} 就绪: ${url}"
      return 0
    fi
    sleep 1
  done
  fail "${label} 超时未就绪: ${url}"
}

if curl -sf "${API_URL}/api/health" >/dev/null 2>&1; then
  log "复用已有后端 ${API_URL}"
else
  log "启动 FastAPI ${API_URL} …"
  (
    cd "${FHD_ROOT}/XCAGI"
    exec "${PY}" run.py --port "${API_PORT}" --host 127.0.0.1
  ) &
  BACKEND_PID=$!
  wait_http "${API_URL}/api/health" "FastAPI"
fi

if curl -sf "${WEB_URL}/" >/dev/null 2>&1; then
  log "复用已有 Vite ${WEB_URL}"
else
  log "启动 Vite ${WEB_URL} …"
  (
    cd "${FRONTEND}"
    exec npm run dev -- --host 127.0.0.1 --port "${WEB_PORT}"
  ) &
  FRONTEND_PID=$!
  wait_http "${WEB_URL}/" "Vite"
fi

cd "${FRONTEND}"
if [[ ! -d node_modules ]] || [[ ! -f node_modules/@playwright/test/package.json ]]; then
  fail "frontend node_modules 不完整，请先在 ${FRONTEND} 执行 npm ci"
fi

log "安装 Playwright Chromium（若已安装则跳过）…"
npx playwright install chromium

export MOD_PILOT_FHD_URL="${MOD_PILOT_FHD_URL:-${WEB_URL}}"
export MOD_PILOT_FHD_API="${MOD_PILOT_FHD_API:-${API_URL}}"

export E2E_FULL_STACK="${E2E_FULL_STACK:-1}"
export E2E_USER="${E2E_USER:-admin}"
export E2E_PASSWORD="${E2E_PASSWORD:-admin123}"

log "运行 Playwright P0（test:e2e:p0，E2E_FULL_STACK=${E2E_FULL_STACK}）…"
npm run test:e2e:p0
log "e2e 完成"
