#!/usr/bin/env bash
# Ship completed PostgreSQL 10 WAL segments to the restricted DR receiver.
# The PostgreSQL archive_command only copies locally; this root-owned job owns
# the network credential and forces a segment switch before each shipment.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

ENV_FILE="${OPS_ENV_FILE:-/etc/xcmax-ops.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

WAL_ROOT="${OPS_WAL_ROOT:-/var/lib/pgsql/xcmax-wal}"
ARCHIVE="$WAL_ROOT/archive"
STATE="${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state"
LOG="${OPS_LOG_DIR:-/var/log/xcmax-ops}/wal-ship.log"
TARGET="${OPS_BACKUP_SSH_TARGET:-}"
KEY="${OPS_BACKUP_SSH_KEY:-/root/.ssh/xcmax_dr_ed25519}"
REMOTE_ROOT="${OPS_BACKUP_SSH_DEST:-.}"
LOCK="/run/lock/xcmax-wal-ship.lock"
TRANSFER_LOCK="${OPS_DR_TRANSFER_LOCK:-/run/lock/xcmax-dr-transfer.lock}"
TRANSFER_WAIT_SECONDS="${OPS_DR_TRANSFER_WAIT_SECONDS:-1800}"
PG_OS_USER="${OPS_PG_OS_USER:-postgres}"

[[ "$WAL_ROOT" == /var/lib/pgsql/xcmax-wal ]] || {
  echo "拒绝非标准 WAL 根目录: $WAL_ROOT" >&2
  exit 2
}
[[ -n "$TARGET" ]] || {
  echo "OPS_BACKUP_SSH_TARGET 未配置" >&2
  exit 1
}
[[ -f "$KEY" ]] || {
  echo "WAL 推送私钥不存在: $KEY" >&2
  exit 1
}

install -d -m 0700 -o "$PG_OS_USER" -g "$PG_OS_USER" "$ARCHIVE"
install -d -m 0700 "$STATE" "$(dirname "$LOG")"
touch "$LOG"

exec 9>"$LOCK"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

previous_segment="$(
  find "$ARCHIVE" -maxdepth 1 -type f \
    -regextype posix-extended -regex '.*/[0-9A-F]{24}' -printf '%f\n' |
    sort | tail -1
)"

# PostgreSQL 10 uses the WAL function names. A forced switch bounds RPO even
# during quiet periods; archive_timeout remains a second line of defence.
primary_lsn="$(
  sudo -u "$PG_OS_USER" psql -Atqc \
    "SELECT pg_switch_wal()" postgres
)"

deadline=$((SECONDS + 60))
while ((SECONDS < deadline)); do
  latest_segment="$(
    find "$ARCHIVE" -maxdepth 1 -type f \
      -regextype posix-extended -regex '.*/[0-9A-F]{24}' -printf '%f\n' |
      sort | tail -1
  )"
  if [[ -n "$latest_segment" &&
    ( -z "$previous_segment" || "$latest_segment" != "$previous_segment" ) ]]; then
    break
  fi
  sleep 2
done
[[ -n "${latest_segment:-}" &&
  ( -z "$previous_segment" || "$latest_segment" != "$previous_segment" ) ]] || {
  log "ERROR: pg_switch_wal 后 60 秒仍无归档段"
  exit 1
}

status_tmp="$STATE/.wal-status.$$"
{
  printf 'shipped_at_epoch=%s\n' "$(date -u +%s)"
  printf 'primary_lsn=%s\n' "$primary_lsn"
  printf 'latest_segment=%s\n' "$latest_segment"
  printf 'primary_host=%s\n' "$(hostname -f 2>/dev/null || hostname)"
} >"$status_tmp"
chmod 0600 "$status_tmp"

ssh_opts=(
  -i "$KEY"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes
)
(
  flock -w "$TRANSFER_WAIT_SECONDS" 8 || exit 1
  rsync -a --ignore-existing --delay-updates --partial \
    -e "ssh ${ssh_opts[*]}" \
    "$ARCHIVE/" "${TARGET}:${REMOTE_ROOT}/wal/archive/" >>"$LOG" 2>&1
  rsync -a --delay-updates \
    -e "ssh ${ssh_opts[*]}" \
    "$status_tmp" "${TARGET}:${REMOTE_ROOT}/wal/status/current" >>"$LOG" 2>&1
) 8>"$TRANSFER_LOCK"
mv -f "$status_tmp" "$STATE/wal-status"
date -u +%s >"$STATE/wal_ship_last_success"

# Retain a week locally. The immutable receiver keeps the disaster copy.
find "$ARCHIVE" -maxdepth 1 -type f \
  -regextype posix-extended -regex '.*/[0-9A-F]{24}' -mtime +7 -delete
log "WAL 推送完成: latest=$latest_segment lsn=$primary_lsn"
