#!/usr/bin/env bash
# 从生产机拉 .env → 本地 .env.production.synced + FHD/XCAGI/.env.smtp.local（均 gitignore）
# 用法：bash MODstore_deploy/scripts/pull_prod_env_for_local.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
XCMAX_ROOT="$(cd "${DEPLOY_ROOT}/../.." && pwd)"
FHD_ROOT="${XCMAX_ROOT}/FHD"
PY="${FHD_ROOT}/.venv/bin/python"

DEPLOY_SSH="${DEPLOY_SSH:-root@119.27.178.147}"
REMOTE_ENV="${MODSTORE_REMOTE_ENV:-/root/XCMAX/成都修茈科技有限公司/MODstore_deploy/.env}"
MODSTORE_PORT="${MODSTORE_PORT:-8788}"
TMP="$(mktemp -t modstore-env-pull.XXXXXX)"

log() { printf '[pull-prod-env] %s\n' "$*"; }
fail() { log "ERROR: $*"; rm -f "$TMP"; exit 1; }

[[ -x "${PY}" ]] || fail "FHD venv 未找到: ${PY}"

log "SSH ${DEPLOY_SSH} → ${REMOTE_ENV}"
if ! ssh -o BatchMode=yes -o ConnectTimeout=20 "${DEPLOY_SSH}" "test -r '${REMOTE_ENV}'"; then
  fail "远程 .env 不可读: ${REMOTE_ENV}"
fi
ssh -o BatchMode=yes -o ConnectTimeout=60 "${DEPLOY_SSH}" "cat '${REMOTE_ENV}'" >"${TMP}"

SYNCED="${DEPLOY_ROOT}/.env.production.synced"
SMTP_LOCAL="${FHD_ROOT}/XCAGI/.env.smtp.local"
export XCMAX_MONOREPO_ROOT="${XCMAX_ROOT}"
"${PY}" "${SCRIPT_DIR}/localize_pulled_prod_env.py" \
  --in "${TMP}" \
  --synced-out "${SYNCED}" \
  --smtp-out "${SMTP_LOCAL}" \
  --local-root "${XCMAX_ROOT}" \
  --port "${MODSTORE_PORT}"

rm -f "${TMP}"
log "完成。重启日更栈: bash FHD/scripts/dev/run_modstore_daily_local.sh"
log "  synced → ${SYNCED}"
log "  smtp   → ${SMTP_LOCAL}"
