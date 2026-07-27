#!/usr/bin/env bash
# Promote the PostgreSQL 10 standby and start DR application services.
# The explicit confirmation flag is intentionally non-optional: promotion is
# irreversible for this standby and must not happen while primary is writable.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}
[[ "${1:-}" == "--confirm-primary-down" ]] || {
  echo "拒绝提升：请先确认生产已停止写入，再传 --confirm-primary-down" >&2
  exit 2
}

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
CONTAINER="${OPS_DR_WAL_CONTAINER:-xcmax-dr-postgres10}"
PORT="${OPS_DR_WAL_PORT:-15432}"
STATE="${OPS_DR_STATE:-/var/lib/xcmax-dr}"
LOG="${OPS_DR_PROMOTE_LOG:-/var/log/xcmax-dr/promote.log}"
PREPARE_RUNTIME="${OPS_DR_PREPARE_RUNTIME:-/usr/local/sbin/xcmax-dr-prepare-runtime}"
LOCK="/run/lock/xcmax-dr-promote.lock"

install -d -m 0700 "$STATE" "$(dirname "$LOG")"
touch "$LOG"
exec 9>"$LOCK"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

docker inspect "$CONTAINER" >/dev/null 2>&1 || {
  log "ERROR: PostgreSQL 10 温备容器不存在"
  exit 1
}
[[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" == "true" ]] || {
  log "ERROR: PostgreSQL 10 温备容器未运行"
  exit 1
}

recovery="$(
  docker exec "$CONTAINER" \
    psql -U postgres -d postgres -Atqc "SELECT pg_is_in_recovery()"
)"
if [[ "$recovery" == "t" ]]; then
  log "提升 PostgreSQL 10 温备"
  docker exec -u postgres "$CONTAINER" \
    pg_ctl -D /var/lib/postgresql/data promote -w
fi

deadline=$((SECONDS + 60))
while ((SECONDS < deadline)); do
  recovery="$(
    docker exec "$CONTAINER" \
      psql -U postgres -d postgres -Atqc "SELECT pg_is_in_recovery()"
  )"
  [[ "$recovery" == "f" ]] && break
  sleep 2
done
[[ "$recovery" == "f" ]] || {
  log "ERROR: PostgreSQL 提升超时"
  exit 1
}

OPS_DR_PG_PORT="$PORT" \
OPS_DR_PG_PRESERVE_CREDENTIALS=1 \
  "$PREPARE_RUNTIME"

systemctl restart xcmax-dr-modstore
systemctl start xcmax-dr-fhd xcmax-dr-payment xcmax-dr-scheduler

curl -fsS http://127.0.0.1:15100/api/health >/dev/null
curl -fsS http://127.0.0.1:19999/api/health >/dev/null
curl -fsS http://127.0.0.1:18080/actuator/health >/dev/null

/usr/local/sbin/xcmax-dr-prepare-edge --promoted
date -u +%s >"$STATE/promoted_at"
log "DR 提升完成: postgres_port=$PORT"
