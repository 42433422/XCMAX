#!/usr/bin/env bash
# Postgres 行级数据保留：按配置表分批删除过期行，然后 VACUUM ANALYZE 回收空间。
#
# 只依赖 Postgres 自带能力，不引入扩展、不改表结构。配置来自
# /etc/fhd/pg-retention.conf，每行格式：
#   table|time_column|retain_days|batch_size
# 以 # 开头的行和空行忽略；表或列不存在时跳过并告警，不会中断其它表。
#
# 用法:
#   fhd-pg-retention.sh            按配置执行删除
#   fhd-pg-retention.sh --dry-run  只统计每个表将删除多少行
#
# 环境变量:
#   FHD_MODSTORE_PG_CONTAINER   留空自动探测
#   FHD_MODSTORE_PG_USER        默认 modstore
#   FHD_MODSTORE_DB             默认 modstore
#   FHD_PG_RETENTION_CONF       默认 /etc/fhd/pg-retention.conf
#   FHD_PG_RETENTION_LOG        默认 /var/log/fhd-pg-retention.log
set -euo pipefail

PG_CONTAINER="${FHD_MODSTORE_PG_CONTAINER:-}"
PG_USER="${FHD_MODSTORE_PG_USER:-modstore}"
PG_DB="${FHD_MODSTORE_DB:-modstore}"
CONF="${FHD_PG_RETENTION_CONF:-/etc/fhd/pg-retention.conf}"
LOG="${FHD_PG_RETENTION_LOG:-/var/log/fhd-pg-retention.log}"
MODE="apply"
[[ "${1:-}" == "--dry-run" ]] && MODE="dry"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
fail() { log "ERROR: $*"; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker 未安装"
[[ -f "$CONF" ]] || fail "配置文件不存在: $CONF"

if [[ -z "$PG_CONTAINER" ]]; then
  CANDIDATES="$(docker ps --format '{{.Names}}' | grep -Ei 'modstore.*postgres|postgres.*modstore' || true)"
  if [[ -n "$CANDIDATES" && "$(printf '%s\n' "$CANDIDATES" | wc -l | tr -d ' ')" == "1" ]]; then
    PG_CONTAINER="$(printf '%s' "$CANDIDATES")"
  fi
fi
[[ -n "$PG_CONTAINER" ]] || fail "找不到 MODstore Postgres 容器，请设置 FHD_MODSTORE_PG_CONTAINER"

psql_db() {
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -Atc "$1"
}

[[ "$(psql_db 'SELECT 1' 2>/dev/null || echo 0)" == "1" ]] || fail "无法连接数据库 $PG_DB"

log "===== 行级保留开始（mode=$MODE db=$PG_DB） ====="
TOTAL_DELETED=0
TOTAL_TABLES=0
FAILED_TABLES=0

while IFS='|' read -r TABLE COLUMN DAYS BATCH; do
  TABLE="$(echo "${TABLE:-}" | xargs)"
  COLUMN="$(echo "${COLUMN:-}" | xargs)"
  DAYS="$(echo "${DAYS:-}" | xargs)"
  BATCH="$(echo "${BATCH:-}" | xargs)"
  [[ -z "$TABLE" || "$TABLE" == \#* ]] && continue

  if ! [[ "$TABLE" =~ ^[a-z_][a-z0-9_]*$ && "$COLUMN" =~ ^[a-z_][a-z0-9_]*$ \
          && "$DAYS" =~ ^[0-9]+$ && "$BATCH" =~ ^[0-9]+$ && "$BATCH" -gt 0 ]]; then
    log "WARN: 配置行非法，已跳过: $TABLE|$COLUMN|$DAYS|$BATCH"
    continue
  fi

  if ! EXISTS=$(psql_db "SELECT to_regclass('public.$TABLE') IS NOT NULL"); then
    log "ERROR: 表存在性查询失败: $TABLE"
    FAILED_TABLES=$((FAILED_TABLES + 1))
    continue
  fi
  if [[ "$EXISTS" != "t" ]]; then
    log "WARN: 表不存在，跳过: $TABLE"
    continue
  fi
  if ! HAS_COL=$(psql_db "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='$TABLE' AND column_name='$COLUMN')"); then
    log "ERROR: 列存在性查询失败: $TABLE.$COLUMN"
    FAILED_TABLES=$((FAILED_TABLES + 1))
    continue
  fi
  if [[ "$HAS_COL" != "t" ]]; then
    log "WARN: 列不存在，跳过: $TABLE.$COLUMN"
    continue
  fi

  TOTAL_TABLES=$((TOTAL_TABLES + 1))
  if [[ "$MODE" == "dry" ]]; then
    if ! PENDING=$(psql_db "SELECT count(*) FROM $TABLE WHERE $COLUMN < now() - interval '$DAYS days'") || ! [[ "$PENDING" =~ ^[0-9]+$ ]]; then
      log "ERROR: 过期行查询失败: $TABLE"
      FAILED_TABLES=$((FAILED_TABLES + 1))
      continue
    fi
    log "  [dry-run] $TABLE.$COLUMN 超过 $DAYS 天: $PENDING 行"
    continue
  fi

  DELETED=0
  TABLE_FAILED=0
  while :; do
    if ! N=$(psql_db "WITH d AS (DELETE FROM $TABLE WHERE ctid IN (SELECT ctid FROM $TABLE WHERE $COLUMN < now() - interval '$DAYS days' LIMIT $BATCH) RETURNING 1) SELECT count(*) FROM d") || ! [[ "$N" =~ ^[0-9]+$ ]]; then
      log "ERROR: 删除失败，停止本表: $TABLE"
      TABLE_FAILED=1
      break
    fi
    DELETED=$((DELETED + N))
    [[ "$N" -lt "$BATCH" ]] && break
  done
  if [[ "$DELETED" -gt 0 ]]; then
    if ! docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -c "VACUUM (ANALYZE) $TABLE" >/dev/null; then
      log "ERROR: VACUUM 失败: $TABLE"
      TABLE_FAILED=1
    fi
  fi
  log "  $TABLE.$COLUMN 删除 $DELETED 行（保留 $DAYS 天）"
  TOTAL_DELETED=$((TOTAL_DELETED + DELETED))
  FAILED_TABLES=$((FAILED_TABLES + TABLE_FAILED))
done < "$CONF"

[[ "$FAILED_TABLES" == "0" ]] || fail "行级保留失败：$FAILED_TABLES 张表异常，已删除 $TOTAL_DELETED 行"
log "===== 行级保留完成：$TOTAL_TABLES 张表，删除 $TOTAL_DELETED 行 ====="
