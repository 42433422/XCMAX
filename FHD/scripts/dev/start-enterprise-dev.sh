#!/usr/bin/env bash
# 企业/管理端本地开发四件套（端口 SSOT）：
#   企业 desktop API :5000  + 企业 Vite :5001
#   管理 web API     :42422 + 管理 Vite :5011/admin/
# 管理端不得共用 desktop 进程（desktop 会拒登 admin，见 desktop_admin_gate）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCAGI_DIR="${FHD_ROOT}/XCAGI"
FRONTEND_DIR="${FHD_ROOT}/frontend"

# P1：本机 Clash/系统代理勿拐走 localhost（curl/Vite 子进程）
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/ensure_dev_proxy_bypass.sh"

export XCAGI_PRODUCT_SKU="${XCAGI_PRODUCT_SKU:-enterprise}"
export XCAGI_DATA_DIR="${XCAGI_DATA_DIR:-${XCAGI_DIR}/data/desktop-dev}"
export XCAGI_MODS_ROOT="${XCAGI_MODS_ROOT:-${FHD_ROOT}/mods}"
ADMIN_MODS_RUNTIME="${FHD_ROOT}/mods-admin-runtime"

if [[ ! -d "${ADMIN_MODS_RUNTIME}/xcagi-planner-bridge" ]]; then
  echo "[prep] 同步管理端 Mod 包 → mods-admin-runtime/ ..."
  bash "${SCRIPT_DIR}/sync-admin-mod-runtime.sh"
fi
export XCAGI_MODS_ADMIN_RUNTIME="${XCAGI_MODS_ADMIN_RUNTIME:-${ADMIN_MODS_RUNTIME}}"

# 桌面开发默认走本地 MODstore :8788；演示号已在官网注册，无本地市场时用 XCAGI_USE_REMOTE_MARKET=1
LOCAL_MARKET_ENV="${XCAGI_DIR}/.env.local-market"
if [[ "${XCAGI_USE_REMOTE_MARKET:-0}" == "1" ]]; then
  export XCAGI_USE_REMOTE_MARKET=1
  export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-https://xiu-ci.com}"
  MARKET_MODE="官网"
  MARKET_HINT="演示号 xcagi-enterprise-demo 已在 ${XCAGI_MARKET_BASE_URL} 注册"
elif [[ -f "${LOCAL_MARKET_ENV}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${LOCAL_MARKET_ENV}"
  set +a
  export XCAGI_USE_REMOTE_MARKET=0
  export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-http://127.0.0.1:8788}"
  export MODSTORE_LOCAL_BASE_URL="${MODSTORE_LOCAL_BASE_URL:-http://127.0.0.1:8788}"
  MARKET_MODE="本地"
  MARKET_HINT="请先 bash FHD/scripts/dev/run_modstore_daily_local.sh；或 XCAGI_USE_REMOTE_MARKET=1 走官网"
else
  export XCAGI_USE_REMOTE_MARKET=0
  export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-http://127.0.0.1:8788}"
  export MODSTORE_LOCAL_BASE_URL="${MODSTORE_LOCAL_BASE_URL:-http://127.0.0.1:8788}"
  MARKET_MODE="本地"
  MARKET_HINT="请先 run_modstore_daily_local.sh；或 XCAGI_USE_REMOTE_MARKET=1 走官网演示号"
fi

API_PORT=5000
WEB_PORT=5001
ADMIN_PORT=5011
# 管理端 SSOT：独立网页后端；不得与 desktop :5000 共用
ADMIN_API_PORT="${ADMIN_API_PORT:-42422}"
API_BASE="http://127.0.0.1:${API_PORT}"
ADMIN_API_BASE="http://127.0.0.1:${ADMIN_API_PORT}"

echo "========================================"
echo "  XCAGI 企业/桌面开发（固定端口 SSOT）"
echo "  企业 API  ${API_BASE}  ← desktop · 企业 Vite 用"
echo "  管理 API  ${ADMIN_API_BASE}  ← web · 管理端 Vite 用（禁 desktop）"
echo "  企业端 http://127.0.0.1:${WEB_PORT}/"
echo "  管理端 http://127.0.0.1:${ADMIN_PORT}/admin/  ← 管理员独立运维台"
echo "  市场 ${XCAGI_MARKET_BASE_URL}（${MARKET_MODE} · ${MARKET_HINT}）"
echo "  企业演示 xcagi-enterprise-demo / Demo@2026（官网 + 本地 shim 均可）"
echo "  企业 mods/ 空（干净通用）；管理端 Mod → ${XCAGI_MODS_ADMIN_RUNTIME}/"
echo "  管理员请打开管理端 URL，勿在企业页 :${WEB_PORT} 登 admin"
echo "  代理：NO_PROXY=${NO_PROXY}"
echo "  若浏览器仍 502：Clash Bypass / 系统代理忽略列表加 localhost,127.0.0.1"
echo "========================================"

"${SCRIPT_DIR}/stop-dev-ports.sh"

if [[ -x "${FHD_ROOT}/.venv/bin/python" ]]; then
  PY="${FHD_ROOT}/.venv/bin/python"
elif [[ -x "${XCAGI_DIR}/.venv/bin/python" ]]; then
  PY="${XCAGI_DIR}/.venv/bin/python"
else
  PY="python3"
fi

health_ok() {
  curl --noproxy '*' -fsS --max-time 2 "$1/api/health?lite=1" >/dev/null 2>&1
}

wait_health() {
  local base="$1"
  local label="$2"
  local pid="$3"
  for _ in $(seq 1 60); do
    if health_ok "${base}"; then
      echo "[OK] ${label} 就绪 ${base}/api/health"
      return 0
    fi
    sleep 1
  done
  echo "[ERR] ${label} 未在 60s 内就绪（PID ${pid}）" >&2
  return 1
}

echo "[1/4] 启动企业后端 desktop → :${API_PORT} ..."
mkdir -p "${XCAGI_DATA_DIR}/data"
(
  cd "${XCAGI_DIR}"
  export XCAGI_DESKTOP_MODE=1
  export XCAGI_MOD_ISOLATED_DATABASES=0
  export XCAGI_DESKTOP_FORCE_LOCAL_DATABASE=1
  export DATABASE_URL=
  export VECTOR_DB_URL=
  export XCAGI_GLOBAL_RATE_LIMIT=0
  export XCAGI_AUTH_RATE_LIMIT=0
  export XCAGI_USE_REMOTE_MARKET="${XCAGI_USE_REMOTE_MARKET:-0}"
  exec "${PY}" run_fastapi.py --desktop --headless --host 127.0.0.1 --port "${API_PORT}" --data-dir "${XCAGI_DATA_DIR}"
) &
BACKEND_PID=$!
wait_health "${API_BASE}" "企业 desktop API" "${BACKEND_PID}"

echo "[2/4] 启动管理端后端 web → :${ADMIN_API_PORT}（XCAGI_DESKTOP_MODE=0）..."
mkdir -p "${FHD_ROOT}/.runtime"
echo "${ADMIN_API_PORT}" > "${FHD_ROOT}/.runtime/api.port"
# 同步注册路由，避免 SPA catch-all 对 POST /api/auth/login 返回 405
# 本机无 PostgreSQL 时回退 SQLite（勿把 desktop API 误绑到本端口）
ADMIN_WEB_DATA="${XCAGI_ADMIN_DATA_DIR:-${XCAGI_DIR}/data/admin-web-dev}"
mkdir -p "${ADMIN_WEB_DATA}/data"
admin_pg_ready=0
if command -v pg_isready >/dev/null 2>&1 && pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
  admin_pg_ready=1
elif "${PY}" - <<'PY' >/dev/null 2>&1
import socket
s = socket.create_connection(("127.0.0.1", 5432), timeout=1)
s.close()
PY
then
  admin_pg_ready=1
fi
if [[ "${admin_pg_ready}" != "1" ]]; then
  if [[ ! -f "${ADMIN_WEB_DATA}/data/xcagi.db" && -f "${XCAGI_DATA_DIR}/data/xcagi.db" ]]; then
    cp "${XCAGI_DATA_DIR}/data/xcagi.db" "${ADMIN_WEB_DATA}/data/xcagi.db"
  fi
  export DATABASE_URL="sqlite:///${ADMIN_WEB_DATA}/data/xcagi.db"
  export VECTOR_DB_URL="${DATABASE_URL}"
  export XCAGI_DATA_DIR="${ADMIN_WEB_DATA}"
  echo "[2/4] PostgreSQL 不可达 → 管理 API 使用 SQLite ${DATABASE_URL}"
fi
(
  cd "${FHD_ROOT}"
  export XCAGI_DESKTOP_MODE=0
  export XCAGI_DESKTOP_FAST_START=0
  export FASTAPI_HOST="${XCAGI_ADMIN_HOST:-127.0.0.1}"
  export FASTAPI_PORT="${ADMIN_API_PORT}"
  export XCAGI_API_PORT="${ADMIN_API_PORT}"
  export XCAGI_ALLOW_PORT_FALLBACK=0
  export XCAGI_GLOBAL_RATE_LIMIT="${XCAGI_ADMIN_GLOBAL_RATE_LIMIT:-1}"
  export XCAGI_AUTH_RATE_LIMIT="${XCAGI_ADMIN_AUTH_RATE_LIMIT:-1}"
  export AUDIT_LOG_PATH="${AUDIT_LOG_PATH:-${ADMIN_WEB_DATA}/audit/admin-audit.jsonl}"
  export XCAGI_USE_REMOTE_MARKET="${XCAGI_USE_REMOTE_MARKET:-0}"
  unset XCAGI_DESKTOP_FORCE_LOCAL_DATABASE || true
  unset XCAGI_MOD_ISOLATED_DATABASES || true
  exec "${PY}" run.py
) &
ADMIN_BACKEND_PID=$!
wait_health "${ADMIN_API_BASE}" "管理端 web API" "${ADMIN_BACKEND_PID}"
# health 可能早于登录路由；等到 POST 不再 405
for _ in $(seq 1 60); do
  code="$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 2 \
    -X POST "${ADMIN_API_BASE}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{}' 2>/dev/null || echo 000)"
  if [[ "${code}" != "000" && "${code}" != "405" ]]; then
    echo "[OK] 管理端登录路由就绪（HTTP ${code}）"
    break
  fi
  sleep 1
done

if [[ ! -f "${FRONTEND_DIR}/package.json" ]]; then
  echo "[ERR] 未找到 ${FRONTEND_DIR}/package.json" >&2
  exit 1
fi

echo "[3/4] 启动 Vite 企业端 → :${WEB_PORT}（代理 ${API_BASE}）..."
(
  cd "${FRONTEND_DIR}"
  export VITE_API_BASE="${API_BASE}"
  export VITE_DEV_PORT="${WEB_PORT}"
  exec npm run dev
) &

sleep 2
echo "[4/4] 启动管理端 admin-console → :${ADMIN_PORT}/admin/（代理 ${ADMIN_API_BASE}）..."
(
  cd "${FHD_ROOT}/admin-console"
  export VITE_API_BASE="${ADMIN_API_BASE}"
  export VITE_DEV_PORT="${ADMIN_PORT}"
  exec npm run dev
) &

sleep 3
if lsof -iTCP:"${WEB_PORT}" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  open "http://127.0.0.1:${WEB_PORT}/" 2>/dev/null || true
  echo "[OK] 企业端 http://127.0.0.1:${WEB_PORT}/"
else
  echo "[WARN] :${WEB_PORT} 尚未监听，请查看 npm 输出。"
fi
if lsof -iTCP:"${ADMIN_PORT}" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  open "http://127.0.0.1:${ADMIN_PORT}/admin/login" 2>/dev/null || true
  echo "[OK] 管理端 http://127.0.0.1:${ADMIN_PORT}/admin/login （API ${ADMIN_API_BASE}）"
else
  echo "[WARN] :${ADMIN_PORT} 尚未监听，请 cd FHD/admin-console && npm run dev"
fi

echo ""
echo "结束：Ctrl+C 后若仍有残留，再执行 scripts/dev/stop-dev-ports.sh"
echo "浏览器 502：在 Clash「绕过」或系统代理忽略列表加入 localhost,127.0.0.1,::1"
wait
