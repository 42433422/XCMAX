#!/usr/bin/env bash
# CVM 每日全量备份：PostgreSQL + uploads + mods + config → 腾讯云 COS 主 bucket
#
# 由 cron 每日 02:00 UTC 调用（业务低峰）
# 跨区复制由 COS 控制台规则自动完成（上海主 → 北京备）
#
# 环境变量:
#   FHD_BACKUP_ROOT        默认 /var/backups/fhd
#   FHD_PG_CONTAINER       默认 fhd-postgres（docker compose 服务名）
#   FHD_PG_USER            默认 xcagi
#   FHD_DEPLOY_ROOT        默认 /opt/fhd-full
#   FHD_COS_BUCKET         默认 xcagi-cvm-backup-sh
#   FHD_COS_REGION         默认 ap-shanghai
#   FHD_BACKUP_LOG         默认 /var/log/fhd-backup.log
#   FHD_BACKUP_RETAIN_DAYS 默认 7（本地保留天数）
#   DRY_RUN                1 时仅打印动作不上传
set -euo pipefail

BACKUP_ROOT="${FHD_BACKUP_ROOT:-/var/backups/fhd}"
DATE_STAMP="$(date +%Y%m%d-%H%M%S)"
WEEK_STAMP="$(date +%Y-W%V)"
MONTH_STAMP="$(date +%Y-%m)"
PG_CONTAINER="${FHD_PG_CONTAINER:-fhd-postgres}"
PG_USER="${FHD_PG_USER:-xcagi}"
DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"
COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"
LOG="${FHD_BACKUP_LOG:-/var/log/fhd-backup.log}"
RETAIN_DAYS="${FHD_BACKUP_RETAIN_DAYS:-7}"
DRY_RUN="${DRY_RUN:-0}"

mkdir -p "$BACKUP_ROOT/$DATE_STAMP"
cd "$BACKUP_ROOT/$DATE_STAMP"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

coscmd_safe() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log "  [DRY_RUN] coscmd $*"
    return 0
  fi
  coscmd "$@"
}

log "===== FHD 每日备份 $DATE_STAMP 开始 ====="

# ========== 1. PostgreSQL 全量 ==========
log "1/6 备份 PostgreSQL..."
if ! docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
  log "ERROR: postgres 容器 $PG_CONTAINER 未运行"
  exit 1
fi

docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -Fc xcagi > xcagi.dump
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -Fc --schema-only xcagi > xcagi-schema.dump

# 备份所有 MOD 独立库
MOD_DBS=()
while IFS= read -r db; do
  [[ -z "$db" ]] && continue
  MOD_DBS+=("$db")
  docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -Fc "$db" > "$db.dump"
done < <(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -Atc \
  "SELECT datname FROM pg_database WHERE datname LIKE 'xcagi_mod_%'" 2>/dev/null || true)

log "  主库 xcagi + ${#MOD_DBS[@]} 个 MOD 库"

# 完整性校验
log "  校验 pg_restore 可读性..."
docker exec -i "$PG_CONTAINER" pg_restore --list < xcagi.dump > /dev/null || {
  log "ERROR: xcagi.dump 不可读"
  exit 1
}

# ========== 2. 用户上传增量 ==========
log "2/6 增量同步 uploads/..."
if [[ -d "$DEPLOY_ROOT/uploads" ]]; then
  rsync -a --link-dest="$BACKUP_ROOT/latest-uploads" \
    "$DEPLOY_ROOT/uploads/" "$BACKUP_ROOT/$DATE_STAMP/uploads/" || log "WARN: uploads rsync 部分失败"
  ln -sfn "$BACKUP_ROOT/$DATE_STAMP/uploads" "$BACKUP_ROOT/latest-uploads"
else
  log "  uploads/ 不存在，跳过"
fi

# ========== 3. MOD 安装包增量 ==========
log "3/6 增量同步 mods/..."
if [[ -d "$DEPLOY_ROOT/mods" ]]; then
  rsync -a --link-dest="$BACKUP_ROOT/latest-mods" \
    "$DEPLOY_ROOT/mods/" "$BACKUP_ROOT/$DATE_STAMP/mods/" || log "WARN: mods rsync 部分失败"
  ln -sfn "$BACKUP_ROOT/$DATE_STAMP/mods" "$BACKUP_ROOT/latest-mods"
else
  log "  mods/ 不存在，跳过"
fi

# ========== 4. 配置 + SSL 证书 ==========
log "4/6 打包配置..."
tar czf config.tar.gz \
  /root/fhd-full.env \
  "$DEPLOY_ROOT/docker-compose.yml" \
  /etc/letsencrypt/ 2>/dev/null || log "WARN: 部分配置文件不存在"

# ========== 5. 上传到 COS ==========
log "5/6 上传 COS（bucket=$COS_BUCKET region=$COS_REGION）..."
coscmd_safe upload xcagi.dump "postgres/daily/xcagi-$DATE_STAMP.dump"
coscmd_safe upload xcagi-schema.dump "postgres/daily/xcagi-schema-$DATE_STAMP.dump"
for db in "${MOD_DBS[@]}"; do
  coscmd_safe upload "$db.dump" "postgres/daily/$db-$DATE_STAMP.dump"
done
coscmd_safe upload config.tar.gz "config/daily/$DATE_STAMP.tar.gz"

if [[ -d uploads ]]; then
  coscmd_safe upload -rs uploads/ "uploads/daily/$DATE_STAMP/" || log "WARN: uploads 上传失败"
fi
if [[ -d mods ]]; then
  coscmd_safe upload -rs mods/ "mods/daily/$DATE_STAMP/" || log "WARN: mods 上传失败"
fi

# 周日全量也存到 weekly/
if [[ "$(date +%u)" == "7" ]]; then
  log "  周日，复制到 weekly/$WEEK_STAMP"
  coscmd_safe copy "postgres/daily/xcagi-$DATE_STAMP.dump" "postgres/weekly/xcagi-$WEEK_STAMP.dump" || true
fi
# 每月 1 日存到 monthly/
if [[ "$(date +%d)" == "01" ]]; then
  log "  月初，复制到 monthly/$MONTH_STAMP"
  coscmd_safe copy "postgres/daily/xcagi-$DATE_STAMP.dump" "postgres/monthly/xcagi-$MONTH_STAMP.dump" || true
fi

# ========== 6. 本地保留 + manifest ==========
log "6/6 清理本地 ${RETAIN_DAYS} 天前备份..."
find "$BACKUP_ROOT" -maxdepth 1 -type d -mtime +"$RETAIN_DAYS" \
  -not -name "latest-*" -not -name "$(basename $BACKUP_ROOT)" \
  -exec rm -rf {} \; 2>/dev/null || true

MOD_DBS_JSON="[]"
if [[ ${#MOD_DBS[@]} -gt 0 ]]; then
  MOD_DBS_JSON="$(printf '%s\n' "${MOD_DBS[@]}" | python3 -c 'import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')"
fi

cat > manifest.json <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "date_stamp": "$DATE_STAMP",
  "hostname": "$(hostname)",
  "postgres_databases": ["xcagi"],
  "mod_databases": $MOD_DBS_JSON,
  "sha256": {
    "xcagi.dump": "$(sha256sum xcagi.dump | awk '{print $1}')",
    "config.tar.gz": "$(sha256sum config.tar.gz | awk '{print $1}')"
  },
  "cos_bucket": "$COS_BUCKET",
  "cos_region": "$COS_REGION",
  "cos_paths": {
    "postgres": "postgres/daily/xcagi-$DATE_STAMP.dump",
    "uploads": "uploads/daily/$DATE_STAMP/",
    "mods": "mods/daily/$DATE_STAMP/",
    "config": "config/daily/$DATE_STAMP.tar.gz"
  },
  "retention": {
    "local_days": $RETAIN_DAYS,
    "weekly_weeks": 4,
    "monthly_months": 12
  }
}
EOF

coscmd_safe upload manifest.json "manifests/$DATE_STAMP.json"

log "===== FHD 每日备份 $DATE_STAMP 完成 ====="
log "Manifest: manifest.json"
log "Size: $(du -sh "$BACKUP_ROOT/$DATE_STAMP" | awk '{print $1}')"
