#!/usr/bin/env bash
# Promote both PostgreSQL standbys and start DR application services.
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
PAYMENT_CONTAINER="${OPS_DR_WAL_CONTAINER:-xcmax-dr-postgres10}"
PAYMENT_PORT="${OPS_DR_WAL_PORT:-15432}"
APP_CONTAINER="${OPS_DR_WAL_PG16_CONTAINER:-xcmax-dr-postgres16-wal}"
APP_PORT="${OPS_DR_WAL_PG16_PORT:-15433}"
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

APP_SUPERUSER="$(cat "$STATE/wal_pg16_superuser" 2>/dev/null || true)"
[[ -n "$APP_SUPERUSER" ]] || {
  log "ERROR: PostgreSQL 16 superuser 状态缺失"
  exit 1
}

promote_cluster() {
  local container="$1" user="$2" label="$3" recovery deadline
  docker inspect "$container" >/dev/null 2>&1 || {
    log "ERROR: $label 温备容器不存在"
    return 1
  }
  [[ "$(docker inspect -f '{{.State.Running}}' "$container")" == "true" ]] || {
    log "ERROR: $label 温备容器未运行"
    return 1
  }
  recovery="$(
    docker exec -u postgres "$container" \
      psql -U "$user" -d postgres -Atqc "SELECT pg_is_in_recovery()"
  )"
  if [[ "$recovery" == "t" ]]; then
    log "提升 $label 温备"
    docker exec -u postgres "$container" \
      pg_ctl -D /var/lib/postgresql/data promote -w
  fi
  deadline=$((SECONDS + 60))
  while ((SECONDS < deadline)); do
    recovery="$(
      docker exec -u postgres "$container" \
        psql -U "$user" -d postgres -Atqc "SELECT pg_is_in_recovery()"
    )"
    [[ "$recovery" == "f" ]] && break
    sleep 2
  done
  [[ "$recovery" == "f" ]] || {
    log "ERROR: $label 提升超时"
    return 1
  }
}

promote_cluster "$APP_CONTAINER" "$APP_SUPERUSER" "PostgreSQL 16 应用库"
promote_cluster "$PAYMENT_CONTAINER" postgres "PostgreSQL 10 支付库"

OPS_DR_APP_PG_PORT="$APP_PORT" \
OPS_DR_PAYMENT_PG_PORT="$PAYMENT_PORT" \
OPS_DR_PG_PRESERVE_CREDENTIALS=1 \
  "$PREPARE_RUNTIME"

systemctl restart xcmax-dr-modstore
systemctl start xcmax-dr-fhd xcmax-dr-payment xcmax-dr-scheduler

curl -fsS http://127.0.0.1:15100/api/health >/dev/null
curl -fsS http://127.0.0.1:19999/api/health >/dev/null
curl -fsS http://127.0.0.1:18080/actuator/health >/dev/null

/usr/local/sbin/xcmax-dr-prepare-edge --promoted
date -u +%s >"$STATE/promoted_at"
log "DR 提升完成: app_pg=$APP_PORT payment_pg=$PAYMENT_PORT"
