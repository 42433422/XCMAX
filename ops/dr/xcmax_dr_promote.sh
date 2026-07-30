#!/usr/bin/env bash
# Promote both PostgreSQL standbys and start DR application services. Promotion
# requires either an explicit operator confirmation or a short-lived, root-only
# witness created after authoritative DNS selection and provider-side fencing.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}
CONFIRM_MODE=""
WITNESS_FILE=""
case "${1:-}" in
  --confirm-primary-down)
    CONFIRM_MODE="manual"
    ;;
  --witness-file)
    CONFIRM_MODE="witness"
    WITNESS_FILE="${2:-}"
    ;;
  *)
    echo "用法: $0 --confirm-primary-down | --witness-file <见证文件>" >&2
    exit 2
    ;;
esac

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
PAYMENT_CONTAINER="${OPS_DR_WAL_CONTAINER:-xcmax-dr-postgres10}"
PAYMENT_PORT="${OPS_DR_WAL_PORT:-15432}"
APP_CONTAINER="${OPS_DR_WAL_PG16_CONTAINER:-xcmax-dr-postgres16-wal}"
APP_PORT="${OPS_DR_WAL_PG16_PORT:-15433}"
STATE="${OPS_DR_STATE:-/var/lib/xcmax-dr}"
LOG="${OPS_DR_PROMOTE_LOG:-/var/log/xcmax-dr/promote.log}"
PREPARE_RUNTIME="${OPS_DR_PREPARE_RUNTIME:-/usr/local/sbin/xcmax-dr-prepare-runtime}"
LOCK="/run/lock/xcmax-dr-promote.lock"

if [[ "$CONFIRM_MODE" == "witness" ]]; then
  [[ -s "$WITNESS_FILE" ]] || {
    echo "拒绝提升：见证文件不存在" >&2
    exit 1
  }
  python3 - "$WITNESS_FILE" <<'PY'
import json
import os
import sys
import time

path = sys.argv[1]
stat = os.stat(path)
if stat.st_uid != 0 or stat.st_mode & 0o077:
    raise SystemExit("拒绝提升：见证文件必须由 root 私有")
doc = json.load(open(path, encoding="utf-8"))
if doc.get("promote") is not True:
    raise SystemExit("拒绝提升：见证决策不是 promote")
if doc.get("reason") != "all_promotion_guards_satisfied":
    raise SystemExit("拒绝提升：见证原因不匹配")
if int(doc.get("expires_at", 0)) < int(time.time()):
    raise SystemExit("拒绝提升：见证已过期")
if doc.get("primary_https_ok") is not False or doc.get("primary_ssh_ok") is not False:
    raise SystemExit("拒绝提升：生产仍可达")
if doc.get("fence_ready") is not True or doc.get("standby_ready") is not True:
    raise SystemExit("拒绝提升：fence 或 standby 未就绪")
if doc.get("authoritative_addresses") != [doc.get("secondary_ip")]:
    raise SystemExit("拒绝提升：权威 DNS 未唯一选择 DR")
PY
fi

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

systemctl disable --now xcmax-dr-primary-tunnel.service >/dev/null 2>&1 || true
OPS_DR_APP_PG_PORT="$APP_PORT" \
OPS_DR_PAYMENT_PG_PORT="$PAYMENT_PORT" \
OPS_DR_REDIS_PORT=6379 \
OPS_DR_PAYMENT_API_PORT=18080 \
OPS_DR_PG_PRESERVE_CREDENTIALS=1 \
OPS_DR_RUNTIME_MODE=promoted \
  "$PREPARE_RUNTIME"

systemctl restart xcmax-dr-modstore
systemctl start xcmax-dr-fhd xcmax-dr-payment xcmax-dr-scheduler

curl -fsS http://127.0.0.1:15100/api/health >/dev/null
curl -fsS http://127.0.0.1:19999/api/health >/dev/null
curl -fsS http://127.0.0.1:18080/actuator/health >/dev/null

/usr/local/sbin/xcmax-dr-prepare-edge --promoted
date -u +%s >"$STATE/promoted_at"
log "DR 提升完成: app_pg=$APP_PORT payment_pg=$PAYMENT_PORT"
