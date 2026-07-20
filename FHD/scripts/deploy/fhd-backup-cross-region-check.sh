#!/usr/bin/env bash
# 跨区复制健康检查（COS 主 bucket vs 异地 bucket 对象数差异）
#
# 由 cron 每周日 03:00 UTC 调用
set -euo pipefail

COS_BUCKET_MAIN="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_BUCKET_BACKUP="${FHD_COS_BUCKET_BACKUP:-xcagi-cvm-backup-bj}"
COS_REGION_MAIN="${FHD_COS_REGION:-ap-shanghai}"
COS_REGION_BACKUP="${FHD_COS_REGION_BACKUP:-ap-beijing}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "===== 跨区复制健康检查 ====="
log "主 bucket: $COS_BUCKET_MAIN ($COS_REGION_MAIN)"
log "备 bucket: $COS_BUCKET_BACKUP ($COS_REGION_BACKUP)"

# 取最近 24h 主 bucket 备份数
MAIN_COUNT=$(coscmd -r "$COS_REGION_MAIN" -b "$COS_BUCKET_MAIN" list "postgres/daily/" 2>/dev/null | wc -l || echo 0)
BACKUP_COUNT=$(coscmd -r "$COS_REGION_BACKUP" -b "$COS_BUCKET_BACKUP" list "postgres/daily/" 2>/dev/null | wc -l || echo 0)

log "主 bucket postgres/daily 对象数: $MAIN_COUNT"
log "备 bucket postgres/daily 对象数: $BACKUP_COUNT"

DIFF=$((MAIN_COUNT - BACKUP_COUNT))
if [[ $DIFF -lt 0 ]]; then DIFF=$((-DIFF)); fi

# 允许 5% 以内差异（跨区复制延迟）
THRESHOLD=$((MAIN_COUNT / 20 + 1))
if [[ $DIFF -gt $THRESHOLD ]]; then
  log "ERROR: 跨区复制差异 $DIFF > 阈值 $THRESHOLD"
  exit 1
fi

log "OK: 差异 $DIFF 在阈值 $THRESHOLD 内"
