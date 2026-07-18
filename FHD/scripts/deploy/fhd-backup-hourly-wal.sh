#!/usr/bin/env bash
# PostgreSQL WAL 增量归档 → COS（把 RPO 从 24h 压到 1h）
#
# 由 postgres archive_command 调用：
#   archive_command = '/scripts/fhd-backup-hourly-wal.sh %p'
#
# 在 docker-compose.yml 中为 postgres 配置：
#   command: >
#     postgres
#     -c wal_level=replica
#     -c archive_mode=on
#     -c archive_command='/scripts/fhd-backup-hourly-wal.sh %p'
#     -c archive_timeout=3600
#
# 环境变量:
#   FHD_COS_BUCKET  默认 xcagi-cvm-backup-sh
#   FHD_COS_REGION  默认 ap-shanghai
#   DRY_RUN         1 时仅打印
set -euo pipefail

WAL_FILE="${1:-}"
COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"
DRY_RUN="${DRY_RUN:-0}"

if [[ -z "$WAL_FILE" || ! -f "$WAL_FILE" ]]; then
  echo "[fhd-backup-hourly-wal] ERROR: WAL file not found: $WAL_FILE" >&2
  exit 1
fi

BASENAME="$(basename "$WAL_FILE")"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[fhd-backup-hourly-wal] DRY_RUN upload $WAL_FILE → postgres/wal/$BASENAME"
  exit 0
fi

coscmd -r "$COS_REGION" -b "$COS_BUCKET" upload "$WAL_FILE" "postgres/wal/$BASENAME" 2>&1 | \
  logger -t fhd-backup-wal || {
  echo "[fhd-backup-hourly-wal] ERROR: coscmd upload failed for $WAL_FILE" >&2
  exit 1
}
