#!/usr/bin/env bash
# Mod 试点 · 官网服务器（xiu-ci.com）四图，不启动本地栈
# 前置：SSH 到 119.27.178.147 已创建 testuser/modpilot（ModPilot2026!）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export MOD_PILOT_MARKET_URL="${MOD_PILOT_MARKET_URL:-https://xiu-ci.com/market}"
export MOD_PILOT_MARKET_API="${MOD_PILOT_MARKET_API:-https://xiu-ci.com}"
export MOD_PILOT_FHD_URL="${MOD_PILOT_FHD_URL:-https://xiu-ci.com/sandbox}"
export MOD_PILOT_FHD_API="${MOD_PILOT_FHD_API:-https://xiu-ci.com/sandbox}"
export MOD_PILOT_ADMIN_USER="${MOD_PILOT_ADMIN_USER:-testuser}"
export MOD_PILOT_ADMIN_PASSWORD="${MOD_PILOT_ADMIN_PASSWORD:-ModPilot2026!}"
export MOD_PILOT_MERCHANT_USER="${MOD_PILOT_MERCHANT_USER:-modpilot}"
export MOD_PILOT_MERCHANT_PASSWORD="${MOD_PILOT_MERCHANT_PASSWORD:-ModPilot2026!}"

log() { printf '[capture-mod-server] %s\n' "$*"; }

log "目标: ${MOD_PILOT_MARKET_URL} · FHD ${MOD_PILOT_FHD_URL}"
log "步骤 3 走生产支付宝（0.01 元真付）；需在浏览器完成付款或 export MOD_PILOT_ALIPAY_BUYER*"

cd "${FHD_ROOT}/frontend"
npx playwright test e2e/mod-pilot-evidence.spec.ts --project=chromium

bash "${FHD_ROOT}/MODstore/scripts/mod-pilot-checklist.sh" --verify
"${FHD_ROOT}/.venv/bin/python" "${FHD_ROOT}/scripts/observability/sync_m0_evidence_manifest.py"
log "完成 → ${FHD_ROOT}/docs/evidence/mod/01–04.png"
