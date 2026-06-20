#!/usr/bin/env bash
# 模式 A：后端 desktop SQLite :5000 + Vite :5001（与 frontend/.env.development.local 默认一致）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCAGI_DIR="${FHD_ROOT}/XCAGI"
FRONTEND_DIR="${FHD_ROOT}/frontend"

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
  export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-https://xiu-ci.com}"
  MARKET_MODE="官网"
  MARKET_HINT="演示号 xcagi-enterprise-demo 已在 ${XCAGI_MARKET_BASE_URL} 注册"
elif [[ -f "${LOCAL_MARKET_ENV}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${LOCAL_MARKET_ENV}"
  set +a
  export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-http://127.0.0.1:8788}"
  export MODSTORE_LOCAL_BASE_URL="${MODSTORE_LOCAL_BASE_URL:-http://127.0.0.1:8788}"
  MARKET_MODE="本地"
  MARKET_HINT="请先 bash FHD/scripts/dev/run_modstore_daily_local.sh；或 XCAGI_USE_REMOTE_MARKET=1 走官网"
else
  export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-http://127.0.0.1:8788}"
  export MODSTORE_LOCAL_BASE_URL="${MODSTORE_LOCAL_BASE_URL:-http://127.0.0.1:8788}"
  MARKET_MODE="本地"
  MARKET_HINT="请先 run_modstore_daily_local.sh；或 XCAGI_USE_REMOTE_MARKET=1 走官网演示号"
fi

API_PORT=5000
WEB_PORT=5001
ADMIN_PORT=5011
API_BASE="http://127.0.0.1:${API_PORT}"

echo "========================================"
echo "  XCAGI 企业/桌面开发（固定端口）"
echo "  API  ${API_BASE}  ← 须与 VITE_API_BASE 一致"
echo "  Web  http://127.0.0.1:${WEB_PORT}/"
echo "  管理端 http://127.0.0.1:${ADMIN_PORT}/admin/  ← 管理员独立运维台"
echo "  市场 ${XCAGI_MARKET_BASE_URL}（${MARKET_MODE} · ${MARKET_HINT}）"
echo "  企业演示 xcagi-enterprise-demo / Demo@2026（官网 + 本地 shim 均可）"
echo "  企业 mods/ 空（干净通用）；管理端 Mod → ${XCAGI_MODS_ADMIN_RUNTIME}/"
echo "  管理员请打开管理端 URL，勿在企业页 :${WEB_PORT} 登 admin"
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
  curl -fsS --max-time 2 "${API_BASE}/api/health" >/dev/null 2>&1
}

echo "[1/2] 启动后端 desktop → :${API_PORT} ..."
mkdir -p "${XCAGI_DATA_DIR}/data"
(
  cd "${XCAGI_DIR}"
  export XCAGI_DESKTOP_MODE=1
  export XCAGI_MOD_ISOLATED_DATABASES=0
  export XCAGI_DESKTOP_FORCE_LOCAL_DATABASE=1
  export DATABASE_URL=
  export VECTOR_DB_URL=
  # 本地开发：关闭全站/认证限流，避免 HMR 刷新与登录调试触发 429
  export XCAGI_GLOBAL_RATE_LIMIT=0
  export XCAGI_AUTH_RATE_LIMIT=0
  # LLM 请求默认走远程服务器（xiu-ci.com），本地不配 LLM / Java 支付服务
  # 如需本地 MODstore 调试，显式设置 XCAGI_USE_REMOTE_MARKET=0
  export XCAGI_USE_REMOTE_MARKET="${XCAGI_USE_REMOTE_MARKET:-1}"
  exec "${PY}" run_fastapi.py --desktop --headless --host 127.0.0.1 --port "${API_PORT}" --data-dir "${XCAGI_DATA_DIR}"
) &
BACKEND_PID=$!

for _ in $(seq 1 45); do
  if health_ok; then
    echo "[OK] 后端就绪 ${API_BASE}/api/health"
    break
  fi
  sleep 1
done
if ! health_ok; then
  echo "[ERR] 后端未在 45s 内就绪（PID ${BACKEND_PID}）" >&2
  exit 1
fi

if [[ ! -f "${FRONTEND_DIR}/package.json" ]]; then
  echo "[ERR] 未找到 ${FRONTEND_DIR}/package.json" >&2
  exit 1
fi

echo "[2/3] 启动 Vite 企业端 → :${WEB_PORT}（generic 宿主 · 不扫 mods-admin-runtime）..."
echo "      确认 frontend/.env.development.local 中 VITE_API_BASE=${API_BASE}"
(
  cd "${FRONTEND_DIR}"
  exec npm run dev
) &

sleep 2
echo "[3/3] 启动管理端 admin-console → :${ADMIN_PORT}/admin/ ..."
(
  cd "${FHD_ROOT}/admin-console"
  export VITE_API_BASE="${API_BASE}"
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
  echo "[OK] 管理端 http://127.0.0.1:${ADMIN_PORT}/admin/login"
else
  echo "[WARN] :${ADMIN_PORT} 尚未监听，请 cd FHD/admin-console && npm run dev"
fi

echo ""
echo "结束：Ctrl+C 后若仍有残留，再执行 scripts/dev/stop-dev-ports.sh"
wait
