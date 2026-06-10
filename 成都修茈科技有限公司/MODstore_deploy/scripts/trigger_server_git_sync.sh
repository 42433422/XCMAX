#!/usr/bin/env bash
# Mac 审批部署链：merge/push 后立刻让 CVM 拉 main 并重启（供 MODSTORE_SYNC_DEPLOY_BASH 调用）
set -euo pipefail

HOST="${XCMAX_REMOTE_HOST:-119.27.178.147}"
USER="${XCMAX_REMOTE_USER:-root}"
XCMAX_ROOT="${XCMAX_REMOTE_ROOT:-/root/XCMAX}"
BRANCH="${XCMAX_GIT_BRANCH:-main}"
SSH_OPTS=(-o StrictHostKeyChecking=no -o ConnectTimeout=15)

remote_cmd=$(cat <<EOF
set -e
cd '${XCMAX_ROOT}'
git fetch origin '${BRANCH}'
git merge --ff-only 'origin/${BRANCH}'
systemctl restart modstore modstore-scheduler 2>/dev/null || true
curl -sf -m 10 http://127.0.0.1:9999/api/health | head -c 200 || true
EOF
)

if [[ -n "${DEPLOY_SSH_PASSWORD:-}" ]]; then
  expect <<EXPECT_EOF
set timeout 120
spawn ssh ${SSH_OPTS[*]} ${USER}@${HOST} ${remote_cmd}
expect {
  -re "(?i)password:" { send "${DEPLOY_SSH_PASSWORD}\r"; exp_continue }
  eof {}
}
EXPECT_EOF
else
  ssh "${SSH_OPTS[@]}" "${USER}@${HOST}" "${remote_cmd}"
fi
