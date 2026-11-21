#!/usr/bin/env bash
# CVM 每日全量备份：PostgreSQL + uploads + mods + config → 腾讯云 COS 主 bucket
#
# 由 cron 每日 17:15 UTC（北京 01:15）调用，避开 02:00-05:00 集成窗口
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
# MODstore 独立 compose（PostgreSQL 16）。容器名留空时自动探测；探测不到默认跳过，
# FHD_MODSTORE_REQUIRED=1 时改为硬失败，避免“备份静默少一个库”。
MODSTORE_PG_CONTAINER="${FHD_MODSTORE_PG_CONTAINER:-}"
MODSTORE_PG_USER="${FHD_MODSTORE_PG_USER:-modstore}"
MODSTORE_DB="${FHD_MODSTORE_DB:-modstore}"
MODSTORE_REQUIRED="${FHD_MODSTORE_REQUIRED:-0}"
ROWCOUNT_TABLES="${FHD_BACKUP_ROWCOUNT_TABLES:-llm_call_logs,openapi_call_logs,customer_service_audit_logs,notifications,incident_events,mac_control_tasks}"

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

# ========== 1b. MODstore 主库（独立 compose） ==========
MODSTORE_DUMPED=0
MODSTORE_COUNTS="{}"
MODSTORE_COUNT_EVIDENCE='{"status":"unverified","reason":"no_modstore_dump"}'
if [[ -z "$MODSTORE_PG_CONTAINER" ]]; then
  _candidates="$(docker ps --format '{{.Names}}' | grep -Ei 'modstore.*postgres|postgres.*modstore' || true)"
  if [[ -n "$_candidates" && "$(printf '%s\n' "$_candidates" | wc -l | tr -d ' ')" == "1" ]]; then
    MODSTORE_PG_CONTAINER="$(printf '%s' "$_candidates")"
  fi
fi
if [[ -n "$MODSTORE_PG_CONTAINER" ]] && docker ps --format '{{.Names}}' | grep -qx "$MODSTORE_PG_CONTAINER"; then
  log "  备份 MODstore 库 $MODSTORE_DB（容器 $MODSTORE_PG_CONTAINER）..."
  # PostgreSQL 16: keep the exporting transaction open while pg_dump imports its
  # snapshot. psql's shell output is the archive; SQL evidence goes to stderr.
  # https://www.postgresql.org/docs/16/app-pgdump.html (--snapshot)
  if ! docker exec -i "$MODSTORE_PG_CONTAINER" psql -X -qAt -w \
    -U "$MODSTORE_PG_USER" -d "$MODSTORE_DB" -v ON_ERROR_STOP=1 \
    -v "tables=$ROWCOUNT_TABLES" > modstore.dump 2>modstore-counts.log <<'SQL'
\o /dev/stderr
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL row_security = off;
SELECT pg_export_snapshot() AS backup_snapshot \gset
\setenv PGDATABASE :DBNAME
\setenv PGUSER :USER
\setenv PGHOST :HOST
\setenv PGPORT :PORT
\setenv FHD_DUMP_SNAPSHOT :backup_snapshot
\! pg_dump -w -Fc --snapshot="$FHD_DUMP_SNAPSHOT"
\if :SHELL_ERROR
  \warn pg_dump failed; snapshot evidence is unverified
  SELECT 1 / 0;
\endif
SELECT 'FHD_COUNT_META:' || json_build_object(
  'snapshot_id', :'backup_snapshot', 'schema', 'public',
  'requested_tables', string_to_array(:'tables', ','),
  'server_version_num', current_setting('server_version_num'))::text;
SELECT format(
  'SELECT %L || json_build_object(''table'', %L, ''count'', count(*))::text FROM %I.%I',
  'FHD_COUNT_ROW:', c.relname, n.nspname, c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
  AND c.relname IN (SELECT btrim(t) FROM unnest(string_to_array(:'tables', ',')) AS t)
ORDER BY c.relname
\gexec
COMMIT;
SQL
  then
    cat modstore-counts.log >&2
    log "ERROR: 同快照备份或精确行数取证失败；未核验，不发布 manifest"
    exit 1
  fi
  docker exec -i "$MODSTORE_PG_CONTAINER" pg_restore --list < modstore.dump > /dev/null || {
    log "ERROR: modstore.dump 不可读"
    exit 1
  }
  MODSTORE_DUMPED=1
  _count_report="$(python3 - modstore-counts.log <<'PY'
import json, re, sys
meta, counts = [], {}
for line in open(sys.argv[1]):
    if line.startswith('FHD_COUNT_META:'):
        meta.append(json.loads(line.split(':', 1)[1]))
    elif line.startswith('FHD_COUNT_ROW:'):
        row = json.loads(line.split(':', 1)[1])
        name, count = row['table'], row['count']
        if name in counts or type(count) is not int or count < 0:
            raise SystemExit('invalid or duplicate exact row count')
        counts[name] = count
if len(meta) != 1 or not meta[0].get('snapshot_id'):
    raise SystemExit('snapshot evidence missing; row counts unverified')
evidence = meta[0]
requested = sorted(set(t.strip() for t in evidence['requested_tables']))
evidence.update(method='pg_export_snapshot_count_v1', requested_tables=requested)
missing = sorted(set(requested) - counts.keys())
valid = bool(requested) and all(re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', t) for t in requested)
evidence.update(status='verified' if valid and not missing else 'unverified', missing_tables=missing)
print(json.dumps(counts))
print(json.dumps(evidence))
PY
  )"
  mapfile -t _count_parts <<< "$_count_report"
  MODSTORE_COUNTS="${_count_parts[0]}"
  MODSTORE_COUNT_EVIDENCE="${_count_parts[1]}"
  if [[ "$MODSTORE_COUNT_EVIDENCE" == *'"unverified"'* ]]; then
    log "WARN: 行数取证未核验（配置表缺失或名称无效）；dump 保留，不能判定恢复演练通过"
  fi
else
  if [[ "$MODSTORE_REQUIRED" == "1" ]]; then
    log "ERROR: 未找到 MODstore Postgres 容器（FHD_MODSTORE_PG_CONTAINER='$MODSTORE_PG_CONTAINER'）"
    exit 1
  fi
  log "  WARN: 未找到 MODstore Postgres 容器，跳过 modstore 备份"
fi

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
if [[ "$MODSTORE_DUMPED" == "1" ]]; then
  coscmd_safe upload modstore.dump "postgres/daily/modstore-$DATE_STAMP.dump"
fi
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
  if [[ "$MODSTORE_DUMPED" == "1" ]]; then
    coscmd_safe copy "postgres/daily/modstore-$DATE_STAMP.dump" "postgres/weekly/modstore-$WEEK_STAMP.dump" || true
  fi
fi
# 每月 1 日存到 monthly/
if [[ "$(date +%d)" == "01" ]]; then
  log "  月初，复制到 monthly/$MONTH_STAMP"
  coscmd_safe copy "postgres/daily/xcagi-$DATE_STAMP.dump" "postgres/monthly/xcagi-$MONTH_STAMP.dump" || true
  if [[ "$MODSTORE_DUMPED" == "1" ]]; then
    coscmd_safe copy "postgres/daily/modstore-$DATE_STAMP.dump" "postgres/monthly/modstore-$MONTH_STAMP.dump" || true
  fi
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

MODSTORE_SHA=""
if [[ "$MODSTORE_DUMPED" == "1" && -f modstore.dump ]]; then
  MODSTORE_SHA="$(sha256sum modstore.dump | awk '{print $1}')"
fi

cat > manifest.json <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "date_stamp": "$DATE_STAMP",
  "hostname": "$(hostname)",
  "postgres_databases": ["xcagi"],
  "mod_databases": $MOD_DBS_JSON,
  "modstore": {
    "database": "$MODSTORE_DB",
    "container": "$MODSTORE_PG_CONTAINER",
    "dump": $( [[ "$MODSTORE_DUMPED" == "1" ]] && printf '"modstore.dump"' || printf 'null' ),
    "sha256": $( [[ -n "$MODSTORE_SHA" ]] && printf '"%s"' "$MODSTORE_SHA" || printf 'null' ),
    "row_counts": ${MODSTORE_COUNTS},
    "row_count_evidence": ${MODSTORE_COUNT_EVIDENCE}
  },
  "sha256": {
    "xcagi.dump": "$(sha256sum xcagi.dump | awk '{print $1}')",
    "config.tar.gz": "$(sha256sum config.tar.gz | awk '{print $1}')"
  },
  "cos_bucket": "$COS_BUCKET",
  "cos_region": "$COS_REGION",
  "cos_paths": {
    "postgres": "postgres/daily/xcagi-$DATE_STAMP.dump",
    "modstore": "postgres/daily/modstore-$DATE_STAMP.dump",
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
