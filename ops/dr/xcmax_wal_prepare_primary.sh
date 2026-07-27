#!/usr/bin/env bash
# Enable PostgreSQL 10 WAL archiving and publish a physical base backup to DR.
# Safe to re-run: settings are changed only when needed and each base is
# finalized in a new immutable snapshot directory.

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
BASE_ROOT="$WAL_ROOT/base"
STATE="${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state"
LOG="${OPS_LOG_DIR:-/var/log/xcmax-ops}/wal-base.log"
TARGET="${OPS_BACKUP_SSH_TARGET:-}"
KEY="${OPS_BACKUP_SSH_KEY:-/root/.ssh/xcmax_dr_ed25519}"
REMOTE_ROOT="${OPS_BACKUP_SSH_DEST:-.}"
PG_OS_USER="${OPS_PG_OS_USER:-postgres}"
PG_SERVICE="${OPS_PG_SERVICE:-postgresql}"
LOCK="/run/lock/xcmax-wal-base.lock"

[[ "$WAL_ROOT" == /var/lib/pgsql/xcmax-wal ]] || {
  echo "拒绝非标准 WAL 根目录: $WAL_ROOT" >&2
  exit 2
}
[[ -n "$TARGET" && -f "$KEY" ]] || {
  echo "温备 SSH 目标或私钥未配置" >&2
  exit 1
}
command -v pg_basebackup >/dev/null 2>&1 || {
  echo "pg_basebackup 不可用" >&2
  exit 1
}

install -d -m 0700 -o "$PG_OS_USER" -g "$PG_OS_USER" \
  "$WAL_ROOT" "$ARCHIVE" "$BASE_ROOT"
install -d -m 0700 "$STATE" "$(dirname "$LOG")"
touch "$LOG"

exec 9>"$LOCK"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

pg_show() {
  sudo -u "$PG_OS_USER" psql -Atqc "SHOW $1" postgres
}

pg_system_identifier() {
  sudo -u "$PG_OS_USER" pg_controldata "$(pg_show data_directory)" |
    awk -F: '/Database system identifier/ {gsub(/ /,"",$2); print $2}'
}

server_major="$(pg_show server_version | cut -d. -f1)"
[[ "$server_major" == "10" ]] || {
  log "ERROR: 物理 WAL 方案要求 PostgreSQL 10，当前为 $(pg_show server_version)"
  exit 1
}

restart_required=0
if [[ "$(pg_show archive_mode)" != "on" ]]; then
  sudo -u "$PG_OS_USER" psql -v ON_ERROR_STOP=1 -qc \
    "ALTER SYSTEM SET archive_mode TO 'on'" postgres
  restart_required=1
fi
archive_cmd="test ! -f ${ARCHIVE}/%f && cp %p ${ARCHIVE}/%f"
escaped_archive_cmd="${archive_cmd//\'/\'\'}"
if [[ "$(pg_show archive_command)" != "$archive_cmd" ]]; then
  sudo -u "$PG_OS_USER" psql -v ON_ERROR_STOP=1 -qc \
    "ALTER SYSTEM SET archive_command TO '${escaped_archive_cmd}'" postgres
  restart_required=1
fi
if [[ "$(pg_show archive_timeout)" != "15min" ]]; then
  sudo -u "$PG_OS_USER" psql -v ON_ERROR_STOP=1 -qc \
    "ALTER SYSTEM SET archive_timeout TO '15min'" postgres
  restart_required=1
fi

if [[ "$restart_required" == "1" ]]; then
  log "重启 PostgreSQL 以启用 WAL 归档"
  systemctl restart "$PG_SERVICE"
fi
[[ "$(pg_show archive_mode)" == "on" ]] || {
  log "ERROR: archive_mode 未生效"
  exit 1
}

# pg_basebackup reads every regular file in PGDATA. Historical root-owned
# config backups are allowed only by explicit basename and receive group-read;
# any other foreign-owned top-level file remains a hard failure.
data_directory="$(pg_show data_directory)"
while IFS= read -r -d '' foreign_file; do
  case "$(basename "$foreign_file")" in
    postgresql.conf.bak*|pg_hba.conf.bak*)
      chgrp "$PG_OS_USER" "$foreign_file"
      chmod g+r "$foreign_file"
      log "允许 pg_basebackup 读取历史配置备份: $(basename "$foreign_file")"
      ;;
    *)
      log "ERROR: PGDATA 存在非 postgres 所有的未知文件: $foreign_file"
      exit 1
      ;;
  esac
done < <(
  find "$data_directory" -maxdepth 1 -type f ! -user "$PG_OS_USER" -print0
)

snapshot="$(date -u +%Y%m%dT%H%M%SZ)-$(pg_system_identifier)"
staging="$BASE_ROOT/.staging-$snapshot"
final="$BASE_ROOT/$snapshot"
rm -rf -- "$staging"
install -d -m 0700 -o "$PG_OS_USER" -g "$PG_OS_USER" "$staging"

log "创建 PostgreSQL 10 物理基础备份: $snapshot"
sudo -u "$PG_OS_USER" pg_basebackup \
  -D "$staging" -Ft -z -X stream -c fast

{
  printf 'snapshot=%s\n' "$snapshot"
  printf 'created_at_epoch=%s\n' "$(date -u +%s)"
  printf 'server_version=%s\n' "$(pg_show server_version)"
  printf 'system_identifier=%s\n' "$(pg_system_identifier)"
  printf 'timeline=%s\n' "$(
    sudo -u "$PG_OS_USER" pg_controldata "$(pg_show data_directory)" |
      awk -F: '/Latest checkpoint.s TimeLineID/ {gsub(/ /,"",$2); print $2}'
  )"
} >"$staging/BASE_INFO"
(cd "$staging" && sha256sum ./*.tar.gz BASE_INFO >MANIFEST.txt)
touch "$staging/BASE_READY"
chown -R root:root "$staging"
chmod -R go-rwx "$staging"
mv "$staging" "$final"

rsync -a --partial --delay-updates \
  -e "ssh -i $KEY -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
  "$final/" "${TARGET}:${REMOTE_ROOT}/wal/base/${snapshot}/" >>"$LOG" 2>&1
printf '%s\n' "$snapshot" >"$STATE/wal_base_last_snapshot"
date -u +%s >"$STATE/wal_base_last_success"

bash "$(dirname "$0")/xcmax_wal_ship.sh"
log "物理基础备份已推送: $snapshot"
