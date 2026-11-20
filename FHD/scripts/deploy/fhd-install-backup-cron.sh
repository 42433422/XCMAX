#!/usr/bin/env bash
# 在 CVM 上注册 FHD 备份 crontab
#
# 用法（CVM 上执行）：
#   sudo bash fhd-install-backup-cron.sh
set -euo pipefail

CRON_FILE="/etc/cron.d/fhd-backup"
DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

cat > "$CRON_FILE" <<'EOF'
# FHD CVM 备份 crontab（服务器时区 UTC，注释同时标注北京时间）
# 每日 17:15 UTC / 北京 01:15 全量备份（避开 02:00-05:00 集成窗口）
15 17 * * * root /opt/fhd-full/scripts/deploy/fhd-backup-daily.sh >> /var/log/fhd-backup.log 2>&1

# 每小时检查 WAL 归档健康（archive_command 由 postgres 自动调用，这里仅做监控）
0 * * * * root /usr/bin/test $(find /var/lib/postgresql/data/pg_wal/archive_status -name '*.ready' 2>/dev/null | wc -l) -lt 100 || echo "WARN: WAL 归档积压" | logger -t fhd-backup

# 每周日 14:00 UTC / 周日 22:00 跨区复制健康检查
0 14 * * 0 root /opt/fhd-full/scripts/deploy/fhd-backup-cross-region-check.sh >> /var/log/fhd-backup.log 2>&1

# 每日 16:15 UTC / 次日 00:15 行级数据保留（分批删除 + VACUUM，配置见 /etc/fhd/pg-retention.conf）
15 16 * * * root /opt/fhd-full/scripts/deploy/fhd-pg-retention.sh >> /var/log/fhd-pg-retention.log 2>&1

# 每月 1 日 13:30 UTC / 21:30 恢复演练（真实恢复到临时库 + 行数断言）
30 13 1 * * root /opt/fhd-full/scripts/deploy/fhd-restore-drill.sh >> /var/log/fhd-backup.log 2>&1
EOF

chmod 644 "$CRON_FILE"
echo "[install] 已注册 $CRON_FILE"
cat "$CRON_FILE"

# 检查 coscmd 是否安装
if ! command -v coscmd &>/dev/null; then
  echo "[install] WARN: coscmd 未安装，请先执行："
  echo "  pip install coscmd"
  echo "  coscmd config -a <SECRET_ID> -s <SECRET_KEY> -b xcagi-cvm-backup-sh -r ap-shanghai"
fi

# 创建备份目录
mkdir -p /var/backups/fhd /var/backups/fhd-pre-restore
chmod 755 /var/backups/fhd /var/backups/fhd-pre-restore

# 首次安装行级保留配置（已存在则不覆盖现场调整）
if [[ ! -f /etc/fhd/pg-retention.conf ]]; then
  install -D -m 0644 "$SCRIPT_DIR/fhd-pg-retention.conf" /etc/fhd/pg-retention.conf
  echo "[install] 已写入 /etc/fhd/pg-retention.conf"
else
  echo "[install] 保留现有 /etc/fhd/pg-retention.conf"
fi

echo "[install] 完成"
