#!/usr/bin/env bash
# Mod 商家试点 · 本地栈（8788 避开全景仪表盘 :8765）
# SSOT: docs/mod-merchant-pilot.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MODSTORE_PORT="${MODSTORE_PORT:-8788}"
MARKET_PORT="${MARKET_PORT:-5176}"
API_PORT="${API_PORT:-5000}"
MODSTORE_DEPLOY_ROOT="${MODSTORE_DEPLOY_ROOT:-${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy}"

log() { printf '[mod-pilot] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[[ -d "${MODSTORE_DEPLOY_ROOT}/modstore_server" ]] || fail "MODstore_deploy 未找到: ${MODSTORE_DEPLOY_ROOT}"

KEYS_DIR="${MODSTORE_DEPLOY_ROOT}/keys"
export MODSTORE_API_PORT="${MODSTORE_PORT}"
export XCAGI_MARKET_BASE_URL="http://127.0.0.1:${MODSTORE_PORT}"
export MODEL_PAYMENT_BACKEND="${MODEL_PAYMENT_BACKEND:-modstore}"
export PAYMENT_BACKEND="${PAYMENT_BACKEND:-python}"
export PAYMENT_SECRET_KEY="${PAYMENT_SECRET_KEY:-mod-pilot-local-dev-signing-key-do-not-use-in-prod}"
export ALIPAY_APP_PRIVATE_KEY_PATH="${ALIPAY_APP_PRIVATE_KEY_PATH:-${KEYS_DIR}/app_private_key.pem}"
export ALIPAY_ALIPAY_PUBLIC_KEY_PATH="${ALIPAY_ALIPAY_PUBLIC_KEY_PATH:-${KEYS_DIR}/alipay_public_key.pem}"
export ALIPAY_NOTIFY_URL="${ALIPAY_NOTIFY_URL:-http://127.0.0.1:${MODSTORE_PORT}/api/payment/notify/alipay}"
export MODSTORE_EMAIL_DEBUG="${MODSTORE_EMAIL_DEBUG:-1}"

log "MODstore API  → http://127.0.0.1:${MODSTORE_PORT}"
log "Market Vite   → http://127.0.0.1:${MARKET_PORT}"
log "FHD API       → http://127.0.0.1:${API_PORT} (export XCAGI_MARKET_BASE_URL=${XCAGI_MARKET_BASE_URL})"
log "证据目录      → ${FHD_ROOT}/docs/evidence/mod/01–04.png"

if ! curl -sf "http://127.0.0.1:${MODSTORE_PORT}/api/health" >/dev/null 2>&1; then
  log "启动 MODstore uvicorn :${MODSTORE_PORT} …"
  (
    cd "${MODSTORE_DEPLOY_ROOT}"
    PY="${FHD_ROOT}/.venv/bin/python"
    [[ -x "${PY}" ]] || PY="$(command -v python3)"
    export MODSTORE_API_PORT MODSTORE_EMAIL_DEBUG PAYMENT_SECRET_KEY PAYMENT_BACKEND
    export ALIPAY_APP_PRIVATE_KEY_PATH ALIPAY_ALIPAY_PUBLIC_KEY_PATH ALIPAY_NOTIFY_URL
    export PYTHONPATH="${MODSTORE_DEPLOY_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
    exec "${PY}" -m uvicorn modstore_server.app:app --host 127.0.0.1 --port "${MODSTORE_PORT}"
  ) &
  for _ in $(seq 1 40); do
    curl -sf "http://127.0.0.1:${MODSTORE_PORT}/api/health" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -sf "http://127.0.0.1:${MODSTORE_PORT}/api/health" >/dev/null 2>&1 || fail "MODstore 未就绪"
  log "MODstore 就绪"
else
  log "MODstore 已在 :${MODSTORE_PORT} 运行"
fi

if ! curl -sf "http://127.0.0.1:${MARKET_PORT}/" >/dev/null 2>&1; then
  log "启动 market Vite :${MARKET_PORT} …"
  (
    cd "${MODSTORE_DEPLOY_ROOT}/market"
    export VITE_API_PROXY_TARGET="http://127.0.0.1:${MODSTORE_PORT}"
    exec npm run dev -- --host 127.0.0.1 --port "${MARKET_PORT}"
  ) &
  for _ in $(seq 1 30); do
    curl -sf "http://127.0.0.1:${MARKET_PORT}/" >/dev/null 2>&1 && break
    sleep 1
  done
fi

log ""
log "=== 四步 URL（截图后保存至 docs/evidence/mod/）==="
log "  1) http://127.0.0.1:${MARKET_PORT}/admin/database"
log "  2) http://127.0.0.1:${MARKET_PORT}/ai-store  或  http://127.0.0.1:5001/mod-store"
log "  3) http://127.0.0.1:${MARKET_PORT}/wallet  （0.01 元沙箱入账后）"
log "  4) http://127.0.0.1:5001/mod-store  （安装并激活 Mod 后）"
log ""
log "一键截图:"
log "  bash ${SCRIPT_DIR}/capture_mod_pilot_evidence.sh"
