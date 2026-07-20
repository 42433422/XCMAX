#!/usr/bin/env bash
# 在 CVM 上注册 FHD 备份 crontab
#
# 用法（CVM 上执行）：
#   sudo bash fhd-install-backup-cron.sh
set -euo pipefail

CRON_FILE="/etc/cron.d/fhd-backup"
DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"

cat > "$CRON_FILE" <<'EOF'
# FHD CVM 备份 crontab
# 每日 02:00 UTC 全量备份（业务低峰）
0 2 * * * root /opt/fhd-full/scripts/deploy/fhd-backup-daily.sh >> /var/log/fhd-backup.log 2>&1

# 每小时检查 WAL 归档健康（archive_command 由 postgres 自动调用，这里仅做监控）
0 * * * * root /usr/bin/test $(find /var/lib/postgresql/data/pg_wal/archive_status -name '*.ready' 2>/dev/null | wc -l) -lt 100 || echo "WARN: WAL 归档积压" | logger -t fhd-backup

# 每周日 03:00 UTC 跨区复制健康检查
0 3 * * 0 root /opt/fhd-full/scripts/deploy/fhd-backup-cross-region-check.sh >> /var/log/fhd-backup.log 2>&1

# 每月 1 日 04:00 UTC 恢复演练（dry-run，仅验证 manifest + dump 可读）
0 4 1 * * root /opt/fhd-full/scripts/deploy/fhd-restore-drill.sh >> /var/log/fhd-backup.log 2>&1
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

echo "[install] 完成"
