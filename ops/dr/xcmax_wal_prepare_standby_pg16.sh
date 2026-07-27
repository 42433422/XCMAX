#!/usr/bin/env bash
# Build or refresh the PostgreSQL 16 application standby.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
INCOMING="${OPS_DR_INCOMING:-$DR_ROOT/incoming}"
WAL_ROOT="${OPS_DR_WAL_ROOT:-$DR_ROOT/wal}"
DATA="$WAL_ROOT/postgres16-data"
STATE="${OPS_DR_STATE:-/var/lib/xcmax-dr}"
LOG="${OPS_DR_WAL_PG16_LOG:-/var/log/xcmax-dr/wal-pg16-standby.log}"
CONTAINER="${OPS_DR_WAL_PG16_CONTAINER:-xcmax-dr-postgres16-wal}"
IMAGE="${OPS_DR_WAL_PG16_IMAGE:-pgvector/pgvector:pg16}"
PORT="${OPS_DR_WAL_PG16_PORT:-15433}"
LOCK="/run/lock/xcmax-dr-wal-pg16-standby.lock"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

[[ "$DR_ROOT" == /srv/xcmax-dr ]] || {
  echo "拒绝非标准 DR 根目录: $DR_ROOT" >&2
  exit 2
}
install -d -m 0700 "$WAL_ROOT" "$STATE" "$(dirname "$LOG")"
touch "$LOG"
exec 9>"$LOCK"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

latest="$(
  find "$INCOMING/wal-pg16/base" -mindepth 1 -maxdepth 1 -type d \
    -exec test -e '{}/BASE_READY' ';' -printf '%T@ %p\n' 2>/dev/null |
    sort -nr | head -1 | cut -d' ' -f2-
)"
[[ -n "$latest" && -d "$latest" ]] || {
  log "尚未收到 PostgreSQL 16 基础备份"
  exit 0
}
snapshot="$(basename "$latest")"
if [[ "$FORCE" != "1" && -f "$STATE/wal_pg16_base_applied" ]] &&
  [[ "$(cat "$STATE/wal_pg16_base_applied")" == "$snapshot" ]]; then
  exit 0
fi
(cd "$latest" && sha256sum -c MANIFEST.txt)
grep -Eq '^server_version=16(\.|$)' "$latest/BASE_INFO"
superuser="$(sed -n 's/^database_superuser=//p' "$latest/BASE_INFO")"
[[ -n "$superuser" ]] || {
  log "ERROR: PostgreSQL 16 基线缺少 superuser 身份"
  exit 1
}

staging="$WAL_ROOT/.postgres16-staging-$snapshot"
rm -rf -- "$staging"
install -d -m 0700 "$staging"
tar -xzf "$latest/base.tar.gz" -C "$staging"
if [[ -s "$latest/pg_wal.tar.gz" ]]; then
  install -d -m 0700 "$staging/pg_wal"
  tar -xzf "$latest/pg_wal.tar.gz" -C "$staging/pg_wal"
fi
touch "$staging/standby.signal"
{
  echo "restore_command = 'cp /wal-archive/%f %p'"
  echo "recovery_target_timeline = 'latest'"
} >>"$staging/postgresql.auto.conf"
chmod 0600 "$staging/postgresql.auto.conf" "$staging/standby.signal"
chown -R 999:999 "$staging"

if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  docker stop -t 30 "$CONTAINER" >/dev/null || true
  docker rm "$CONTAINER" >/dev/null
fi
if [[ -d "$DATA" ]]; then
  mv "$DATA" "$WAL_ROOT/postgres16-data.previous-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mv "$staging" "$DATA"
docker pull "$IMAGE" >/dev/null
docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  -p "127.0.0.1:${PORT}:5432" \
  -v "$DATA:/var/lib/postgresql/data" \
  -v "$INCOMING/wal-pg16/archive:/wal-archive:ro" \
  "$IMAGE" \
  -c listen_addresses='*' \
  -c hot_standby=on >/dev/null

deadline=$((SECONDS + 180))
while ((SECONDS < deadline)); do
  if docker exec "$CONTAINER" pg_isready -q -d postgres; then
    break
  fi
  sleep 2
done
docker exec "$CONTAINER" pg_isready -q -d postgres || {
  docker logs --tail 100 "$CONTAINER" >&2
  exit 1
}
in_recovery="$(
  docker exec -u postgres "$CONTAINER" \
    psql -U "$superuser" -d postgres -Atqc "SELECT pg_is_in_recovery()"
)"
[[ "$in_recovery" == "t" ]] || {
  log "ERROR: PostgreSQL 16 容器未处于恢复模式"
  exit 1
}
printf '%s\n' "$snapshot" >"$STATE/wal_pg16_base_applied"
printf '%s\n' "$superuser" >"$STATE/wal_pg16_superuser"
date -u +%s >"$STATE/wal_pg16_standby_last_success"
log "PostgreSQL 16 温备已启动: snapshot=$snapshot port=$PORT"
