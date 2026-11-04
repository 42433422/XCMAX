#!/usr/bin/env bash
# Nightly FHD/Modstore/payment and configuration snapshots; daily UTC directories rotate locally and may copy offsite.
# Each MANIFEST covers only the artifacts produced by that run; stale files remain untouched and unlisted.
# PostgreSQL, SQLite, gzip and tar artifacts are validated before publishing the manifest.
# Runtime options and defaults are in ops/env.example; use xcmax_backup.sh [--dry-run].

set -uo pipefail

OPS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")/.." &>/dev/null && pwd)"
NOTIFY="python3 ${OPS_ROOT}/lib/notify.py"

BACKUP_DIR="${OPS_BACKUP_DIR:-/var/backups/xcmax}"
FHD_ENV="${OPS_FHD_ENV:-/root/fhd-full.env}"
MODSTORE_ENV="${OPS_MODSTORE_ENV:-/etc/xcmax/modstore.env}"
MODSTORE_DIR="${OPS_MODSTORE_DIR:-/root/XCMAX/成都修茈科技有限公司/MODstore_deploy}"
MODSTORE_DB="${OPS_MODSTORE_DB:-${MODSTORE_DIR}/modstore.db}"
LOG_DIR="${OPS_LOG_DIR:-/var/log/xcmax-ops}"
LOG="${LOG_DIR}/backup.log"
LOCK="/tmp/xcmax-backup.lock"
TRANSFER_LOCK="${OPS_DR_TRANSFER_LOCK:-/run/lock/xcmax-dr-transfer.lock}"
TRANSFER_WAIT_SECONDS="${OPS_DR_TRANSFER_WAIT_SECONDS:-1800}"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1
RELEASE_TARGET_SHA=""
if [[ "${1:-}" == "--modstore-release" ]]; then
  [[ $# == 2 && "$2" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: $0 --modstore-release <40-char-main-sha>" >&2; exit 64; }
  RELEASE_TARGET_SHA="$2"
fi
BACKUP_TOOL_VERSION=""

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  if ! flock -n 9; then
    log "另一实例运行中，发布快照中止"
    [[ -z "$RELEASE_TARGET_SHA" ]] && exit 0 || exit 1
  fi
fi

FAILURES=()
fail() {
  FAILURES+=("$1")
  log "ERROR: $1"
}

TODAY="$(date -u +%Y%m%d)"

# ----------------------------------------------------------- PostgreSQL
extract_database_url() {
  local env_file="$1" key="$2" inject_credentials="${3:-0}"
  python3 - "$env_file" "$key" "$inject_credentials" <<'PY'
import re
import sys
from urllib.parse import quote, urlsplit, urlunsplit

values = {}
with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    for raw in fh:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

url = values.get(sys.argv[2], "")
if url.startswith("jdbc:"):
    url = url[5:]
# SQLAlchemy 方言后缀 pg_dump 不认识（postgresql+psycopg:// → postgresql://）
url = re.sub(r"^postgres(ql)?\+[a-z0-9_]+://", "postgresql://", url)
if url and sys.argv[3] == "1":
    parsed = urlsplit(url)
    if parsed.username is None:
        user = values.get("DATABASE_USER", "")
        password = values.get("DATABASE_PASSWORD", "")
        if user:
            credentials = quote(user, safe="")
            if password:
                credentials += ":" + quote(password, safe="")
            hostname = parsed.hostname or ""
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            host = hostname + (f":{parsed.port}" if parsed.port else "")
            url = urlunsplit(
                (parsed.scheme, f"{credentials}@{host}", parsed.path, parsed.query, parsed.fragment)
            )
print(url)
PY
}

backup_pg_url() {
  local label="$1" filename="$2" url="$3" policy="${4:-default}" out="$DEST/$2"
  [[ "$DRY_RUN" == 1 ]] && { log "[dry-run] 将导出 $label PostgreSQL → $filename（URL 已脱敏）"; return; }
  local pg_image="${OPS_PG_DUMP_CONTAINER_IMAGE:-}"
  [[ "$policy" == payment ]] && pg_image="${OPS_PAYMENT_PG_DUMP_CONTAINER_IMAGE:-}"
  if [[ "$policy" == payment || "$policy" == release ]]; then
    local server_version client_version server_major client_major restore_version restore_major
    command -v psql >/dev/null 2>&1 || { fail "$label 无法检查数据库版本：缺少 psql"; return; }
    server_version="$(psql --no-password "$url" -XAtc 'show server_version_num' 2>>"$LOG")" || { fail "$label 无法读取 PostgreSQL 服务端版本"; return; }
    if [[ -n "$pg_image" ]]; then
      command -v docker >/dev/null 2>&1 || { fail "$label 已配置支付导出镜像但 docker 不可用"; return; }
      client_version="$(docker run --rm --network none --entrypoint pg_dump "$pg_image" --version 2>>"$LOG")" || { fail "$label 无法读取支付导出镜像版本"; return; }
      restore_version="$(docker run --rm --network none --entrypoint pg_restore "$pg_image" --version 2>>"$LOG")" || { fail "$label 无法读取归档校验镜像版本"; return; }
    else
      command -v pg_dump >/dev/null 2>&1 && command -v pg_restore >/dev/null 2>&1 || { fail "$label 缺少匹配的 pg_dump/pg_restore 或 OPS_PAYMENT_PG_DUMP_CONTAINER_IMAGE"; return; }
      client_version="$(pg_dump --version 2>>"$LOG")" || { fail "$label 无法读取支付导出客户端版本"; return; }
      restore_version="$(pg_restore --version 2>>"$LOG")" || { fail "$label 无法读取归档校验客户端版本"; return; }
    fi
    client_version="${client_version##* }"
    [[ "$server_version" =~ ^[0-9]+$ ]] || { fail "$label 返回了无效的 PostgreSQL 服务端版本"; return; }
    if (( server_version >= 100000 )); then server_major=$((server_version / 10000)); else server_major="$((server_version / 10000)).$(((server_version / 100) % 100))"; fi
    if [[ "$client_version" == 9.* ]]; then client_major="$(cut -d. -f1-2 <<<"$client_version")"; else client_major="${client_version%%.*}"; fi
    [[ "$client_major" == "$server_major" ]] || { fail "$label 导出客户端版本 $client_major 与数据库版本 $server_major 不匹配"; return; }
    if [[ "$policy" == release ]]; then
      restore_version="${restore_version##* }"
      restore_major="${restore_version%%.*}"
      [[ "$restore_major" == "$server_major" ]] || { fail "$label 归档校验客户端版本 $restore_major 与数据库版本 $server_major 不匹配"; return; }
      BACKUP_TOOL_VERSION="pg_dump $client_version; pg_restore $restore_version; PostgreSQL $server_major"
    fi
  fi
  if [[ -n "$pg_image" ]]; then
    printf '%s\n' "$url" | docker run --rm -i --network host --entrypoint sh "$pg_image" -ceu 'IFS= read -r url; exec pg_dump --no-password -Fc -d "$url"' >"$out" 2>>"$LOG" || { fail "$label pg_dump 失败（容器镜像 $pg_image）"; return; }
    docker run --rm -i --network none --entrypoint pg_restore "$pg_image" --list <"$out" >/dev/null 2>>"$LOG" || { fail "$filename 验证失败（容器 pg_restore --list）"; return; }
  elif command -v pg_dump >/dev/null 2>&1; then
    pg_dump --no-password -Fc -d "$url" -f "$out" 2>>"$LOG" || { fail "$label pg_dump 失败（本机客户端）"; return; }
    command -v pg_restore >/dev/null 2>&1 && pg_restore --list "$out" >/dev/null 2>>"$LOG" || { fail "$filename pg_restore --list 验证失败"; return; }
  else
    local container="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -im1 postgres || true)"
    [[ -n "$container" ]] || { fail "$label 缺少 pg_dump 且没有可用 Postgres 容器"; return; }
    docker exec "$container" pg_dump -Fc -d "$url" >"$out" 2>>"$LOG" || { fail "$label pg_dump 失败（容器 $container）"; return; }
    docker exec "$container" pg_restore --list "$out" >/dev/null 2>>"$LOG" || { fail "$filename 容器 pg_restore --list 验证失败"; return; }
  fi
  log "$label PG 备份完成: $(du -h "$out" | cut -f1)"
}

backup_fhd_pg() {
  if [[ ! -f "$FHD_ENV" ]]; then
    fail "FHD env 不存在: $FHD_ENV（无法取 DATABASE_URL）"
    return
  fi
  local url
  url="$(extract_database_url "$FHD_ENV" DATABASE_URL)"
  if [[ -z "$url" ]]; then
    fail "未在 $FHD_ENV 找到 DATABASE_URL"
    return
  fi
  if [[ "$url" == sqlite* ]]; then
    log "FHD DATABASE_URL 是 sqlite，按文件备份"
    local db_file="${url#sqlite:///}"
    if [[ -f "$db_file" && "$DRY_RUN" != "1" ]]; then
      gzip -c "$db_file" > "$DEST/fhd_sqlite.db.gz" || fail "FHD sqlite 备份失败"
    fi
    return
  fi
  backup_pg_url "FHD" "fhd_pg.dump" "$url"
}

backup_modstore_pg() {
  if [[ ! -f "$MODSTORE_ENV" ]]; then
    fail "MODstore env 不存在: $MODSTORE_ENV"
    return
  fi
  local modstore_url payment_url
  modstore_url="$(extract_database_url "$MODSTORE_ENV" DATABASE_URL)"
  payment_url="$(extract_database_url "$MODSTORE_ENV" JAVA_DATABASE_URL 1)"
  if [[ -z "$modstore_url" ]]; then
    fail "未在 $MODSTORE_ENV 找到 DATABASE_URL"
  else
    backup_pg_url "MODstore" "modstore_pg.dump" "$modstore_url" "${RELEASE_TARGET_SHA:+release}"
  fi
  [[ -n "$RELEASE_TARGET_SHA" ]] && return
  if [[ -z "$payment_url" ]]; then
    fail "未在 $MODSTORE_ENV 找到 JAVA_DATABASE_URL"
  else
    backup_pg_url "支付服务" "payment_pg.dump" "$payment_url" payment
  fi
}

# ------------------------------------------------------------- MODstore
backup_modstore_sqlite() {
  local db="$MODSTORE_DB"
  if [[ ! -f "$db" ]]; then
    # 常见变体：instance/ 或 data/ 下
    db="$(find "$MODSTORE_DIR" -maxdepth 2 -name 'modstore.db' -type f 2>/dev/null | head -1 || true)"
  fi
  if [[ -z "$db" || ! -f "$db" ]]; then
    fail "未找到 MODstore SQLite（找过 $MODSTORE_DB 与 $MODSTORE_DIR 下两层）"
    return
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] 将备份 SQLite: $db"
    return
  fi
  local snap="$DEST/modstore_sqlite.db"
  if ! python3 - "$db" "$snap" <<'PY' 2>>"$LOG"; then
import sqlite3, sys
src = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True, timeout=30)
dst = sqlite3.connect(sys.argv[2])
if hasattr(src, "backup"):  # py3.7+ 在线一致性快照
    with dst:
        src.backup(dst)
else:  # py3.6 退路：只读连接逐语句导出
    dst.executescript("".join(src.iterdump()))
row = dst.execute("PRAGMA quick_check").fetchone()
src.close(); dst.close()
if row and row[0] != "ok":
    raise SystemExit("quick_check: %s" % row[0])
PY
    fail "MODstore SQLite 备份/校验失败: $db"
    return
  fi
  gzip -f "$snap" || { fail "gzip modstore_sqlite 失败"; return; }
  log "MODstore SQLite 备份完成: $(du -h "$snap.gz" | cut -f1)（源 $db）"
}

# --------------------------------------------------------------- configs
backup_configs() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] 将打包配置 tarball"
    return
  fi
  local staging
  staging="$(mktemp -d /tmp/xcmax-cfg.XXXXXX)"
  # 逐项复制（缺哪个不算错，生产布局在演进）
  local items=(
    "/root/fhd-full.env"
    "${MODSTORE_DIR}/.env"
    "/etc/xcmax"
    "/etc/nginx"
    "/etc/xcmax-ops.env"
    "/etc/cron.d/xcmax-ops"
    "/var/www/update/releases/stable/server/fhd-manifest.json"
  )
  for item in "${items[@]}"; do
    if [[ -e "$item" ]]; then
      mkdir -p "$staging$(dirname "$item")"
      cp -a "$item" "$staging$(dirname "$item")/" 2>>"$LOG" || true
    fi
  done
  mkdir -p "$staging/etc/systemd/system"
  local unit
  for unit in fhd-full modstore modstore-scheduler modstore-payment fhd-sandbox; do
    [[ -f "/etc/systemd/system/${unit}.service" ]] \
      && cp -a "/etc/systemd/system/${unit}.service" "$staging/etc/systemd/system/"
    if [[ -d "/etc/systemd/system/${unit}.service.d" ]]; then
      cp -a "/etc/systemd/system/${unit}.service.d" "$staging/etc/systemd/system/"
    fi
  done
  crontab -l > "$staging/root-crontab.txt" 2>/dev/null || true
  # 额外路径（如上传目录）——调用方自己对大小负责
  for extra in ${OPS_BACKUP_EXTRA:-}; do
    if [[ -e "$extra" ]]; then
      mkdir -p "$staging$(dirname "$extra")"
      cp -a "$extra" "$staging$(dirname "$extra")/" 2>>"$LOG" || true
    fi
  done
  if ! tar -czf "$DEST/configs.tar.gz" -C "$staging" . 2>>"$LOG"; then
    fail "configs.tar.gz 打包失败"
  elif ! tar -tzf "$DEST/configs.tar.gz" >/dev/null 2>&1; then
    fail "configs.tar.gz 验证失败"
  else
    chmod 600 "$DEST/configs.tar.gz"
    log "配置备份完成: $(du -h "$DEST/configs.tar.gz" | cut -f1)"
  fi
  rm -rf "$staging"
}

# ---------------------------------------------------------- 轮转 + 异地
write_manifest() {
  [[ "$DRY_RUN" == "1" ]] && return
  local -a files=(modstore_pg.dump payment_pg.dump modstore_sqlite.db.gz configs.tar.gz)
  if [[ -s "$DEST/fhd_pg.dump" ]]; then
    files+=(fhd_pg.dump)
  elif [[ -s "$DEST/fhd_sqlite.db.gz" ]]; then
    files+=(fhd_sqlite.db.gz)
  else
    fail "FHD backup output missing"
    return 1
  fi
  local pending="$DEST/MANIFEST.txt.tmp"
  if ! (cd "$DEST" && sha256sum "${files[@]}" > "$pending") ||
    ! mv -f "$pending" "$DEST/MANIFEST.txt"; then
    fail "MANIFEST generation failed"
    return 1
  fi
}

backup_modstore_release() {
  DEST="${BACKUP_DIR}/modstore-release/${RELEASE_TARGET_SHA}/$(date -u +%Y%m%dT%H%M%SZ)-$$"
  mkdir -p "$(dirname "$DEST")" && mkdir "$DEST" || { fail "MODstore snapshot path unavailable"; return 1; }
  chmod 700 "$BACKUP_DIR" "$(dirname "$DEST")" "$DEST" 2>/dev/null || true
  backup_modstore_pg
  [[ ${#FAILURES[@]} == 0 ]] || return 1
  (cd "$DEST" && sha256sum modstore_pg.dump > MANIFEST.txt && sha256sum -c MANIFEST.txt >/dev/null) \
    || { fail "MODstore release manifest/hash validation failed"; return 1; }
  (umask 077; printf 'scope=modstore-postgres\ntarget_sha=%s\ncreated_at=%s\ntool_versions=%s\narchive_validation=pg_restore --list passed\n' \
    "$RELEASE_TARGET_SHA" "$(date -u +%FT%TZ)" "$BACKUP_TOOL_VERSION" > "$DEST/release-backup.txt") \
    || { fail "MODstore release receipt could not be written"; return 1; }
  log "MODstore pre-migration snapshot validated: target=$RELEASE_TARGET_SHA dir=$DEST tools=$BACKUP_TOOL_VERSION"
}

rotate() {
  [[ "$DRY_RUN" == "1" ]] && return
  local weekly="${BACKUP_DIR}/weekly" monthly="${BACKUP_DIR}/monthly"
  mkdir -p "$weekly" "$monthly"
  # 周日 → weekly；1 号 → monthly（复制当日目录）
  if [[ "$(date -u +%u)" == "7" && ! -e "$weekly/$TODAY" ]]; then
    cp -a "$DEST" "$weekly/$TODAY" 2>>"$LOG" || fail "weekly 轮转复制失败"
  fi
  if [[ "$(date -u +%d)" == "01" && ! -e "$monthly/$TODAY" ]]; then
    cp -a "$DEST" "$monthly/$TODAY" 2>>"$LOG" || fail "monthly 轮转复制失败"
  fi
  # 只清理形如 8 位日期的目录，防手滑
  prune() {
    local dir="$1" keep="$2"
    ls -1d "$dir"/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null \
      | sort -r | tail -n "+$((keep + 1))" | while read -r victim; do
        rm -rf "$victim"
        log "轮转清理: $victim"
      done
  }
  prune "${BACKUP_DIR}/daily" 7
  prune "$weekly" 4
  prune "$monthly" 6
}

offsite_cos() {
  [[ "$DRY_RUN" == "1" ]] && return
  local bucket="${OPS_COS_BUCKET:-}"
  if [[ -z "$bucket" ]]; then
    log "未配置 OPS_COS_BUCKET，跳过异地上传（建议尽快配置，见 ops/README.md）"
    return
  fi
  if ! command -v coscmd >/dev/null 2>&1; then
    fail "OPS_COS_BUCKET 已设但 coscmd 未安装（pip3 install coscmd 并 coscmd config）"
    return
  fi
  if coscmd -b "$bucket" upload -rs "$DEST" "xcmax-backup/daily/${TODAY}/" >>"$LOG" 2>&1; then
    date -u +%s > "${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state/offsite_last_success" 2>/dev/null || true
    log "COS 异地上传完成 → $bucket/xcmax-backup/daily/${TODAY}/"
  else
    fail "COS 上传失败（bucket=$bucket）"
  fi
}

offsite_ssh() {
  [[ "$DRY_RUN" == "1" ]] && return
  local target="${OPS_BACKUP_SSH_TARGET:-}"
  [[ -z "$target" ]] && return
  local key="${OPS_BACKUP_SSH_KEY:-/root/.ssh/xcmax_dr_ed25519}"
  local remote_root="${OPS_BACKUP_SSH_DEST:-.}"
  if [[ ! -f "$key" ]]; then
    fail "温备 SSH 私钥不存在: $key"
    return
  fi
  if ! command -v rsync >/dev/null 2>&1; then
    fail "温备推送需要 rsync"
    return
  fi
  if (
    flock -w "$TRANSFER_WAIT_SECONDS" 8 || exit 1
    rsync -a --partial \
      -e "ssh -i $key -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
      "$DEST/" "${target}:${remote_root}/${TODAY}/" >>"$LOG" 2>&1
  ) 8>"$TRANSFER_LOCK"; then
    date -u +%s > "${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state/offsite_ssh_last_success" \
      2>/dev/null || true
    log "SSH 异地推送完成 → ${target}:${remote_root}/${TODAY}/"
  else
    fail "SSH 异地推送失败（target=$target）"
  fi
}

# ------------------------------------------------------------------ main
log "===== 备份开始 (dry-run=$DRY_RUN) ====="
if [[ -n "$RELEASE_TARGET_SHA" ]]; then
  backup_modstore_release || exit 1
  exit 0
fi

DEST="${BACKUP_DIR}/daily/${TODAY}"
if [[ "$DRY_RUN" == "1" ]]; then
  log "[dry-run] 目标目录: $DEST"
else
  mkdir -p "$DEST"
  chmod 700 "$BACKUP_DIR" "$BACKUP_DIR/daily" "$DEST" 2>/dev/null || true
  # 同日重跑先撤销旧清单；只有本轮所有产物成功后才重新发布。
  rm -f "$DEST/MANIFEST.txt"
fi

backup_fhd_pg
backup_modstore_pg
backup_modstore_sqlite
backup_configs

if [[ ${#FAILURES[@]} -eq 0 ]]; then
  if write_manifest; then rotate; offsite_ssh; offsite_cos; fi
else
  log "备份产物存在失败，跳过 MANIFEST、轮转和异地推送"
fi

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  body="$(printf '%s\n' "${FAILURES[@]}")"
  log "备份存在 ${#FAILURES[@]} 处失败"
  if [[ "$DRY_RUN" != "1" ]]; then
    $NOTIFY --level crit --title "夜间备份失败 ${#FAILURES[@]} 项" \
      --body "$body

产物目录: $DEST
日志: $LOG" || true
  fi
  exit 1
fi

if [[ "$DRY_RUN" != "1" ]]; then
  mkdir -p "${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state"
  date -u +%s > "${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state/backup_last_success"
fi
log "===== 备份成功 ====="
exit 0
