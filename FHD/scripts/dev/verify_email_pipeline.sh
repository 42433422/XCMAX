#!/usr/bin/env bash
# 对比本机 :8788 与公网 :9999 邮件配置，可选发一封远程 测试信
set -euo pipefail

LOCAL="${MODSTORE_LOCAL_BASE_URL:-http://127.0.0.1:8788}"
REMOTE="${MODSTORE_REMOTE_BASE_URL:-http://119.27.178.147:9999}"
USER="${MODSTORE_DIGEST_ADMIN_USER:-admin}"
PASS="${MODSTORE_DIGEST_ADMIN_PASSWORD:-admin123}"
TEST_TO="${MODSTORE_EMAIL_TEST_TO:-970882904@qq.com}"
SEND_TEST="${1:-}"

log() { printf '[verify-email] %s\n' "$*"; }

_status() {
  local base="$1"
  local label="$2"
  local tok
  tok="$(curl -sS -m 8 -X POST "${base}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${USER}\",\"password\":\"${PASS}\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)"
  if [[ -z "${tok}" ]]; then
    log "${label}: 登录失败"
    return 1
  fi
  curl -sS -m 8 "${base}/api/admin/email/status" -H "Authorization: Bearer ${tok}"
  echo ""
}

log "本机 MODstore ${LOCAL}"
_status "${LOCAL}" "local" || true
log "公网 MODstore ${REMOTE}"
_status "${REMOTE}" "remote" || true

if [[ "${SEND_TEST}" == "--send-test" ]]; then
  log "公网发测试信 → ${TEST_TO}"
  tok="$(curl -sS -m 8 -X POST "${REMOTE}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${USER}\",\"password\":\"${PASS}\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")"
  curl -sS -m 30 -X POST "${REMOTE}/api/admin/email/test" \
    -H "Authorization: Bearer ${tok}" \
    -H 'Content-Type: application/json' \
    -d "{\"to\":\"${TEST_TO}\"}"
  echo ""
fi
