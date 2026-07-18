#!/usr/bin/env bash
# 恢复演练（dry-run）：每月 1 日自动验证最新备份可恢复
#
# 不实际恢复生产，仅下载最新 manifest + dump 校验可读性
set -euo pipefail

COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "===== 恢复演练（dry-run） ====="

# 找到最新的 manifest
LATEST_MANIFEST=$(coscmd -r "$COS_REGION" -b "$COS_BUCKET" list "manifests/" 2>/dev/null | \
  grep -oE '[0-9]{8}-[0-9]{6}\.json' | sort -r | head -1 | sed 's/\.json//')

if [[ -z "$LATEST_MANIFEST" ]]; then
  log "ERROR: 找不到 manifest"
  exit 1
fi

log "最新备份: $LATEST_MANIFEST"

# 调用 dry-run 恢复脚本
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
bash "$SCRIPT_DIR/fhd-restore-from-cos.sh" "$LATEST_MANIFEST" --dry-run

log "===== 演练完成 ====="
