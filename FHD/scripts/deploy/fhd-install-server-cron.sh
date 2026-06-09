#!/usr/bin/env bash
# 幂等安装 FHD 拉取式自动更新 cron（替换 git_auto_update.sh）。
#
# 在目标服务器上直接运行:
#   bash /opt/fhd-full/scripts/deploy/fhd-install-server-cron.sh
#
# 或从本机经 SSH 远程安装:
#   FHD_INSTALL_VIA_SSH=1 FHD_PUSH_HOST=119.27.178.147 bash scripts/deploy/fhd-install-server-cron.sh
#
# 环境变量:
#   FHD_AUTO_UPDATE_SCRIPT   默认 /opt/fhd-full/scripts/deploy/fhd-auto-update.sh
#   FHD_CRON_SCHEDULE        默认 */5 * * * *
#   FHD_DEPLOY_LOG           默认 /var/log/fhd-auto-update.log
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

if [[ "${FHD_INSTALL_VIA_SSH:-0}" == "1" ]]; then
  HOST="${FHD_PUSH_HOST:-119.27.178.147}"
  USER="${FHD_PUSH_USER:-root}"
  SSH_KEY="${FHD_PUSH_SSH_KEY:-}"
  SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
  if [[ -n "$SSH_KEY" ]]; then
    SSH_OPTS+=(-i "$SSH_KEY")
  fi
  REMOTE="${USER}@${HOST}"
  echo "[info] 经 SSH 在 $REMOTE 安装 cron..."
  # shellcheck disable=SC2029
  ssh "${SSH_OPTS[@]}" "$REMOTE" "FHD_INSTALL_VIA_SSH=0 bash -s" < "$SCRIPT_DIR/fhd-install-server-cron.sh"
  exit $?
fi

AUTO_SCRIPT="${FHD_AUTO_UPDATE_SCRIPT:-/opt/fhd-full/scripts/deploy/fhd-auto-update.sh}"
SCHEDULE="${FHD_CRON_SCHEDULE:-*/5 * * * *}"
LOG="${FHD_DEPLOY_LOG:-/var/log/fhd-auto-update.log}"
LOCK="/tmp/fhd-auto-update.lock"
BACKUP_DIR="/root/cron-backups"
TS="$(date +%Y%m%d-%H%M%S)"

if [[ ! -x "$AUTO_SCRIPT" && ! -f "$AUTO_SCRIPT" ]]; then
  echo "[err] 自动更新脚本不存在: $AUTO_SCRIPT" >&2
  echo "[hint] 先执行一次 fhd-apply-release.sh 或手动复制 scripts/deploy/ 到该路径" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
touch "$LOG"
chmod 644 "$LOG" 2>/dev/null || true

if crontab -l >/dev/null 2>&1; then
  crontab -l > "$BACKUP_DIR/crontab-$TS.bak"
  echo "[ok] 已备份 crontab → $BACKUP_DIR/crontab-$TS.bak"
else
  echo "[info] 当前无 crontab，创建新 crontab"
fi

NEW_CRON="$(
  crontab -l 2>/dev/null | grep -v 'git_auto_update.sh' \
    | grep -v '/source/path/' \
    | grep -v 'fhd-auto-update.sh' \
    | grep -v 'fhd-auto-update.lock' \
    || true
)"
# 锁由 fhd-auto-update.sh 内部 flock 负责；cron 外层勿再 flock 同一 lock 文件（会永远「另一实例运行中」）。
CRON_LINE="${SCHEDULE} ${AUTO_SCRIPT} >> ${LOG} 2>&1"

{
  if [[ -n "$NEW_CRON" ]]; then
    printf '%s\n' "$NEW_CRON"
  fi
  printf '%s\n' "$CRON_LINE"
} | crontab -

echo "[ok] 已安装 FHD 拉取式自动更新 cron:"
echo "     $CRON_LINE"
echo "[ok] 已移除 git_auto_update.sh 与占位 rsync cron（若存在）"
echo "[info] 日志: $LOG"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "[ok] Docker + Compose v2 已就绪（manifest deploy_mode=image 时可走 compose）"
  if ! docker info 2>/dev/null | grep -q 'Username:'; then
    echo "[warn] 未检测到 ghcr.io 登录；compose 模式需: echo \$TOKEN | docker login ghcr.io -u USER --password-stdin"
  fi
else
  echo "[info] 未检测到 Docker Compose v2；当前仅 tarball 模式（deploy_mode=tarball）"
fi
