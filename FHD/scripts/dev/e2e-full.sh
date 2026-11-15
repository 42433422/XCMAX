#!/usr/bin/env bash
# Playwright 门禁：编排隔离 FastAPI + Vite，验证首次登录及 P0 业务闭环。
set +x
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FRONTEND="${FHD_ROOT}/frontend"
PY="${E2E_PYTHON:-${FHD_ROOT}/.venv/bin/python}"
if [[ ! -x "${PY}" ]]; then
  PY="$(command -v python3 || true)"
fi
# Dotenv files can override database/market routing during application startup.
for config in "${FHD_ROOT}/.env" "${FHD_ROOT}/XCAGI/.env"; do
  [[ ! -e "${config}" ]] || { echo '[e2e-full] Refusing local dotenv configuration' >&2; exit 1; }
done
pick_free_port() {
  "${PY}" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

# An acceptance run must exercise the current checkout.  Default to isolated
# ports instead of silently attaching to a developer server with stale code or
# data. Credentials belong only to the fresh backend created below.
API_PORT="${E2E_API_PORT:-$(pick_free_port)}"
WEB_PORT="${E2E_WEB_PORT:-$(pick_free_port)}"
for port in "${API_PORT}" "${WEB_PORT}"; do
  [[ "${port}" =~ ^[0-9]{1,5}$ ]] && (( 10#${port} > 0 && 10#${port} < 65536 )) || {
    echo '[e2e-full] Invalid loopback port' >&2; exit 1;
  }
done
while [[ "${WEB_PORT}" == "${API_PORT}" ]]; do
  WEB_PORT="$(pick_free_port)"
done
# Never attach test credentials to a caller's existing service or data.
[[ "${E2E_REUSE_SERVICES:-0}" == "0" && -z "${E2E_DATA_DIR:-}" ]] || {
  echo '[e2e-full] Refusing service/data reuse' >&2; exit 1;
}
API_URL="http://127.0.0.1:${API_PORT}"
WEB_URL="http://127.0.0.1:${WEB_PORT}"

log() { printf '[e2e-full] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

MARKET_GUARD_PID=""
BACKEND_PID=""
FRONTEND_PID=""
E2E_DATA_DIR="$(mktemp -d "${TMPDIR:-/tmp}/xcagi-e2e.XXXXXX")"
BACKEND_LOG="${E2E_DATA_DIR}/e2e-backend.log"
export E2E_EVIDENCE_DIR="${RUNNER_TEMP:-${E2E_DATA_DIR}}/xcagi-e2e-evidence"

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
  if [[ -n "${MARKET_GUARD_PID}" ]]; then
    stop_process "${MARKET_GUARD_PID}"
  fi
  # Logs, databases and Playwright DOM snapshots can contain session secrets.
  rm -rf -- "${E2E_DATA_DIR}"
  return "${code}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ -x "${PY}" ]] || fail "缺少 ${PY}，请先 make setup"

export LAN_GUARD_ENABLED="${LAN_GUARD_ENABLED:-0}"
export XCAGI_NEURO_INTENT="${XCAGI_NEURO_INTENT:-1}"
export XCAGI_PRODUCT_SKU="${XCAGI_PRODUCT_SKU:-enterprise}"
export FHD_ETL_CENTER_ENABLED="${FHD_ETL_CENTER_ENABLED:-1}"
export VITE_XCAGI_PRODUCT_SKU="${VITE_XCAGI_PRODUCT_SKU:-enterprise}"
export VITE_XCAGI_EDITION="${VITE_XCAGI_EDITION:-full}"
export VITE_XCAGI_PLATFORM_SHELL="0"
export VITE_XCAGI_DEFAULT_PLATFORM_SHELL="0"
export VITE_API_BASE="${API_URL}"
export XCAGI_DESKTOP_MODE="1"
# This gate verifies the local desktop login and ERP paths.  Keep it
# deterministic and offline by exercising the repository's loopback-only demo
# market shim instead of making CI availability depend on xiu-ci.com.
# Reserve a loopback port without listening, so no existing service can receive
# login requests and the normal offline shim remains the only successful path.
"${PY}" - "${E2E_DATA_DIR}/market-port" <<'PY_GUARD' &
import pathlib, signal, socket, sys
with socket.socket() as guard:
    guard.bind(("127.0.0.1", 0))
    pathlib.Path(sys.argv[1]).write_text(str(guard.getsockname()[1]))
    signal.pause()
PY_GUARD
MARKET_GUARD_PID=$!
for _ in $(seq 1 50); do
  [[ -s "${E2E_DATA_DIR}/market-port" ]] && break
  kill -0 "${MARKET_GUARD_PID}" 2>/dev/null || fail "Market port guard failed"
  sleep 0.1
done
[[ -s "${E2E_DATA_DIR}/market-port" ]] || fail "Market port guard timed out"
export XCAGI_MARKET_BASE_URL="http://127.0.0.1:$(cat "${E2E_DATA_DIR}/market-port")"
export XCAGI_USE_REMOTE_MARKET=0 XCAGI_USE_LOCAL_MARKET=0
export NO_PROXY="127.0.0.1,localhost,::1" no_proxy="127.0.0.1,localhost,::1"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export PLAYWRIGHT_NO_COPY_PROMPT=1
export E2E_FULL_STACK=1 E2E_USER=xcagi-enterprise-demo E2E_ACCOUNT_KIND=enterprise
export E2E_PASSWORD="$("${PY}" -c 'import secrets; print(secrets.token_urlsafe(32))')"
[[ -n "${E2E_PASSWORD}" ]] || fail "Failed to generate isolated credentials"
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  printf '::add-mask::%s\n' "${E2E_PASSWORD}"
fi
export SURFACE_AUDIT_DEMO_USER="${E2E_USER}" SURFACE_AUDIT_DEMO_PASSWORD="${E2E_PASSWORD}"
# The P0 suite creates several independent browser contexts, each of which
# establishes its own session.  Authentication rate limiting has dedicated
# middleware tests and would otherwise make this local concurrency gate flaky.
export XCAGI_AUTH_RATE_LIMIT="${XCAGI_AUTH_RATE_LIMIT:-0}"
export XCAGI_MARKET_HTTP_TIMEOUT="${XCAGI_MARKET_HTTP_TIMEOUT:-10}"
export XCAGI_MARKET_HTTP_RETRIES="${XCAGI_MARKET_HTTP_RETRIES:-2}"
export XCAGI_DESKTOP_FAST_START="${XCAGI_DESKTOP_FAST_START:-0}"
export XCAGI_DATA_DIR="${E2E_DATA_DIR}"
export DATABASE_URL="" VECTOR_DB_URL=""
export XCAGI_DESKTOP_FORCE_LOCAL_DATABASE=1 XCAGI_MOD_ISOLATED_DATABASES=0
unset XCAGI_DESKTOP_DATABASE_URL XCAGI_DESKTOP_VECTOR_DB_URL XCAGI_DESKTOP_KEEP_DATABASE_URL
unset DATABASE_PATH WORKSPACE_ROOT XCAGI_WORKSPACE_ROOT UPLOAD_FOLDER EXCEL_VECTOR_DB_PATH
unset XCAGI_USER_MEMORY_DIR XCAGI_MODS_ROOT XCAGI_MODELS_DIR XCAGI_LOG_DIR
export XCAGI_FORCE_SYNC_TASKS=1 XCAGI_DISABLE_REDIS=1 CACHE_REDIS_URL=""
export CELERY_BROKER_URL="memory://" CELERY_RESULT_BACKEND="cache+memory://"
export PYTHONPATH="${FHD_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

owns_listener() {
  "${PY}" - "$1" "$2" <<'PY_OWNER'
import sys
from urllib.parse import urlparse
import psutil
url = urlparse(sys.argv[2])
try:
    sockets = psutil.Process(int(sys.argv[1])).net_connections(kind="tcp")
    owned = any(c.status == psutil.CONN_LISTEN and c.laddr.ip == "127.0.0.1"
                and c.laddr.port == url.port for c in sockets)
except psutil.Error:
    owned = False
sys.exit(0 if owned else 1)
PY_OWNER
}

wait_http() {
  local url="$1"
  local label="$2"
  local pid="$3"
  local attempts="${4:-60}"
  for _ in $(seq 1 "${attempts}"); do
    { kill -0 "${pid}" && kill -0 "${MARKET_GUARD_PID}"; } 2>/dev/null || fail "Owned service exited"
    if owns_listener "${pid}" "${url}" && curl --noproxy '*' --connect-timeout 2 --max-time 8 -sf "${url}" >/dev/null 2>&1; then
      { kill -0 "${pid}" && kill -0 "${MARKET_GUARD_PID}"; } 2>/dev/null || fail "Owned service exited"
      log "${label} 就绪: ${url}"
      return 0
    fi
    sleep 1
  done
  fail "${label} 超时未就绪: ${url}"
}

if curl --noproxy '*' --connect-timeout 2 --max-time 8 -sf "${API_URL}/api/health" >/dev/null 2>&1; then
  fail "${API_URL} 已被占用；门禁拒绝复用未知后端"
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
wait_http "${API_URL}/api/health" "FastAPI" "${BACKEND_PID}"
if curl --noproxy '*' --connect-timeout 2 --max-time 8 -sf "${WEB_URL}/" >/dev/null 2>&1; then
  fail "${WEB_URL} 已被占用；门禁拒绝复用未知前端"
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
  exec node node_modules/vite/bin/vite.js preview --strictPort --host 127.0.0.1 --port "${WEB_PORT}"
) &
FRONTEND_PID=$!
wait_http "${WEB_URL}/" "Vite" "${FRONTEND_PID}"
cd "${FRONTEND}"
if [[ ! -d node_modules ]] || [[ ! -f node_modules/@playwright/test/package.json ]]; then
  fail "frontend node_modules 不完整，请先在 ${FRONTEND} 执行 npm ci"
fi

log "安装 Playwright Chromium（若已安装则跳过）…"
npx playwright install chromium

export MOD_PILOT_FHD_URL="${WEB_URL}"
export MOD_PILOT_FHD_API="${API_URL}"
export PLAYWRIGHT_BASE_URL="${WEB_URL}"


run_suite() {
  mkdir -p "${E2E_DATA_DIR}/browser-tmp"
  TMPDIR="${E2E_DATA_DIR}/browser-tmp" "${PY}" "${SCRIPT_DIR}/e2e_supervise.py" \
    "${BACKEND_PID}" "${FRONTEND_PID}" "${MARKET_GUARD_PID}" "${API_URL}" "${WEB_URL}" \
    node node_modules/@playwright/test/cli.js "$@"
}
log "验证新账号首次表单登录（ERP fixture 绑定行业之前）…"
run_suite test --config playwright.fresh-login.config.ts --output "${E2E_DATA_DIR}/first-login" \
  >"${E2E_DATA_DIR}/first-login.log" 2>&1 || fail "Isolated first-login tests failed"

log "运行 Playwright P0 + 表单登录闭环（E2E_FULL_STACK=${E2E_FULL_STACK}）…"
run_suite test \
  --output "${E2E_DATA_DIR}/erp" \
  e2e/smoke.spec.ts \
  e2e/desktop-resilience.spec.ts \
  e2e/critical-paths.spec.ts \
  e2e/plan2026-skeleton.spec.ts \
  e2e/login-flow.spec.ts >"${E2E_DATA_DIR}/erp.log" 2>&1 || fail "Isolated ERP tests failed"
log "e2e 完成"
