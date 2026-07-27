#!/usr/bin/env bash
# 将接收端 latest 只读归档恢复到温备运行库。
# 先完整恢复到 *_next，再停本机 API 并切换库名；保留一代 *_previous 便于回退。

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
ARCHIVE="${OPS_DR_ARCHIVE:-$DR_ROOT/archive}"
STATE="${OPS_DR_STATE:-/var/lib/xcmax-dr}"
LOG="${OPS_DR_RESTORE_LOG:-/var/log/xcmax-dr/restore.log}"
PG_CONTAINER="${OPS_DR_PG_CONTAINER:-xcmax-dr-postgres}"
LOCK="/run/lock/xcmax-dr-restore.lock"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

mkdir -p "$STATE" "$(dirname "$LOG")"
touch "$LOG"
chmod 700 "$STATE" "$(dirname "$LOG")"

exec 9>"$LOCK"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

latest="$(readlink -f "$ARCHIVE/latest" 2>/dev/null || true)"
[[ -n "$latest" && "$latest" == "$ARCHIVE"/[0-9]*-* && -d "$latest" ]] || {
  log "没有可恢复的 latest 归档"
  exit 1
}
snapshot="$(basename "$latest")"
if [[ "$FORCE" != "1" && -f "$STATE/last_restored_snapshot" ]] &&
  [[ "$(cat "$STATE/last_restored_snapshot")" == "$snapshot" ]]; then
  exit 0
fi

required=(MANIFEST.txt fhd_pg.dump modstore_pg.dump payment_pg.dump modstore_sqlite.db.gz)
for file in "${required[@]}"; do
  [[ -s "$latest/$file" ]] || {
    log "归档不完整: $latest 缺少 $file"
    exit 1
  }
done
(cd "$latest" && sha256sum -c MANIFEST.txt >/dev/null)
for dump in fhd_pg.dump modstore_pg.dump payment_pg.dump; do
  pg_restore --list "$latest/$dump" >/dev/null
done
gzip -t "$latest/modstore_sqlite.db.gz"

docker inspect "$PG_CONTAINER" >/dev/null 2>&1 || {
  log "PostgreSQL 容器不存在: $PG_CONTAINER"
  exit 1
}
[[ "$(docker inspect -f '{{.State.Running}}' "$PG_CONTAINER")" == "true" ]] ||
  docker start "$PG_CONTAINER" >/dev/null

modstore_was_active=0
if systemctl is-active --quiet xcmax-dr-modstore.service; then
  modstore_was_active=1
fi
cleanup() {
  if [[ "$modstore_was_active" == "1" ]]; then
    systemctl start xcmax-dr-modstore.service || true
  fi
}
trap cleanup EXIT

restore_next() {
  local db="$1" dump="$2" next
  next="${db}_next"
  log "恢复 $db → $next"
  docker exec "$PG_CONTAINER" sh -ceu \
    'dropdb --if-exists --force -U "$POSTGRES_USER" "$1"; createdb -T template0 -U "$POSTGRES_USER" "$1"' \
    sh "$next"
  dd if="$latest/$dump" status=none |
    docker exec -i "$PG_CONTAINER" sh -ceu \
      'exec pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$1"' \
      sh "$next"
  local tables
  tables="$(
    docker exec "$PG_CONTAINER" sh -ceu \
      'psql -U "$POSTGRES_USER" -d "$1" -Atc "select count(*) from pg_tables where schemaname=current_schema()"' \
      sh "$next"
  )"
  [[ "$tables" =~ ^[0-9]+$ && "$tables" -gt 0 ]] || {
    log "$next 恢复后没有业务表"
    return 1
  }
  log "$next 校验完成: tables=$tables"
}

restore_next xcagi fhd_pg.dump
restore_next modstore modstore_pg.dump
restore_next payment_db payment_pg.dump

systemctl stop xcmax-dr-modstore.service 2>/dev/null || true
docker exec "$PG_CONTAINER" sh -ceu '
  for db in xcagi modstore payment_db; do
    dropdb --if-exists --force -U "$POSTGRES_USER" "${db}_previous"
  done
'
docker exec "$PG_CONTAINER" sh -ceu \
  'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c "$1"' sh \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('xcagi', 'modstore', 'payment_db') AND pid <> pg_backend_pid()"
for rename in \
  "xcagi xcagi_previous" \
  "xcagi_next xcagi" \
  "modstore modstore_previous" \
  "modstore_next modstore" \
  "payment_db payment_db_previous" \
  "payment_db_next payment_db"; do
  read -r from to <<<"$rename"
  docker exec "$PG_CONTAINER" sh -ceu \
    'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c "$1"' sh \
    "ALTER DATABASE $from RENAME TO $to"
done

sqlite_tmp="$(mktemp "$DR_ROOT/runtime-data/modstore/.modstore.db.XXXXXX")"
gzip -dc "$latest/modstore_sqlite.db.gz" >"$sqlite_tmp"
chown xcmaxapp:xcmaxapp "$sqlite_tmp"
chmod 0600 "$sqlite_tmp"
mv -f "$sqlite_tmp" "$DR_ROOT/runtime-data/modstore/modstore.db"

for db in xcagi modstore payment_db; do
  docker exec "$PG_CONTAINER" sh -ceu \
    'vacuumdb --analyze-only -U "$POSTGRES_USER" "$1" >/dev/null' sh "$db"
done

printf '%s\n' "$snapshot" >"$STATE/last_restored_snapshot"
date -u +%s >"$STATE/last_restore_success"
log "恢复切换成功: $snapshot"
