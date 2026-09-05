#!/usr/bin/env bash
# 全量 Playwright e2e：编排 FastAPI :5000 + Vite :5001，跑 P0 套件（14 用例）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FRONTEND="${FHD_ROOT}/frontend"
PY="${E2E_PYTHON:-${FHD_ROOT}/.venv/bin/python}"
if [[ ! -x "${PY}" ]]; then
  PY="$(command -v python3 || true)"
fi
pick_free_port() {
  "${PY}" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

# An acceptance run must exercise the current checkout.  Default to isolated
# ports instead of silently attaching to a developer server with stale code or
# data.  Explicit reuse remains available for local debugging only.
API_PORT="${E2E_API_PORT:-$(pick_free_port)}"
WEB_PORT="${E2E_WEB_PORT:-$(pick_free_port)}"
while [[ "${WEB_PORT}" == "${API_PORT}" ]]; do
  WEB_PORT="$(pick_free_port)"
done
E2E_REUSE_SERVICES="${E2E_REUSE_SERVICES:-0}"
API_URL="http://127.0.0.1:${API_PORT}"
WEB_URL="http://127.0.0.1:${WEB_PORT}"

log() { printf '[e2e-full] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

BACKEND_PID=""
FRONTEND_PID=""
E2E_DATA_DIR="${E2E_DATA_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/xcagi-e2e.XXXXXX")}"
E2E_LOG_DIR="${E2E_LOG_DIR:-${FRONTEND}/test-results}"
# Playwright clears its outputDir when a run starts.  Keep the live backend log
# beside the isolated database so the test runner cannot delete the evidence
# while the backend is still writing to it.
BACKEND_LOG="${E2E_DATA_DIR}/e2e-backend.log"
mkdir -p "${E2E_DATA_DIR}" "${E2E_LOG_DIR}"

stop_process() {
  local pid="$1"
  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 50); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      wait "${pid}" 2>/dev/null || true
      return 0
    fi
    sleep 0.1
  done
  log "进程 ${pid} 未响应 SIGTERM，发送 SIGKILL"
  kill -KILL "${pid}" 2>/dev/null || true
  wait "${pid}" 2>/dev/null || true
}

cleanup() {
  local code=$?
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    stop_process "${FRONTEND_PID}"
  fi
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    stop_process "${BACKEND_PID}"
  fi
  if [[ "${code}" -ne 0 && -f "${BACKEND_LOG}" ]]; then
    cp "${BACKEND_LOG}" "${E2E_LOG_DIR}/e2e-backend.log" 2>/dev/null || true
    log "后端失败日志尾部（完整日志：${BACKEND_LOG}）"
    tail -n 120 "${BACKEND_LOG}" || true
  fi
  return "${code}"
}
trap cleanup EXIT INT TERM

[[ -x "${PY}" ]] || fail "缺少 ${PY}，请先 make setup"

export LAN_GUARD_ENABLED="${LAN_GUARD_ENABLED:-0}"
export XCAGI_NEURO_INTENT="${XCAGI_NEURO_INTENT:-1}"
export XCAGI_PRODUCT_SKU="${XCAGI_PRODUCT_SKU:-enterprise}"
export VITE_XCAGI_PRODUCT_SKU="${VITE_XCAGI_PRODUCT_SKU:-enterprise}"
export VITE_XCAGI_EDITION="${VITE_XCAGI_EDITION:-full}"
export VITE_XCAGI_PLATFORM_SHELL="0"
export VITE_XCAGI_DEFAULT_PLATFORM_SHELL="0"
export VITE_API_BASE="${API_URL}"
export XCAGI_DESKTOP_MODE="1"
# This gate verifies the local desktop login and ERP paths.  Keep it
# deterministic and offline by exercising the repository's loopback-only demo
# market shim instead of making CI availability depend on xiu-ci.com.
export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-http://127.0.0.1:8765}"
# The P0 suite creates several independent browser contexts, each of which
# establishes its own session.  Authentication rate limiting has dedicated
# middleware tests and would otherwise make this local concurrency gate flaky.
export XCAGI_AUTH_RATE_LIMIT="${XCAGI_AUTH_RATE_LIMIT:-0}"
export XCAGI_MARKET_HTTP_TIMEOUT="${XCAGI_MARKET_HTTP_TIMEOUT:-10}"
export XCAGI_MARKET_HTTP_RETRIES="${XCAGI_MARKET_HTTP_RETRIES:-2}"
export XCAGI_DESKTOP_FAST_START="${XCAGI_DESKTOP_FAST_START:-0}"
export XCAGI_DATA_DIR="${E2E_DATA_DIR}"
unset DATABASE_URL
export PYTHONPATH="${FHD_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

wait_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-60}"
  for _ in $(seq 1 "${attempts}"); do
    if curl --noproxy '*' --connect-timeout 2 --max-time 8 -sf "${url}" >/dev/null 2>&1; then
      log "${label} 就绪: ${url}"
      return 0
    fi
    sleep 1
  done
  fail "${label} 超时未就绪: ${url}"
}

if [[ "${E2E_REUSE_SERVICES}" == "1" ]] && curl --noproxy '*' --connect-timeout 2 --max-time 8 -sf "${API_URL}/api/health" >/dev/null 2>&1; then
  log "复用已有后端 ${API_URL}"
else
  if curl --noproxy '*' --connect-timeout 2 --max-time 8 -sf "${API_URL}/api/health" >/dev/null 2>&1; then
    fail "${API_URL} 已被占用；门禁拒绝复用未知后端（调试时可设置 E2E_REUSE_SERVICES=1）"
  fi
  log "启动 FastAPI ${API_URL} …"
  (
    cd "${FHD_ROOT}/XCAGI"
    exec "${PY}" run.py \
      --desktop \
      --headless \
      --data-dir "${E2E_DATA_DIR}" \
      --port "${API_PORT}" \
      --host 127.0.0.1
  ) >"${BACKEND_LOG}" 2>&1 &
  BACKEND_PID=$!
  wait_http "${API_URL}/api/health" "FastAPI"
fi

if [[ "${E2E_REUSE_SERVICES}" == "1" ]] && curl --noproxy '*' --connect-timeout 2 --max-time 8 -sf "${WEB_URL}/" >/dev/null 2>&1; then
  log "复用已有 Vite ${WEB_URL}"
else
  if curl --noproxy '*' --connect-timeout 2 --max-time 8 -sf "${WEB_URL}/" >/dev/null 2>&1; then
    fail "${WEB_URL} 已被占用；门禁拒绝复用未知前端（调试时可设置 E2E_REUSE_SERVICES=1）"
  fi
  # Build synchronously first so wait_http only needs to wait for preview
  # startup (a few seconds). Previously build:strict ran inside the async
  # subshell, eating the 60s wait_http budget and causing spurious timeouts.
  log "构建前端 (build:strict) ${WEB_URL} …"
  (
    cd "${FRONTEND}"
    npm run build:strict
  )
  log "启动 Vite preview ${WEB_URL} …"
  # Keep the tracked PID on the actual Vite process.  `npm run preview`
  # leaves a child Node process behind on failure and previously made the
  # EXIT trap wait until the GitHub job hit its 30 minute hard timeout.
  (
    cd "${FRONTEND}"
    exec node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port "${WEB_PORT}"
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
export PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-${WEB_URL}}"

export E2E_FULL_STACK="${E2E_FULL_STACK:-1}"
export E2E_USER="${E2E_USER:-xcagi-enterprise-demo}"
export E2E_PASSWORD="${E2E_PASSWORD:-Demo@2026}"
export E2E_ACCOUNT_KIND="${E2E_ACCOUNT_KIND:-enterprise}"

log "验证新账号首次表单登录（ERP fixture 绑定行业之前）…"
npx playwright test --config playwright.fresh-login.config.ts --output test-results/first-login

log "运行 Playwright P0 + 表单登录闭环（E2E_FULL_STACK=${E2E_FULL_STACK}）…"
npx playwright test \
  --output test-results/erp \
  e2e/smoke.spec.ts \
  e2e/desktop-resilience.spec.ts \
  e2e/critical-paths.spec.ts \
  e2e/plan2026-skeleton.spec.ts \
  e2e/login-flow.spec.ts
log "e2e 完成"
