#!/usr/bin/env bash
# 在 Linux 服务器上执行：合并 /tmp/modstore_qq_env.patch 进 MODstore_deploy/.env
# 用法：bash remote-merge-qq-env.sh /root/modstore-git
set -e
REMOTE_BASE="${1:?need REMOTE_BASE e.g. /root/modstore-git}"
FRAG=/tmp/modstore_qq_env.patch
ENV_FILE="$REMOTE_BASE/MODstore_deploy/.env"
test -f "$FRAG"
test -f "$ENV_FILE"
cp "$ENV_FILE" "${ENV_FILE}.bak.qqpush.$(date +%s)"
grep -v -E '^(TASK_ROUTER_QQ_APP_SECRET|TASK_ROUTER_QQ_BOT_TOKEN|EMPLOYEE_INTERVIEW_QQ_APP_SECRET|EMPLOYEE_INTERVIEW_QQ_BOT_TOKEN)=' "$ENV_FILE" > "${ENV_FILE}.new" || true
printf '\n# QQ first-class bots (remote-merge-qq-env.sh %s)\n' "$(date -Iseconds)" >> "${ENV_FILE}.new"
cat "$FRAG" >> "${ENV_FILE}.new"
mv "${ENV_FILE}.new" "$ENV_FILE"
rm -f "$FRAG"
systemctl restart modstore
echo '[ok] .env merged + modstore restarted'
