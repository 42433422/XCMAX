#!/usr/bin/env bash
# Ship completed WAL segments from the PostgreSQL 16 application cluster.

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

CONTAINER="${OPS_PG16_CONTAINER:-modstore_deploy-postgres-1}"
ARCHIVE_NAME="${OPS_PG16_ARCHIVE_NAME:-xcmax_wal_archive}"
STATE="${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state"
LOG="${OPS_LOG_DIR:-/var/log/xcmax-ops}/wal-pg16-ship.log"
TARGET="${OPS_BACKUP_SSH_TARGET:-}"
KEY="${OPS_BACKUP_SSH_KEY:-/root/.ssh/xcmax_dr_ed25519}"
REMOTE_ROOT="${OPS_BACKUP_SSH_DEST:-.}"
LOCK="/run/lock/xcmax-wal-pg16-ship.lock"
TRANSFER_LOCK="${OPS_DR_TRANSFER_LOCK:-/run/lock/xcmax-dr-transfer.lock}"
TRANSFER_WAIT_SECONDS="${OPS_DR_TRANSFER_WAIT_SECONDS:-1800}"
TRANSFER_MAX_SECONDS="${OPS_DR_WAL_TRANSFER_MAX_SECONDS:-900}"

# shellcheck source=../lib/bounded_transfer.sh
# shellcheck disable=SC1091
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../lib" &>/dev/null && pwd)/bounded_transfer.sh"

[[ -n "$TARGET" && -f "$KEY" ]] || {
  echo "温备 SSH 目标或私钥未配置" >&2
  exit 1
}
docker inspect "$CONTAINER" >/dev/null
volume="$(
  docker inspect -f \
    '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Source}}{{end}}{{end}}' \
    "$CONTAINER"
)"
[[ "$volume" == /var/lib/docker/volumes/*/_data ]] || {
  echo "拒绝未知 PostgreSQL 16 数据卷: $volume" >&2
  exit 2
}
ARCHIVE="$volume/$ARCHIVE_NAME"
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
restore_point="xcmax-dr-pg16-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -u postgres "$CONTAINER" sh -ceu \
  "psql -U \"\$POSTGRES_USER\" -d postgres -Atqc \
  \"SELECT pg_create_restore_point('$restore_point')\"" >/dev/null
primary_lsn="$(
  docker exec -u postgres "$CONTAINER" sh -ceu \
    'psql -U "$POSTGRES_USER" -d postgres -Atqc "SELECT pg_switch_wal()"'
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
  log "ERROR: PostgreSQL 16 pg_switch_wal 后 60 秒仍无归档段"
  exit 1
}

status_tmp="$STATE/.wal-pg16-status.$$"
{
  printf 'shipped_at_epoch=%s\n' "$(date -u +%s)"
  printf 'primary_lsn=%s\n' "$primary_lsn"
  printf 'latest_segment=%s\n' "$latest_segment"
  printf 'primary_host=%s\n' "$(hostname -f 2>/dev/null || hostname)"
} >"$status_tmp"
chmod 0600 "$status_tmp"

ssh_cmd="ssh -i $KEY -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
(
  flock -w "$TRANSFER_WAIT_SECONDS" 8 || exit 1
  xcmax_run_bounded_transfer "$TRANSFER_MAX_SECONDS" "postgres16-wal" "$LOG" \
    rsync -a --ignore-existing --delay-updates --partial \
    -e "$ssh_cmd" \
    "$ARCHIVE/" "${TARGET}:${REMOTE_ROOT}/wal-pg16/archive/"
  xcmax_run_bounded_transfer "$TRANSFER_MAX_SECONDS" "postgres16-wal-status" "$LOG" \
    rsync -a --delay-updates \
    -e "$ssh_cmd" \
    "$status_tmp" "${TARGET}:${REMOTE_ROOT}/wal-pg16/status/current"
) 8>"$TRANSFER_LOCK"
mv -f "$status_tmp" "$STATE/wal-pg16-status"
date -u +%s >"$STATE/wal_pg16_ship_last_success"

# Keep only eight transferred segments in PGDATA so future base backups do not
# recursively absorb an unbounded archive.
mapfile -t archived_segments < <(
  find "$ARCHIVE" -maxdepth 1 -type f \
    -regextype posix-extended -regex '.*/[0-9A-F]{24}' -printf '%p\n' | sort -r
)
if ((${#archived_segments[@]} > 8)); then
  for victim in "${archived_segments[@]:8}"; do
    [[ "$victim" == "$ARCHIVE"/[0-9A-F]* ]] || continue
    rm -f -- "$victim"
  done
fi
log "PostgreSQL 16 WAL 推送完成: latest=$latest_segment lsn=$primary_lsn"
