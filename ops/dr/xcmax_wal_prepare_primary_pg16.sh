#!/usr/bin/env bash
# Enable WAL archiving and publish a physical base backup for the PostgreSQL 16
# application cluster running in Docker.

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
BASE_ROOT="${OPS_PG16_BASE_ROOT:-/var/lib/pgsql/xcmax-wal-pg16/base}"
STATE="${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state"
LOG="${OPS_LOG_DIR:-/var/log/xcmax-ops}/wal-pg16-base.log"
TARGET="${OPS_BACKUP_SSH_TARGET:-}"
KEY="${OPS_BACKUP_SSH_KEY:-/root/.ssh/xcmax_dr_ed25519}"
REMOTE_ROOT="${OPS_BACKUP_SSH_DEST:-.}"
LOCK="/run/lock/xcmax-wal-pg16-base.lock"
TRANSFER_LOCK="${OPS_DR_TRANSFER_LOCK:-/run/lock/xcmax-dr-transfer.lock}"
TRANSFER_WAIT_SECONDS="${OPS_DR_TRANSFER_WAIT_SECONDS:-1800}"

[[ "$BASE_ROOT" == /var/lib/pgsql/xcmax-wal-pg16/base ]] || {
  echo "拒绝非标准 PostgreSQL 16 基线目录: $BASE_ROOT" >&2
  exit 2
}
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
install -d -m 0700 "$BASE_ROOT" "$STATE" "$(dirname "$LOG")"
docker exec -u postgres "$CONTAINER" \
  install -d -m 0700 -o postgres -g postgres \
  "/var/lib/postgresql/data/$ARCHIVE_NAME"
touch "$LOG"

# shellcheck source=../lib/wal_archive_command.sh
# shellcheck disable=SC1091
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../lib" &>/dev/null && pwd)/wal_archive_command.sh"
exec 9>"$LOCK"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

pg_show() {
  docker exec -u postgres "$CONTAINER" sh -ceu \
    'psql -U "$POSTGRES_USER" -d postgres -Atqc "SHOW $1"' sh "$1"
}

server_major="$(pg_show server_version | cut -d. -f1)"
[[ "$server_major" == "16" ]] || {
  log "ERROR: 预期 PostgreSQL 16，当前为 $(pg_show server_version)"
  exit 1
}

restart_required=0
if [[ "$(pg_show archive_mode)" != "on" ]]; then
  docker exec -u postgres "$CONTAINER" sh -ceu \
    'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -qc "ALTER SYSTEM SET archive_mode TO '\''on'\''"'
  restart_required=1
fi
archive_cmd="$(xcmax_wal_archive_command "/var/lib/postgresql/data/$ARCHIVE_NAME")"
escaped_archive_cmd="${archive_cmd//\'/\'\'}"
if [[ "$(pg_show archive_command)" != "$archive_cmd" ]]; then
  docker exec -u postgres "$CONTAINER" sh -ceu \
    'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -qc "$1"' sh \
    "ALTER SYSTEM SET archive_command TO '$escaped_archive_cmd'"
  restart_required=1
fi
if [[ "$(pg_show archive_timeout)" != "15min" ]]; then
  docker exec -u postgres "$CONTAINER" sh -ceu \
    'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -qc "ALTER SYSTEM SET archive_timeout TO '\''15min'\''"'
  restart_required=1
fi
if [[ "$restart_required" == "1" ]]; then
  log "重启 PostgreSQL 16 容器以启用 WAL 归档"
  docker restart -t 30 "$CONTAINER" >/dev/null
fi
deadline=$((SECONDS + 120))
while ((SECONDS < deadline)); do
  docker exec "$CONTAINER" pg_isready -q && break
  sleep 2
done
docker exec "$CONTAINER" pg_isready -q
[[ "$(pg_show archive_mode)" == "on" ]] || {
  log "ERROR: PostgreSQL 16 archive_mode 未生效"
  exit 1
}

system_id="$(
  docker exec -u postgres "$CONTAINER" sh -ceu \
    'psql -U "$POSTGRES_USER" -d postgres -Atqc "SELECT system_identifier FROM pg_control_system()"'
)"
superuser="$(
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" |
    sed -n 's/^POSTGRES_USER=//p'
)"
snapshot="$(date -u +%Y%m%dT%H%M%SZ)-$system_id"
container_staging="/tmp/xcmax-pg16-base-$snapshot"
staging="$BASE_ROOT/.staging-$snapshot"
final="$BASE_ROOT/$snapshot"
rm -rf -- "$staging"
install -d -m 0700 "$staging"
docker exec -u postgres "$CONTAINER" rm -rf -- "$container_staging"

log "创建 PostgreSQL 16 物理基础备份: $snapshot"
docker exec -u postgres "$CONTAINER" sh -ceu \
  'pg_basebackup -U "$POSTGRES_USER" -D "$1" -Ft -z -X stream -c fast' \
  sh "$container_staging"
docker cp "$CONTAINER:$container_staging/." "$staging/"
docker exec -u postgres "$CONTAINER" rm -rf -- "$container_staging"

{
  printf 'snapshot=%s\n' "$snapshot"
  printf 'created_at_epoch=%s\n' "$(date -u +%s)"
  printf 'server_version=%s\n' "$(pg_show server_version)"
  printf 'system_identifier=%s\n' "$system_id"
  printf 'database_superuser=%s\n' "$superuser"
} >"$staging/BASE_INFO"
(cd "$staging" && sha256sum ./*.tar.gz BASE_INFO >MANIFEST.txt)
touch "$staging/BASE_READY"
chmod -R go-rwx "$staging"
mv "$staging" "$final"

(
  flock -w "$TRANSFER_WAIT_SECONDS" 8 || exit 1
  rsync -a --partial --delay-updates \
    -e "ssh -i $KEY -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
    "$final/" "${TARGET}:${REMOTE_ROOT}/wal-pg16/base/${snapshot}/" >>"$LOG" 2>&1
) 8>"$TRANSFER_LOCK"
printf '%s\n' "$snapshot" >"$STATE/wal_pg16_base_last_snapshot"
date -u +%s >"$STATE/wal_pg16_base_last_success"

bash "$(dirname "$0")/xcmax_wal_ship_pg16.sh"
log "PostgreSQL 16 物理基础备份已推送: $snapshot"
