#!/usr/bin/env bash
# 月度恢复演练：把最新 MODstore 备份真实恢复到临时库并做行数断言。
#
# 默认执行真实恢复：下载最新 dump → 在同一个 Postgres 里建临时库 fhd_drill_*
# → pg_restore → 比对 manifest 行数 → 自动 DROP。任何一步失败都以非零退出，
# 由 cron 日志或外部告警捕获。
#
# 用法:
#   fhd-restore-drill.sh             真实恢复 + 断言
#   fhd-restore-drill.sh --dry-run   只校验 manifest 与 dump 可读性
#
# 环境变量:
#   FHD_COS_BUCKET              默认 xcagi-cvm-backup-sh
#   FHD_COS_REGION              默认 ap-shanghai
#   FHD_MODSTORE_PG_CONTAINER   留空自动探测 modstore 的 postgres 容器
#   FHD_MODSTORE_PG_USER        默认 modstore
#   FHD_DRILL_ROW_TOLERANCE     行数容差，默认 0.05（5%，pg_stat 估算会有轻微偏差）
set -euo pipefail

COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"
PG_CONTAINER="${FHD_MODSTORE_PG_CONTAINER:-}"
PG_USER="${FHD_MODSTORE_PG_USER:-modstore}"
TOLERANCE="${FHD_DRILL_ROW_TOLERANCE:-0.05}"
MODE="full"
[[ "${1:-}" == "--dry-run" ]] && MODE="dry"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { log "ERROR: $*"; exit 1; }

command -v coscmd >/dev/null 2>&1 || fail "coscmd 未安装"
command -v docker >/dev/null 2>&1 || fail "docker 未安装"
command -v python3 >/dev/null 2>&1 || fail "python3 未安装"

log "===== 恢复演练开始（mode=$MODE） ====="

LATEST_MANIFEST=$(coscmd -r "$COS_REGION" -b "$COS_BUCKET" list "manifests/" 2>/dev/null | \
  grep -oE '[0-9]{8}-[0-9]{6}\.json' | sort -r | head -1 | sed 's/\.json//')
[[ -n "$LATEST_MANIFEST" ]] || fail "找不到 manifest"
log "最新备份: $LATEST_MANIFEST"

WORK="$(mktemp -d /tmp/fhd-drill.XXXXXX)"
DRILL_DB=""
PG_READY=0

cleanup() {
  if [[ "$PG_READY" == "1" && -n "$DRILL_DB" ]]; then
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -c \
      "DROP DATABASE IF EXISTS $DRILL_DB" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

coscmd -r "$COS_REGION" -b "$COS_BUCKET" download \
  "manifests/$LATEST_MANIFEST.json" "$WORK/manifest.json" >/dev/null \
  || fail "下载 manifest 失败"

MODSTORE_DUMP=$(python3 - "$WORK/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
x = m.get("modstore") or {}
print(x.get("dump") or "")
PY
)
[[ -n "$MODSTORE_DUMP" ]] || fail "manifest 里没有 modstore 备份，无法演练（检查备份是否跳过）"

DUMP_PATH="postgres/daily/modstore-$LATEST_MANIFEST.dump"
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download "$DUMP_PATH" "$WORK/modstore.dump" >/dev/null \
  || fail "下载 dump 失败: $DUMP_PATH"

if [[ -z "$PG_CONTAINER" ]]; then
  CANDIDATES="$(docker ps --format '{{.Names}}' | grep -Ei 'modstore.*postgres|postgres.*modstore' || true)"
  if [[ -n "$CANDIDATES" && "$(printf '%s\n' "$CANDIDATES" | wc -l | tr -d ' ')" == "1" ]]; then
    PG_CONTAINER="$(printf '%s' "$CANDIDATES")"
  fi
fi
[[ -n "$PG_CONTAINER" ]] || fail "找不到 MODstore Postgres 容器，请设置 FHD_MODSTORE_PG_CONTAINER"

docker exec -i "$PG_CONTAINER" pg_restore --list < "$WORK/modstore.dump" >/dev/null \
  || fail "dump 不可读"

if [[ "$MODE" == "dry" ]]; then
  log "dry-run 通过：manifest 与 dump 均可读"
  log "===== 恢复演练完成 ====="
  exit 0
fi

DRILL_DB="fhd_drill_$(date +%Y%m%d%H%M%S)"
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -c "CREATE DATABASE $DRILL_DB" >/dev/null \
  || fail "创建临时库失败"
PG_READY=1

log "恢复到临时库 $DRILL_DB ..."
docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$DRILL_DB" \
  --no-owner --no-privileges < "$WORK/modstore.dump" >/dev/null 2>&1 || true

TABLE_COUNT=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$DRILL_DB" -Atc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null || echo 0)
[[ "${TABLE_COUNT:-0}" -gt 0 ]] || fail "恢复后 public schema 无表"

log "恢复后表数量: $TABLE_COUNT"

python3 - "$WORK/manifest.json" > "$WORK/counts.txt" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for k, v in ((m.get("modstore") or {}).get("row_counts") or {}).items():
    print(k, int(v))
PY

ASSERTED=0
while read -r TABLE EXPECTED; do
  [[ -n "${TABLE:-}" ]] || continue
  [[ "$TABLE" =~ ^[a-z_][a-z0-9_]*$ ]] || continue
  ACTUAL=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$DRILL_DB" -Atc \
    "SELECT count(*) FROM $TABLE" 2>/dev/null || echo -1)
  [[ "$ACTUAL" != "-1" ]] || fail "恢复库里缺少表 $TABLE"
  if ! awk -v e="$EXPECTED" -v a="$ACTUAL" -v t="$TOLERANCE" 'BEGIN{
      if (e == 0) exit (a == 0 ? 0 : 1);
      d = a - e; if (d < 0) d = -d;
      exit ((d / e) <= t ? 0 : 1)
    }'; then
    fail "行数超出容差: $TABLE 备份=$EXPECTED 恢复=$ACTUAL 容差=$TOLERANCE"
  fi
  log "  断言通过: $TABLE 备份=$EXPECTED 恢复=$ACTUAL"
  ASSERTED=$((ASSERTED + 1))
done < "$WORK/counts.txt"

[[ "$ASSERTED" -gt 0 ]] || fail "manifest 里没有可断言行数，演练视为无效"

log "断言通过 $ASSERTED 张表；临时库将在退出时删除"
log "===== 恢复演练完成 ====="
