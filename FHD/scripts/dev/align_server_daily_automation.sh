#!/usr/bin/env bash
# 将公网 MODstore 与本地「日更迁回 Mac」策略对齐，避免双线（时间轨）重复跑 digest / 员工大会 / release_train bump。
#
# 策略：
#   - 本机 Mac：日更主跑（run_modstore_daily_local.sh · scheduler_running=True）
#   - 公网 CVM：关闭 08:00 digest / 08:15 vibe execute / 08:25 orchestrator 等 cron，仅保留市场/支付/巡检 API
#   - release_train SSOT：从本机 FHD/config/release_train.json 同步到服务器 MODSTORE_RELEASE_TRAIN_JSON
#
# 用法：
#   DEPLOY_SSH_PASSWORD='你的密码' bash FHD/scripts/dev/align_server_daily_automation.sh
#   或先 export DEPLOY_SSH_PASSWORD 再执行
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
HOST="${XCMAX_REMOTE_HOST:-119.27.178.147}"
USER="${DEPLOY_SSH_USER:-root}"
PORT="${DEPLOY_SSH_PORT:-22}"
MODSTORE_ROOT="${MODSTORE_API_ROOT:-/root/XCMAX/成都修茈科技有限公司/MODstore_deploy}"
ENV_FILE="${MODSTORE_ROOT}/.env"
RT_LOCAL="${FHD_ROOT}/config/release_train.json"
TAR_RT="/tmp/release_train_sync_$$.json"

log() { printf '[align-server] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[[ -n "${DEPLOY_SSH_PASSWORD:-${DEPLOY_PW:-}}" ]] || fail "请设置 DEPLOY_SSH_PASSWORD"

if [[ ! -f "${RT_LOCAL}" ]]; then
  fail "本地 release_train 不存在: ${RT_LOCAL}"
fi

cp "${RT_LOCAL}" "${TAR_RT}"
trap 'rm -f "${TAR_RT}"' EXIT

REMOTE_SCRIPT=$(cat <<'REMOTE_EOF'
set -e
MODSTORE_ROOT="__MODSTORE_ROOT__"
ENV_FILE="${MODSTORE_ROOT}/.env"
RT_SERVER="${MODSTORE_ROOT}/../FHD/config/release_train.json"
mkdir -p "$(dirname "${RT_SERVER}")" 2>/dev/null || true
if [[ -f /tmp/release_train_sync.json ]]; then
  cp /tmp/release_train_sync.json "${RT_SERVER}" 2>/dev/null || cp /tmp/release_train_sync.json "${MODSTORE_ROOT}/config/release_train.json"
  echo "[ok] release_train.json synced"
fi
touch "${ENV_FILE}"
upsert() {
  local k="$1" v="$2"
  if grep -q "^${k}=" "${ENV_FILE}" 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" "${ENV_FILE}"
  else
    echo "${k}=${v}" >> "${ENV_FILE}"
  fi
  echo "[ok] ${k}=${v}"
}
upsert MODSTORE_AUTOMATION_PRIMARY local_mac
upsert MODSTORE_AUTOMATION_ROLE server
upsert MODSTORE_DAILY_DIGEST_ENABLED 0
upsert MODSTORE_DAILY_MEETING_ENABLED 0
upsert MODSTORE_DAILY_VIBE_PREP_ENABLED 0
upsert MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED 0
upsert MODSTORE_DAILY_VIBE_EXECUTE_ENABLED 0
upsert MODSTORE_RELEASE_TRAIN_ENABLED 0
upsert MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE off
upsert MODSTORE_RUN_BACKGROUND_JOBS 1
upsert MODSTORE_RELEASE_TRAIN_JSON "${RT_SERVER}"
upsert XCMAX_MONOREPO_ROOT /root/XCMAX
upsert MODSTORE_REPO_ROOT /root/XCMAX
upsert MODSTORE_DEPLOY_HEALTH_URL http://127.0.0.1:9999/api/health
upsert MODSTORE_SURFACE_AUDIT_AUTO_START 0
upsert MODSTORE_SURFACE_AUDIT_PS_ENABLED 0
upsert MODSTORE_INBOX_POLL_ENABLED 0
echo "[info] 公网日更 cron 已关闭；日更主跑在开发者本机（见 MODSTORE_AUTOMATION_PRIMARY）"
if systemctl is-active modstore >/dev/null 2>&1; then
  systemctl restart modstore
  sleep 2
  systemctl is-active modstore
fi
curl -sf -m 5 http://127.0.0.1:9999/api/health | head -c 200 || true
REMOTE_EOF
)
REMOTE_SCRIPT="${REMOTE_SCRIPT//__MODSTORE_ROOT__/${MODSTORE_ROOT}}"

/usr/bin/expect <<EXPECT_EOF
set timeout 120
set pw \$env(DEPLOY_SSH_PASSWORD)
if {![info exists env(DEPLOY_SSH_PASSWORD)]} { set pw \$env(DEPLOY_PW) }
set host "${HOST}"
set user "${USER}"
set port "${PORT}"

proc scp_up {local remote} {
  global pw host user port
  spawn scp -o StrictHostKeyChecking=no -P \$port \$local \${user}@\${host}:\$remote
  expect {
    -re "(?i)password:" { send "\$pw\r"; exp_continue }
    eof {}
  }
  catch wait result
  set exit_code [lindex \$result 3]
  if {\$exit_code != 0} { exit \$exit_code }
}

proc ssh_run {cmd} {
  global pw host user port
  spawn ssh -o StrictHostKeyChecking=no -p \$port \${user}@\${host} \$cmd
  expect {
    -re "(?i)password:" { send "\$pw\r"; exp_continue }
    eof {}
  }
  catch wait result
  exit [lindex \$result 3]
}

scp_up {${TAR_RT}} /tmp/release_train_sync.json
ssh_run {${REMOTE_SCRIPT}}
EXPECT_EOF

log "完成。本机请保持: bash FHD/scripts/dev/run_modstore_daily_local.sh"
log "公网 MODstore 健康: curl -s http://${HOST}:9999/api/health"
