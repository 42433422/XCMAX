#!/usr/bin/env bash
# 一键：拉生产 env → 起 MODstore 日更栈（Mac 主跑）
# 用法：bash FHD/scripts/dev/bootstrap_modstore_daily_local.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
MODSTORE="${XCMAX_ROOT}/成都修茈科技有限公司/MODstore_deploy"

log() { printf '[bootstrap-daily] %s\n' "$*"; }

log "1/2 从服务器拉 env（SMTP / 凭证 → gitignore 文件）"
bash "${MODSTORE}/scripts/pull_prod_env_for_local.sh"

log "2/2 启动 MODstore :${MODSTORE_PORT:-8788} 日更栈"
MODSTORE_DAILY_FORCE_RESTART="${MODSTORE_DAILY_FORCE_RESTART:-1}" \
  bash "${SCRIPT_DIR}/run_modstore_daily_local.sh"

log "可选：bash FHD/scripts/dev/trigger_digest_now_local.sh"
