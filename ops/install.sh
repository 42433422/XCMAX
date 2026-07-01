#!/usr/bin/env bash
# XCMAX 运维工具包一键安装器（在生产服务器上以 root 运行，幂等，可反复执行）。
#
#   cd /root/XCMAX && git pull && bash ops/install.sh
#
# 做五件事：
#   1. 把 ops/ 复制到 /usr/local/xcmax-ops（运行副本与仓库解耦，坏 pull 不影响监控）
#   2. 生成 /etc/xcmax-ops.env（如无），建 state/log/backup 目录
#   3. 写 /etc/cron.d/xcmax-ops：哨兵 */5、夜备 03:30、漂移 06:50
#      + 接通 FHD 拉取式发布链（fhd-auto-update.sh */5，替代手工 scp 热补）
#   4. 清理旧的用户 crontab 里的 fhd-auto-update 行（避免双驱动），装 logrotate
#   5. 自检：告警通道状态 + 发测试告警、哨兵跑一轮、备份 dry-run
#
# 选项：--no-test-alert 不发测试告警；--skip-selftest 跳过全部自检

set -euo pipefail

if [[ "$(id -u)" != "0" ]]; then
  echo "[err] 需要 root（安装 cron.d / 写 /var/lib）" >&2
  exit 1
fi

NO_TEST_ALERT=0
SKIP_SELFTEST=0
for arg in "$@"; do
  case "$arg" in
    --no-test-alert) NO_TEST_ALERT=1 ;;
    --skip-selftest) SKIP_SELFTEST=1 ;;
    *) echo "[err] 未知参数: $arg" >&2; exit 1 ;;
  esac
done

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
INSTALL_DIR="/usr/local/xcmax-ops"
ENV_FILE="/etc/xcmax-ops.env"
CRON_FILE="/etc/cron.d/xcmax-ops"

echo "[1/5] 安装运行副本 → $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
  --exclude 'install.sh' --exclude 'env.example' --exclude 'harden_ssh.sh' \
  "$SRC_DIR/" "$INSTALL_DIR/"
find "$INSTALL_DIR" -name '*.sh' -exec chmod 755 {} +
chmod 755 "$INSTALL_DIR"/lib/notify.py "$INSTALL_DIR"/monitor/xcmax_monitor.py

echo "[2/5] 配置与目录"
if [[ ! -f "$ENV_FILE" ]]; then
  install -m 600 "$SRC_DIR/env.example" "$ENV_FILE"
  echo "  已生成 $ENV_FILE（按需编辑，默认值即为生产现状）"
else
  echo "  $ENV_FILE 已存在，保留"
fi
# shellcheck disable=SC1090
. "$ENV_FILE"
mkdir -p "${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state" \
  "${OPS_LOG_DIR:-/var/log/xcmax-ops}" \
  "${OPS_BACKUP_DIR:-/var/backups/xcmax}/daily"
chmod 700 "${OPS_BACKUP_DIR:-/var/backups/xcmax}"

echo "[3/5] 写 $CRON_FILE"
XCMAX_ROOT_VAL="${OPS_XCMAX_ROOT:-/root/XCMAX}"
AUTOUPDATE_LINE=""
if [[ "${OPS_INSTALL_FHD_AUTOUPDATE:-1}" == "1" ]]; then
  AUTO_SCRIPT="${XCMAX_ROOT_VAL}/FHD/scripts/deploy/fhd-auto-update.sh"
  if [[ -f "$AUTO_SCRIPT" ]]; then
    AUTOUPDATE_LINE="*/5 * * * * root . ${ENV_FILE}; bash ${AUTO_SCRIPT} >> /var/log/fhd-auto-update.log 2>&1"
  else
    echo "  [warn] 未找到 $AUTO_SCRIPT，跳过发布链 cron（git 仓库不在 ${XCMAX_ROOT_VAL}?）"
  fi
fi
{
  echo "# XCMAX 运维 cron —— 由 ops/install.sh 生成，手改会在下次安装时被覆盖"
  echo "SHELL=/bin/bash"
  echo "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  echo ""
  echo "# 哨兵：服务/健康/停摆/错误爆发/备份新鲜度/发布链/证书"
  echo "*/5 * * * * root . ${ENV_FILE}; flock -n /tmp/xcmax-monitor.lock python3 ${INSTALL_DIR}/monitor/xcmax_monitor.py >> ${OPS_LOG_DIR:-/var/log/xcmax-ops}/monitor.log 2>&1"
  echo ""
  echo "# 夜间备份（UTC 19:30 = 北京 03:30）"
  echo "30 19 * * * root . ${ENV_FILE}; bash ${INSTALL_DIR}/backup/xcmax_backup.sh >> ${OPS_LOG_DIR:-/var/log/xcmax-ops}/backup.log 2>&1"
  echo ""
  echo "# 漂移检测（UTC 22:50 = 北京 06:50）"
  echo "50 22 * * * root . ${ENV_FILE}; bash ${INSTALL_DIR}/drift/xcmax_drift_check.sh >> ${OPS_LOG_DIR:-/var/log/xcmax-ops}/drift.log 2>&1"
  if [[ -n "$AUTOUPDATE_LINE" ]]; then
    echo ""
    echo "# FHD 拉取式发布链（CI 推 manifest+tarball → 本机校验/备份/健康门/自动回滚）"
    echo "$AUTOUPDATE_LINE"
  fi
} > "$CRON_FILE"
chmod 644 "$CRON_FILE"

echo "[4/5] 清理旧 crontab 双驱动 + logrotate"
if crontab -l >/dev/null 2>&1; then
  if crontab -l | grep -q 'fhd-auto-update.sh'; then
    mkdir -p /root/cron-backups
    crontab -l > "/root/cron-backups/crontab-$(date +%Y%m%d-%H%M%S).bak"
    crontab -l | grep -v 'fhd-auto-update.sh' | crontab -
    echo "  已从用户 crontab 移除 fhd-auto-update 行（归口 ${CRON_FILE}），原表已备份"
  fi
fi
cat > /etc/logrotate.d/xcmax-ops <<'ROT'
/var/log/xcmax-ops/*.log /var/log/fhd-auto-update.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
ROT

echo "[5/5] 自检"
if [[ "$SKIP_SELFTEST" == "1" ]]; then
  echo "  跳过（--skip-selftest）"
else
  set +e
  echo "  -- 告警通道 --"
  # shellcheck disable=SC1090
  (. "$ENV_FILE"; python3 "$INSTALL_DIR/lib/notify.py" --channel-status)
  if [[ "$NO_TEST_ALERT" != "1" ]]; then
    (. "$ENV_FILE"; python3 "$INSTALL_DIR/lib/notify.py" --self-test) \
      || echo "  [warn] 测试告警未送达——检查 SMTP 配置（见上方通道状态）"
  fi
  echo "  -- 哨兵单轮（不告警）--"
  (. "$ENV_FILE"; python3 "$INSTALL_DIR/monitor/xcmax_monitor.py" --no-alert)
  echo "  -- 备份 dry-run --"
  (. "$ENV_FILE"; bash "$INSTALL_DIR/backup/xcmax_backup.sh" --dry-run)
  set -e
fi

echo ""
echo "安装完成。"
echo "  哨兵日志:   tail -f ${OPS_LOG_DIR:-/var/log/xcmax-ops}/monitor.log"
echo "  手动跑一轮: . ${ENV_FILE}; python3 ${INSTALL_DIR}/monitor/xcmax_monitor.py"
echo "  立即全量备份: . ${ENV_FILE}; bash ${INSTALL_DIR}/backup/xcmax_backup.sh"
echo "  运维手册:   ${XCMAX_ROOT_VAL}/ops/README.md"
