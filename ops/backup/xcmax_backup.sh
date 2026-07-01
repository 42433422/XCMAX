#!/usr/bin/env bash
# XCMAX 夜间备份：FHD PostgreSQL + MODstore SQLite + 关键配置 → 本地轮转 + 可选 COS 异地。
#
# 产物（/var/backups/xcmax/daily/<UTC日期>/）：
#   fhd_pg.dump          pg_dump -Fc（自带压缩，可 pg_restore 单库恢复）
#   modstore_sqlite.db.gz  SQLite 在线备份（sqlite3 backup API，不脏读）
#   configs.tar.gz       /root/fhd-full.env、MODstore .env、nginx、systemd 单元、crontab（0600，含秘密）
#   MANIFEST.txt         各产物 sha256 与字节数
#
# 轮转：daily 保 7 份；每周日复制到 weekly/ 保 4 份；每月 1 号复制到 monthly/ 保 6 份。
# 异地：装了 coscmd 且设置 OPS_COS_BUCKET 时上传当日目录（腾讯云 COS）。
# 验证：pg_restore --list、gzip -t、tar -tzf、sqlite PRAGMA quick_check 全过才算成功。
# 失败：任何一步失败 → notify.py 发 crit 告警（哨兵还有 26h 新鲜度兜底）。
#
# 环境（/etc/xcmax-ops.env，由 cron 行 source）：
#   OPS_BACKUP_DIR      默认 /var/backups/xcmax
#   OPS_FHD_ENV         默认 /root/fhd-full.env（取 DATABASE_URL）
#   OPS_MODSTORE_DIR    默认 /root/XCMAX/成都修茈科技有限公司/MODstore_deploy
#   OPS_MODSTORE_DB     默认 $OPS_MODSTORE_DIR/modstore.db（可显式指定）
#   OPS_COS_BUCKET      可选，如 xcmax-backup-1250000000
#   OPS_BACKUP_EXTRA    可选，空格分隔的额外备份路径（如上传目录）
#
# 用法：xcmax_backup.sh [--dry-run]

set -uo pipefail

OPS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
NOTIFY="python3 ${OPS_ROOT}/lib/notify.py"

BACKUP_DIR="${OPS_BACKUP_DIR:-/var/backups/xcmax}"
FHD_ENV="${OPS_FHD_ENV:-/root/fhd-full.env}"
MODSTORE_DIR="${OPS_MODSTORE_DIR:-/root/XCMAX/成都修茈科技有限公司/MODstore_deploy}"
MODSTORE_DB="${OPS_MODSTORE_DB:-${MODSTORE_DIR}/modstore.db}"
LOG_DIR="${OPS_LOG_DIR:-/var/log/xcmax-ops}"
LOG="${LOG_DIR}/backup.log"
LOCK="/tmp/xcmax-backup.lock"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  if ! flock -n 9; then
    log "另一实例运行中，跳过"
    exit 0
  fi
fi

FAILURES=()
fail() {
  FAILURES+=("$1")
  log "ERROR: $1"
}

TODAY="$(date -u +%Y%m%d)"
DEST="${BACKUP_DIR}/daily/${TODAY}"

if [[ "$DRY_RUN" == "1" ]]; then
  log "[dry-run] 目标目录: $DEST"
else
  mkdir -p "$DEST"
  chmod 700 "$BACKUP_DIR" "$BACKUP_DIR/daily" "$DEST" 2>/dev/null || true
fi

# ---------------------------------------------------------------- FHD PG
backup_fhd_pg() {
  if [[ ! -f "$FHD_ENV" ]]; then
    fail "FHD env 不存在: $FHD_ENV（无法取 DATABASE_URL）"
    return
  fi
  local url
  url="$(python3 - "$FHD_ENV" <<'PY'
import re, sys
url = ""
with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        m = re.match(r"DATABASE_URL=[\"']?([^\"']+)[\"']?$", line)
        if m:
            url = m.group(1)
# SQLAlchemy 方言后缀 pg_dump 不认识（postgresql+psycopg:// → postgresql://）
url = re.sub(r"^postgres(ql)?\+[a-z0-9]+://", "postgresql://", url)
print(url)
PY
)"
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
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] 将执行 pg_dump -Fc（URL 已脱敏）"
    return
  fi
  local out="$DEST/fhd_pg.dump"
  if command -v pg_dump >/dev/null 2>&1; then
    if ! pg_dump --no-password -Fc -d "$url" -f "$out" 2>>"$LOG"; then
      fail "pg_dump 失败（本机客户端）"
      return
    fi
  else
    # 没装 pg 客户端：尝试用 postgres 容器内的 pg_dump
    local container
    container="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -im1 postgres || true)"
    if [[ -z "$container" ]]; then
      fail "pg_dump 不可用且未发现 postgres 容器——装 postgresql-client 或设 OPS_PG_CONTAINER"
      return
    fi
    if ! docker exec "$container" pg_dump -Fc -d "$url" > "$out" 2>>"$LOG"; then
      fail "pg_dump 失败（容器 $container）"
      return
    fi
  fi
  # 验证：能列出目录才算真备份
  if command -v pg_restore >/dev/null 2>&1; then
    if ! pg_restore --list "$out" >/dev/null 2>>"$LOG"; then
      fail "fhd_pg.dump 验证失败（pg_restore --list）"
      return
    fi
  fi
  log "FHD PG 备份完成: $(du -h "$out" | cut -f1)"
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
  (cd "$DEST" && sha256sum ./* 2>/dev/null | grep -v MANIFEST > MANIFEST.txt) || true
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

# ------------------------------------------------------------------ main
log "===== 备份开始 (dry-run=$DRY_RUN) ====="
backup_fhd_pg
backup_modstore_sqlite
backup_configs
write_manifest
rotate
offsite_cos

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
