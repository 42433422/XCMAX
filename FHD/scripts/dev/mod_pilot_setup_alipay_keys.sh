#!/usr/bin/env bash
# 为 Mod 试点生成 RSA2 密钥对，并提示上传沙箱（解除 invalid-signature）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODSTORE_DEPLOY_ROOT="${MODSTORE_DEPLOY_ROOT:-${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy}"
KEYS_DIR="${MODSTORE_DEPLOY_ROOT}/keys"
ENV_FILE="${MODSTORE_DEPLOY_ROOT}/.env"
STAMP="$(date +%Y%m%d%H%M%S)"

log() { printf '[alipay-keys] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[[ -d "${MODSTORE_DEPLOY_ROOT}/modstore_server" ]] || fail "MODstore_deploy 未找到: ${MODSTORE_DEPLOY_ROOT}"
mkdir -p "${KEYS_DIR}"

if [[ -f "${KEYS_DIR}/app_private_key.pem" ]]; then
  cp "${KEYS_DIR}/app_private_key.pem" "${KEYS_DIR}/app_private_key.pem.bak-${STAMP}"
  log "已备份旧私钥 → keys/app_private_key.pem.bak-${STAMP}"
fi
if [[ -f "${KEYS_DIR}/alipay_public_key.pem" ]]; then
  cp "${KEYS_DIR}/alipay_public_key.pem" "${KEYS_DIR}/alipay_public_key.pem.bak-${STAMP}"
fi

log "生成 RSA2048 应用私钥（PKCS#1，python-alipay-sdk 适用）…"
openssl genrsa -out "${KEYS_DIR}/app_private_key.pem" 2048
chmod 600 "${KEYS_DIR}/app_private_key.pem"
openssl rsa -in "${KEYS_DIR}/app_private_key.pem" -pubout -out "${KEYS_DIR}/app_public_key_upload.pem"

APP_PUB_ONE_LINE="$(openssl rsa -in "${KEYS_DIR}/app_private_key.pem" -pubout 2>/dev/null | grep -v 'BEGIN\|END' | tr -d '\n')"

log ""
log "=== 下一步（须人工，约 2 分钟）==="
log "1) 打开 https://open.alipay.com/develop/sandbox/app"
log "2) 进入沙箱应用 → 接口加签方式 → 设置/上传应用公钥"
log "3) 粘贴下方单行公钥（或上传 ${KEYS_DIR}/app_public_key_upload.pem 内容）:"
echo "${APP_PUB_ONE_LINE}"
log ""
log "4) 保存后，在沙箱页复制「支付宝公钥」覆盖:"
log "   ${KEYS_DIR}/alipay_public_key.pem"
log "5) 确认 ${ENV_FILE} 中 ALIPAY_APP_ID 与沙箱页 APPID 一致（当前: $(grep -E '^ALIPAY_APP_ID=' "${ENV_FILE}" 2>/dev/null || echo '未设置')）"
log "6) 重启 MODstore :8788，然后:"
log "   bash ${SCRIPT_DIR}/run_mod_pilot_local.sh"
log "   ${SCRIPT_DIR}/../..//.venv/bin/python ${SCRIPT_DIR}/mod_pilot_verify_alipay.py"
log ""
log "输出 OK: 沙箱网关接受签名 后，再跑 Playwright 03-payment。"
