#!/usr/bin/env bash
# Build or refresh a PostgreSQL 10 physical standby from the newest verified
# base backup. Completed WAL segments are replayed continuously from the
# receiver directory mounted read-only in the container.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
INCOMING="${OPS_DR_INCOMING:-$DR_ROOT/incoming}"
WAL_ROOT="${OPS_DR_WAL_ROOT:-$DR_ROOT/wal}"
DATA="$WAL_ROOT/postgres10-data"
STATE="${OPS_DR_STATE:-/var/lib/xcmax-dr}"
LOG="${OPS_DR_WAL_LOG:-/var/log/xcmax-dr/wal-standby.log}"
CONTAINER="${OPS_DR_WAL_CONTAINER:-xcmax-dr-postgres10}"
IMAGE="${OPS_DR_WAL_IMAGE:-postgres:10}"
PORT="${OPS_DR_WAL_PORT:-15432}"
LOCK="/run/lock/xcmax-dr-wal-standby.lock"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

[[ "$DR_ROOT" == /srv/xcmax-dr ]] || {
  echo "拒绝非标准 DR 根目录: $DR_ROOT" >&2
  exit 2
}
[[ "$PORT" =~ ^[0-9]+$ && "$PORT" -ge 1024 && "$PORT" -le 65535 ]] || {
  echo "OPS_DR_WAL_PORT 非法: $PORT" >&2
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
  find "$INCOMING/wal/base" -mindepth 1 -maxdepth 1 -type d \
    -exec test -e '{}/BASE_READY' ';' -printf '%T@ %p\n' 2>/dev/null |
    sort -nr | head -1 | cut -d' ' -f2-
)"
[[ -n "$latest" && -d "$latest" ]] || {
  log "尚未收到可用的 PostgreSQL 10 基础备份"
  exit 0
}
snapshot="$(basename "$latest")"
if [[ "$FORCE" != "1" && -f "$STATE/wal_base_applied" ]] &&
  [[ "$(cat "$STATE/wal_base_applied")" == "$snapshot" ]]; then
  exit 0
fi

(cd "$latest" && sha256sum -c MANIFEST.txt)
grep -Eq '^server_version=10(\.|$)' "$latest/BASE_INFO" || {
  log "ERROR: 基础备份不是 PostgreSQL 10"
  exit 1
}

staging="$WAL_ROOT/.postgres10-staging-$snapshot"
rm -rf -- "$staging"
install -d -m 0700 "$staging"
tar -xzf "$latest/base.tar.gz" -C "$staging"
if [[ -s "$latest/pg_wal.tar.gz" ]]; then
  install -d -m 0700 "$staging/pg_wal"
  tar -xzf "$latest/pg_wal.tar.gz" -C "$staging/pg_wal"
fi

cat >"$staging/recovery.conf" <<'EOF'
standby_mode = 'on'
restore_command = 'cp /wal-archive/%f %p'
recovery_target_timeline = 'latest'
EOF
chmod 0600 "$staging/recovery.conf"
chown -R 999:999 "$staging"

if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  docker stop -t 30 "$CONTAINER" >/dev/null || true
  docker rm "$CONTAINER" >/dev/null
fi

if [[ -d "$DATA" ]]; then
  previous="$WAL_ROOT/postgres10-data.previous-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$DATA" "$previous"
fi
mv "$staging" "$DATA"
find "$WAL_ROOT" -maxdepth 1 -type d -name 'postgres10-data.previous-*' \
  -printf '%T@ %p\n' | sort -nr | tail -n +3 | cut -d' ' -f2- |
  while IFS= read -r victim; do
    [[ "$victim" == "$WAL_ROOT"/postgres10-data.previous-* ]] || continue
    rm -rf -- "$victim"
  done

docker pull "$IMAGE" >/dev/null
docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  -p "127.0.0.1:${PORT}:5432" \
  -v "$DATA:/var/lib/postgresql/data" \
  -v "$INCOMING/wal/archive:/wal-archive:ro" \
  "$IMAGE" \
  -c listen_addresses='*' \
  -c hot_standby=on >/dev/null

deadline=$((SECONDS + 120))
while ((SECONDS < deadline)); do
  if docker exec "$CONTAINER" pg_isready -q -d postgres; then
    break
  fi
  sleep 2
done
docker exec "$CONTAINER" pg_isready -q -d postgres || {
  docker logs --tail 80 "$CONTAINER" >&2
  exit 1
}

in_recovery="$(
  docker exec "$CONTAINER" \
    psql -U postgres -d postgres -Atqc "SELECT pg_is_in_recovery()"
)"
[[ "$in_recovery" == "t" ]] || {
  log "ERROR: PostgreSQL 10 容器未处于恢复模式"
  exit 1
}
printf '%s\n' "$snapshot" >"$STATE/wal_base_applied"
date -u +%s >"$STATE/wal_standby_last_success"
log "PostgreSQL 10 温备已启动: snapshot=$snapshot port=$PORT"
