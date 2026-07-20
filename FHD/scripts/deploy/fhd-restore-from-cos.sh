#!/usr/bin/env bash
# 从 COS 恢复指定日期备份（恢复演练 / 真实恢复）
#
# 用法：
#   bash fhd-restore-from-cos.sh 20260718-020000           # 真实恢复（谨慎）
#   bash fhd-restore-from-cos.sh 20260718-020000 --dry-run # 仅下载 + 校验
#
# 恢复前快照：脚本会先把当前数据库 pg_dump 一份放到 /var/backups/fhd-pre-restore/
#
# 环境变量:
#   FHD_RESTORE_ROOT       默认 /tmp/fhd-restore-$DATE_STAMP
#   FHD_PRE_RESTORE_SNAP   默认 /var/backups/fhd-pre-restore
#   FHD_PG_CONTAINER       默认 fhd-postgres
#   FHD_PG_USER            默认 xcagi
#   FHD_DEPLOY_ROOT        默认 /opt/fhd-full
#   FHD_COS_BUCKET         默认 xcagi-cvm-backup-sh
#   FHD_COS_REGION         默认 ap-shanghai
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <DATE_STAMP> [--dry-run]" >&2
  exit 1
fi

DATE_STAMP="$1"
DRY_RUN=0
[[ "${2:-}" == "--dry-run" ]] && DRY_RUN=1

COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"
RESTORE_ROOT="${FHD_RESTORE_ROOT:-/tmp/fhd-restore-$DATE_STAMP}"
PRE_SNAP="${FHD_PRE_RESTORE_SNAP:-/var/backups/fhd-pre-restore}"
PG_CONTAINER="${FHD_PG_CONTAINER:-fhd-postgres}"
PG_USER="${FHD_PG_USER:-xcagi}"
DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"

mkdir -p "$RESTORE_ROOT" && cd "$RESTORE_ROOT"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ========== 0. 恢复前快照（非 dry-run） ==========
if [[ "$DRY_RUN" == "0" ]]; then
  log "0/7 当前数据库快照 → $PRE_SNAP/pre-restore-$(date +%Y%m%d-%H%M%S).dump"
  mkdir -p "$PRE_SNAP"
  docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -Fc xcagi \
    > "$PRE_SNAP/pre-restore-$(date +%Y%m%d-%H%M%S).dump" || {
    log "ERROR: 预恢复快照失败，终止"
    exit 1
  }
fi

# ========== 1. 下载 manifest ==========
log "1/7 下载 manifest..."
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download "manifests/$DATE_STAMP.json" manifest.json
cat manifest.json

# ========== 2. 下载 PostgreSQL dump ==========
log "2/7 下载 PostgreSQL dump..."
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download \
  "postgres/daily/xcagi-$DATE_STAMP.dump" xcagi.dump

# ========== 3. 校验 sha256 ==========
log "3/7 校验 sha256..."
if ! command -v jq &>/dev/null; then
  log "WARN: jq 未安装，跳过 sha256 校验"
else
  EXPECTED_SHA="$(jq -r '.sha256["xcagi.dump"]' manifest.json)"
  ACTUAL_SHA="$(sha256sum xcagi.dump | awk '{print $1}')"
  if [[ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]]; then
    log "ERROR: SHA256 不匹配 expected=$EXPECTED_SHA actual=$ACTUAL_SHA"
    exit 1
  fi
  log "  sha256 OK: $ACTUAL_SHA"
fi

# ========== 4. 校验 pg_restore 可读性 ==========
log "4/7 校验 dump 可读性..."
docker exec -i "$PG_CONTAINER" pg_restore --list < xcagi.dump > /dev/null || {
  log "ERROR: dump 不可读"
  exit 1
}

if [[ "$DRY_RUN" == "1" ]]; then
  log "===== DRY_RUN 完成：下载与校验均通过，未实际恢复 ====="
  exit 0
fi

# ========== 5. 恢复 PostgreSQL ==========
log "5/7 恢复 PostgreSQL（--clean --if-exists）..."
docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_USER" -d xcagi --clean --if-exists < xcagi.dump || {
  log "ERROR: 恢复失败，预恢复快照位于 $PRE_SNAP"
  exit 1
}

# ========== 6. 恢复 uploads / mods ==========
log "6/7 恢复 uploads / mods..."
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download -r "uploads/daily/$DATE_STAMP/" uploads/ || log "WARN: uploads 下载失败"
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download -r "mods/daily/$DATE_STAMP/" mods/ || log "WARN: mods 下载失败"

if [[ -d uploads ]]; then
  rsync -a --delete uploads/ "$DEPLOY_ROOT/uploads/" || log "WARN: uploads rsync 失败"
fi
if [[ -d mods ]]; then
  rsync -a --delete mods/ "$DEPLOY_ROOT/mods/" || log "WARN: mods rsync 失败"
fi

# ========== 7. 恢复配置（仅警告，不自动覆盖） ==========
log "7/7 配置恢复提示..."
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download "config/daily/$DATE_STAMP.tar.gz" config.tar.gz || true
log "  配置包已下载到 $RESTORE_ROOT/config.tar.gz"
log "  ⚠️  配置不会自动覆盖，请人工 diff 后决定是否应用"

log "===== 恢复完成 $DATE_STAMP ====="
log "⚠️  请手动验证：curl -sf http://localhost:5100/api/health"
log "⚠️  预恢复快照位于 $PRE_SNAP（如需回滚）"
