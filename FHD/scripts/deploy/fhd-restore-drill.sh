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
# 同快照精确计数必须完全相等；旧估算清单或缺失证据以未核验（退出码 2）结束。
set -euo pipefail

COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"
PG_CONTAINER="${FHD_MODSTORE_PG_CONTAINER:-}"
PG_USER="${FHD_MODSTORE_PG_USER:-modstore}"
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
  local status=$?
  if [[ "$PG_READY" == "1" && -n "$DRILL_DB" ]]; then
    if ! docker exec "$PG_CONTAINER" psql -X -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 -c \
      "DROP DATABASE IF EXISTS $DRILL_DB" >/dev/null; then
      log "ERROR: 恢复演练临时库清理失败: $DRILL_DB"
      status=1
    fi
  fi
  rm -rf "$WORK"
  if [[ "$status" == "0" && "$PG_READY" == "1" ]]; then
    log "===== 恢复演练完成 ====="
  fi
  exit "$status"
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

if python3 - "$WORK/manifest.json" "$WORK/modstore.dump" > "$WORK/counts.txt" <<'PY'
import hashlib, json, re, sys
from pathlib import Path

def unverified(reason):
    print('UNVERIFIED: ' + reason, file=sys.stderr)
    raise SystemExit(2)

data = json.loads(Path(sys.argv[1]).read_text()).get('modstore') or {}
expected_sha = data.get('sha256')
if not isinstance(expected_sha, str) or not re.fullmatch('[a-fA-F0-9]{64}', expected_sha):
    unverified('缺少有效的 dump SHA256，无法绑定备份证据')
with open(sys.argv[2], 'rb') as archive:
    digest = hashlib.sha256()
    for chunk in iter(lambda: archive.read(1024 * 1024), b''):
        digest.update(chunk)
    actual_sha = digest.hexdigest()
if actual_sha != expected_sha.lower():
    raise SystemExit('ERROR: modstore.dump SHA256 不匹配，拒绝恢复')
evidence = data.get('row_count_evidence') or {}
counts = data.get('row_counts')
if (not isinstance(evidence, dict) or evidence.get('status') != 'verified'
        or evidence.get('method') != 'pg_export_snapshot_count_v1'
        or not isinstance(evidence.get('snapshot_id'), str) or not evidence['snapshot_id']
        or evidence.get('schema') != 'public' or evidence.get('missing_tables') != []):
    unverified('缺少同 dump 快照的精确行数证据；不使用旧统计估算做断言')
requested = evidence.get('requested_tables')
if (not isinstance(counts, dict) or not counts or not isinstance(requested, list)
        or any(not isinstance(t, str) for t in requested) or set(requested) != set(counts)
        or any(not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', t)
               or type(n) is not int or n < 0 for t, n in counts.items())):
    unverified('精确行数清单不完整或无效')
for table, count in counts.items():
    print(table, count)
PY
then
  log "dump SHA256 与同快照精确行数证据校验通过"
else
  status=$?
  [[ "$status" == "2" ]] && { log "UNVERIFIED: 恢复演练未核验"; exit 2; }
  fail "备份证据校验失败"
fi

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
  log "dry-run 校验通过：dump SHA256 与可读性通过；实际恢复和行数比对未执行"
  exit 0
fi

DRILL_DB="fhd_drill_$(date +%Y%m%d%H%M%S)"
docker exec "$PG_CONTAINER" psql -X -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DRILL_DB" >/dev/null \
  || fail "创建临时库失败"
PG_READY=1

log "恢复到临时库 $DRILL_DB ..."
docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$DRILL_DB" \
  --exit-on-error --single-transaction --no-owner --no-privileges \
  < "$WORK/modstore.dump" >"$WORK/restore.log" 2>&1 || {
    cat "$WORK/restore.log" >&2
    fail "pg_restore 失败，恢复演练未通过"
  }

TABLE_COUNT=$(docker exec "$PG_CONTAINER" psql -X -U "$PG_USER" -d "$DRILL_DB" -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'") \
  || fail "恢复后表数量查询失败"
[[ "$TABLE_COUNT" =~ ^[0-9]+$ ]] || fail "恢复后表数量无效"
[[ "${TABLE_COUNT:-0}" -gt 0 ]] || fail "恢复后 public schema 无表"

log "恢复后表数量: $TABLE_COUNT"

ASSERTED=0
while read -r TABLE EXPECTED; do
  [[ -n "${TABLE:-}" ]] || continue
  [[ "$TABLE" =~ ^[a-z_][a-z0-9_]*$ ]] || continue
  ACTUAL=$(docker exec "$PG_CONTAINER" psql -X -U "$PG_USER" -d "$DRILL_DB" -v ON_ERROR_STOP=1 -Atc \
    "SELECT count(*) FROM public.\"$TABLE\"") || fail "恢复库表行数查询失败: $TABLE"
  [[ "$ACTUAL" =~ ^[0-9]+$ ]] || fail "恢复库表行数无效: $TABLE"
  if [[ "$ACTUAL" != "$EXPECTED" ]]; then
    fail "同快照精确行数不匹配: $TABLE 备份=$EXPECTED 恢复=$ACTUAL"
  fi
  log "  断言通过: $TABLE 备份=$EXPECTED 恢复=$ACTUAL"
  ASSERTED=$((ASSERTED + 1))
done < "$WORK/counts.txt"

[[ "$ASSERTED" -gt 0 ]] || fail "manifest 里没有可断言行数，演练视为无效"

log "断言通过 $ASSERTED 张表；临时库将在退出时删除"
