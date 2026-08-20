#!/usr/bin/env bash
# 幂等安装 CVM 临时文件清理 cron（.~tmp~ / .part / .partial）。
#
# 在目标服务器上直接运行:
#   bash /opt/fhd-full/scripts/deploy/fhd-install-temp-cleanup-cron.sh
#
# 或从本机经 SSH 远程安装（自动先上传清理脚本再注册 cron）:
#   FHD_INSTALL_VIA_SSH=1 FHD_PUSH_HOST=119.27.178.147 \
#     bash scripts/deploy/fhd-install-temp-cleanup-cron.sh
#
# 环境变量:
#   FHD_TMP_CLEAN_SCHEDULE   默认 */30 * * * *
#   FHD_TMP_CLEAN_SCRIPT     默认 /opt/fhd-full/scripts/deploy/fhd-clean-temp-files.sh
#   FHD_TMP_CLEAN_LOG        默认 /var/log/fhd-temp-cleanup.log
set -euo pipefail

if [[ "${FHD_INSTALL_VIA_SSH:-0}" == "1" ]]; then
  SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
  HOST="${FHD_PUSH_HOST:-119.27.178.147}"
  USER="${FHD_PUSH_USER:-root}"
  SSH_KEY="${FHD_PUSH_SSH_KEY:-}"
  SSH_OPTS=(-o StrictHostKeyChecking=no)
  if [[ -n "$SSH_KEY" ]]; then
    SSH_OPTS+=(-i "$SSH_KEY")
  fi
  REMOTE="${USER}@${HOST}"
  REMOTE_SCRIPT="${FHD_TMP_CLEAN_SCRIPT:-/opt/fhd-full/scripts/deploy/fhd-clean-temp-files.sh}"
  SCHEDULE="${FHD_TMP_CLEAN_SCHEDULE:-*/30 * * * *}"
  LOG="${FHD_TMP_CLEAN_LOG:-/var/log/fhd-temp-cleanup.log}"
  echo "[info] 经 SSH 在 $REMOTE 上传并安装临时文件清理 cron..."
  # shellcheck disable=SC2029
  ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '$(dirname "$REMOTE_SCRIPT")'"
  scp "${SSH_OPTS[@]}" "$SCRIPT_DIR/fhd-clean-temp-files.sh" "${REMOTE}:${REMOTE_SCRIPT}"
  # 转发自定义配置，远端直接执行本地安装逻辑
  # shellcheck disable=SC2029
  ssh "${SSH_OPTS[@]}" "$REMOTE" \
    "chmod +x '$REMOTE_SCRIPT' && FHD_INSTALL_VIA_SSH=0 FHD_TMP_CLEAN_SCRIPT='$REMOTE_SCRIPT' FHD_TMP_CLEAN_SCHEDULE='$SCHEDULE' FHD_TMP_CLEAN_LOG='$LOG' bash -s" \
    < "$SCRIPT_DIR/fhd-install-temp-cleanup-cron.sh"
  exit $?
fi

CLEAN_SCRIPT="${FHD_TMP_CLEAN_SCRIPT:-/opt/fhd-full/scripts/deploy/fhd-clean-temp-files.sh}"
SCHEDULE="${FHD_TMP_CLEAN_SCHEDULE:-*/30 * * * *}"
LOG="${FHD_TMP_CLEAN_LOG:-/var/log/fhd-temp-cleanup.log}"
BACKUP_DIR="/root/cron-backups"
TS="$(date +%Y%m%d-%H%M%S)"

if [[ ! -x "$CLEAN_SCRIPT" ]]; then
  echo "[err] 清理脚本不存在: $CLEAN_SCRIPT" >&2
  echo "[hint] 请经 SSH 模式安装（自动上传），或先确认脚本已随制品下发到该路径" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
touch "$LOG"
chmod 644 "$LOG" 2>/dev/null || true

if crontab -l >/dev/null 2>&1; then
  crontab -l > "$BACKUP_DIR/crontab-tmpclean-$TS.bak"
  echo "[ok] 已备份 crontab → $BACKUP_DIR/crontab-tmpclean-$TS.bak"
else
  echo "[info] 当前无 crontab，创建新 crontab"
fi

NEW_CRON="$(
  crontab -l 2>/dev/null | grep -v 'fhd-clean-temp-files.sh' || true
)"
CRON_LINE="${SCHEDULE} ${CLEAN_SCRIPT} >> ${LOG} 2>&1"

{
  if [[ -n "$NEW_CRON" ]]; then
    printf '%s\n' "$NEW_CRON"
  fi
  printf '%s\n' "$CRON_LINE"
} | crontab -

echo "[ok] 已安装临时文件清理 cron:"
echo "     $CRON_LINE"
echo "[ok] 已移除旧版本清理 cron（若存在）"
echo "[info] 日志: $LOG"
