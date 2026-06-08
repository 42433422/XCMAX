#!/usr/bin/env bash
# Mod 商家试点 · 一键启动栈 + 前置数据 + Playwright 四图 → docs/evidence/mod/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MODSTORE_DEPLOY_ROOT="${MODSTORE_DEPLOY_ROOT:-${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy}"
MODSTORE_PORT="${MODSTORE_PORT:-8788}"
MARKET_PORT="${MARKET_PORT:-5176}"
API_PORT="${API_PORT:-5000}"
WEB_PORT="${WEB_PORT:-5001}"

export MODSTORE_DEPLOY_ROOT MODSTORE_PORT MARKET_PORT
MOD_PILOT_USER="${MOD_PILOT_ADMIN_USER:-testuser}"
MOD_PILOT_PASSWORD="${MOD_PILOT_ADMIN_PASSWORD:-ModPilot2026!}"
export MOD_PILOT_USER MOD_PILOT_PASSWORD
export MOD_PILOT_ADMIN_USER="${MOD_PILOT_ADMIN_USER:-testuser}"
export MOD_PILOT_ADMIN_PASSWORD="${MOD_PILOT_ADMIN_PASSWORD:-ModPilot2026!}"
export MOD_PILOT_MERCHANT_USER="${MOD_PILOT_MERCHANT_USER:-modpilot}"
export MOD_PILOT_MERCHANT_PASSWORD="${MOD_PILOT_MERCHANT_PASSWORD:-ModPilot2026!}"
export MOD_PILOT_MARKET_URL="http://127.0.0.1:${MARKET_PORT}"
export MOD_PILOT_FHD_URL="http://127.0.0.1:${WEB_PORT}"
export MOD_PILOT_FHD_API="http://127.0.0.1:${API_PORT}"
export XCAGI_MARKET_BASE_URL="http://127.0.0.1:${MODSTORE_PORT}"
export MODEL_PAYMENT_BACKEND="${MODEL_PAYMENT_BACKEND:-modstore}"
export PAYMENT_SECRET_KEY="${PAYMENT_SECRET_KEY:-mod-pilot-local-dev-signing-key-do-not-use-in-prod}"
export PAYMENT_BACKEND="${PAYMENT_BACKEND:-python}"

log() { printf '[capture-mod] %s\n' "$*"; }

log "=== 1/4 启动 MODstore + Market ==="
bash "${SCRIPT_DIR}/run_mod_pilot_local.sh"

log "=== 2/4 重启 FHD API（连 :${MODSTORE_PORT}）==="
if lsof -tiTCP:"${API_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  lsof -tiTCP:"${API_PORT}" -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 1
fi
XCAGI_DIR="${FHD_ROOT}/XCAGI"
PY="${FHD_ROOT}/.venv/bin/python"
[[ -x "${PY}" ]] || PY="python3"
(
  cd "${XCAGI_DIR}"
  export XCAGI_DESKTOP_MODE=1
  export XCAGI_MOD_ISOLATED_DATABASES=0
  export XCAGI_DESKTOP_FORCE_LOCAL_DATABASE=1
  export XCAGI_PRODUCT_SKU=enterprise
  export XCAGI_DATA_DIR="${XCAGI_DIR}/data/desktop-dev"
  export XCAGI_MODS_ROOT="${FHD_ROOT}/mods"
  export XCAGI_MARKET_BASE_URL MODEL_PAYMENT_BACKEND
  export NO_PROXY=127.0.0.1,localhost,::1
  export no_proxy=127.0.0.1,localhost,::1
  exec "${PY}" run_fastapi.py --desktop --headless --host 127.0.0.1 --port "${API_PORT}"
) &
for _ in $(seq 1 45); do
  curl -sf "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1 || { log "FHD API 未就绪"; exit 1; }

if ! curl -sf "http://127.0.0.1:${WEB_PORT}/" >/dev/null 2>&1; then
  log "=== 启动 FHD Vite :${WEB_PORT} ==="
  (
    cd "${FHD_ROOT}/frontend"
    exec npm run dev
  ) &
  sleep 5
fi

log "=== 3/4 前置：企业商家 + 管理员 + 支付宝签名校验 ==="
MODSTORE_PORT="${MODSTORE_PORT}" MOD_PILOT_FHD_API="${MOD_PILOT_FHD_API}" \
  NO_PROXY=127.0.0.1,localhost,::1 no_proxy=127.0.0.1,localhost,::1 \
  "${PY}" "${SCRIPT_DIR}/mod_pilot_setup_merchant.py"
if ! MODSTORE_PORT="${MODSTORE_PORT}" "${PY}" "${SCRIPT_DIR}/mod_pilot_verify_alipay.py"; then
  log "BLOCKER: 支付宝沙箱 APPID 与 keys/ 不匹配（invalid-signature）"
  log "  → https://open.alipay.com/develop/sandbox/app 同步 APPID + 密钥到 MODstore_deploy/keys/"
  log "  → 03-payment 真实 0.01 元需修复后再跑 Playwright"
  exit 2
fi

log "=== 4/4 Playwright 截图 ==="
cd "${FHD_ROOT}/frontend"
npx playwright test e2e/mod-pilot-evidence.spec.ts --project=chromium

bash "${FHD_ROOT}/MODstore/scripts/mod-pilot-checklist.sh" --verify
"${PY}" "${FHD_ROOT}/scripts/observability/sync_m0_evidence_manifest.py"
log "完成 → ${FHD_ROOT}/docs/evidence/mod/01–04.png"
