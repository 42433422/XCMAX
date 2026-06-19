#!/usr/bin/env bash
# 幂等安装 NeuroBus NN 路由在线更新 cron。
#
# 在目标服务器上直接运行:
#   bash /opt/fhd-full/scripts/deploy/fhd-install-online-update-cron.sh
#
# 或从本机经 SSH 远程安装:
#   FHD_INSTALL_VIA_SSH=1 FHD_PUSH_HOST=119.27.178.147 bash scripts/deploy/fhd-install-online-update-cron.sh
#
# 环境变量:
#   FHD_DEPLOY_ROOT           默认 /opt/fhd-full
#   FHD_ONLINE_UPDATE_SCRIPT  默认 ${FHD_DEPLOY_ROOT}/scripts/deploy/online_update_daemon.py
#   FHD_CRON_SCHEDULE         默认 */5 * * * *
#   FHD_ONLINE_LOG            默认 /var/log/fhd-online-update.log
#   FHD_PYTHON                默认 ${FHD_DEPLOY_ROOT}/.venv/bin/python（回退 python3）
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
  echo "[info] 经 SSH 在 $REMOTE 安装在线更新 cron..."
  # shellcheck disable=SC2029
  ssh "${SSH_OPTS[@]}" "$REMOTE" "FHD_INSTALL_VIA_SSH=0 bash -s" < "$SCRIPT_DIR/fhd-install-online-update-cron.sh"
  exit $?
fi

DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"
UPDATE_SCRIPT="${FHD_ONLINE_UPDATE_SCRIPT:-${DEPLOY_ROOT}/scripts/deploy/online_update_daemon.py}"
SCHEDULE="${FHD_CRON_SCHEDULE:-*/5 * * * *}"
LOG="${FHD_ONLINE_LOG:-/var/log/fhd-online-update.log}"
LOCK="/tmp/fhd-online-update.lock"
BACKUP_DIR="/root/cron-backups"
TS="$(date +%Y%m%d-%H%M%S)"

# 选择 python
if [[ -x "${DEPLOY_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${FHD_PYTHON:-${DEPLOY_ROOT}/.venv/bin/python}"
else
  PYTHON="${FHD_PYTHON:-python3}"
fi

if [[ ! -f "$UPDATE_SCRIPT" ]]; then
  echo "[err] 在线更新脚本不存在: $UPDATE_SCRIPT" >&2
  echo "[hint] 确认制品已解压到 $DEPLOY_ROOT" >&2
  exit 1
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[err] Python 不可用: $PYTHON" >&2
  exit 1
fi

# 检查 torch 依赖
if ! "$PYTHON" -c "import torch" 2>/dev/null; then
  echo "[warn] torch 未安装，在线更新会跳过（影子模式仍可记录决策）" >&2
  echo "[hint] 在 $DEPLOY_ROOT 执行: pip install torch --index-url https://download.pytorch.org/whl/cpu"
fi

mkdir -p "$BACKUP_DIR"
touch "$LOG"
chmod 644 "$LOG" 2>/dev/null || true

# 备份当前 crontab
if crontab -l >/dev/null 2>&1; then
  crontab -l > "$BACKUP_DIR/crontab-online-$TS.bak"
  echo "[ok] 已备份 crontab → $BACKUP_DIR/crontab-online-$TS.bak"
else
  echo "[info] 当前无 crontab，创建新 crontab"
fi

# 移除旧的在线更新 cron（幂等），保留其他 cron
NEW_CRON="$(
  crontab -l 2>/dev/null \
    | grep -v 'online_update_daemon.py' \
    | grep -v 'fhd-online-update.lock' \
    | grep -v 'fhd-online-update.log' \
    || true
)"

# cron 行：flock 防并发 + 激活 venv + 跑 daemon
CRON_LINE="${SCHEDULE} flock -n ${LOCK} -c 'cd ${DEPLOY_ROOT} && ${PYTHON} ${UPDATE_SCRIPT} --once >> ${LOG} 2>&1'"

{
  if [[ -n "$NEW_CRON" ]]; then
    printf '%s\n' "$NEW_CRON"
  fi
  printf '%s\n' "$CRON_LINE"
} | crontab -

echo "[ok] 已安装 NeuroBus NN 路由在线更新 cron:"
echo "     $CRON_LINE"
echo "[ok] 每 ${SCHEDULE} 自动读取新样本 → 喂 OnlineLearner → 达阈值触发更新"
echo "[info] 日志: $LOG"
echo "[info] 确认影子模式已启用: grep XCAGI_ROUTING_POLICY_ENABLED ${DEPLOY_ROOT}/.env 或环境变量"
