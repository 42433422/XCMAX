#!/usr/bin/env bash
# 安装官网 + market + MODstore 自动更新 cron，并移除 FHD tarball cron。
#
# 用法（服务器 root）:
#   bash /root/成都修茈科技有限公司/MODstore_deploy/scripts/install-site-auto-update-cron.sh
#
# 环境变量:
#   XCMAX_CRON_INTERVAL      默认 */10（每 10 分钟）
#   XCMAX_REMOVE_FHD_CRON    默认 1（移除 fhd-auto-update.sh cron）
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
AUTO_SCRIPT="${XCMAX_AUTO_SCRIPT:-${SCRIPT_DIR}/xcmax-site-auto-update.sh}"
LOG="${XCMAX_DEPLOY_LOG:-/var/log/xcmax-site-auto-update.log}"
INTERVAL="${XCMAX_CRON_INTERVAL:-*/10}"
MARKER="# xcmax-site-auto-update"

if [[ ! -f "$AUTO_SCRIPT" ]]; then
  echo "[err] 未找到: $AUTO_SCRIPT" >&2
  exit 1
fi
chmod +x "$AUTO_SCRIPT"

touch "$LOG"
mkdir -p /var/lib/xcmax-site-auto-update

TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'fhd-auto-update\.sh' | grep -v 'xcmax-site-auto-update' | grep -v "$MARKER" >"$TMP" || true

if [[ "${XCMAX_REMOVE_FHD_CRON:-1}" == "1" ]]; then
  echo "[ok] 已过滤 crontab 中的 fhd-auto-update.sh"
fi

{
  cat "$TMP"
  echo "# ${MARKER}"
  echo "${INTERVAL} * * * * ${AUTO_SCRIPT} >> ${LOG} 2>&1"
} | crontab -

rm -f "$TMP"

echo "[ok] cron 已安装: ${INTERVAL} ${AUTO_SCRIPT}"
echo "[ok] 日志: ${LOG}"
crontab -l | grep -E 'xcmax-site|fhd-auto' || true
