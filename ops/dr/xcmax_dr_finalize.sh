#!/usr/bin/env bash
# 温备接收端封存器：验证 incoming 备份，再复制为 receiver 无权改写的只读归档。
# 建议由 root cron 每 10 分钟运行；不会启动业务服务，也不会切换公网流量。

set -uo pipefail

INCOMING="${OPS_DR_INCOMING:-/srv/xcmax-dr/incoming}"
ARCHIVE="${OPS_DR_ARCHIVE:-/srv/xcmax-dr/archive}"
STATE="${OPS_DR_STATE:-/var/lib/xcmax-dr}"
LOG="${OPS_DR_LOG:-/var/log/xcmax-dr/finalize.log}"
KEEP="${OPS_DR_KEEP:-14}"
LOCK="/run/lock/xcmax-dr-finalize.lock"

safe_root() {
  local path="$1"
  [[ "$path" == /srv/xcmax-dr/* && "$path" != /srv/xcmax-dr/ ]]
}

if ! safe_root "$INCOMING" || ! safe_root "$ARCHIVE"; then
  echo "拒绝不安全目录: incoming=$INCOMING archive=$ARCHIVE" >&2
  exit 2
fi
if ! [[ "$KEEP" =~ ^[0-9]+$ ]] || ((KEEP < 1)); then
  echo "OPS_DR_KEEP 必须是正整数" >&2
  exit 2
fi

mkdir -p "$INCOMING" "$ARCHIVE" "$STATE" "$(dirname "$LOG")"
touch "$LOG"
chmod 700 "$ARCHIVE" "$STATE" "$(dirname "$LOG")"

exec 9>"$LOCK"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

validate_snapshot() {
  local src="$1"
  local required
  for required in MANIFEST.txt fhd_pg.dump modstore_pg.dump payment_pg.dump modstore_sqlite.db.gz configs.tar.gz; do
    [[ -s "$src/$required" ]] || {
      log "等待完整上传: $src 缺少 $required"
      return 1
    }
  done
  (cd "$src" && sha256sum -c MANIFEST.txt >/dev/null) || {
    log "校验失败: $src MANIFEST"
    return 1
  }
  local dump
  for dump in fhd_pg.dump modstore_pg.dump payment_pg.dump; do
    pg_restore --list "$src/$dump" >/dev/null 2>&1 || {
      log "校验失败: $src $dump"
      return 1
    }
  done
  gzip -t "$src/modstore_sqlite.db.gz" || {
    log "校验失败: $src SQLite gzip"
    return 1
  }
  tar -tzf "$src/configs.tar.gz" >/dev/null 2>&1 || {
    log "校验失败: $src configs tar"
    return 1
  }
}

finalize_snapshot() {
  local src="$1" day digest target staging
  day="$(basename "$src")"
  [[ "$day" =~ ^[0-9]{8}$ ]] || return 0
  validate_snapshot "$src" || return 0
  digest="$(sha256sum "$src/MANIFEST.txt" | awk '{print substr($1,1,12)}')"
  target="$ARCHIVE/${day}-${digest}"
  if [[ -d "$target" ]]; then
    return 0
  fi
  staging="$ARCHIVE/.staging-${day}-${digest}-$$"
  mkdir -m 700 "$staging"
  cp -a "$src/." "$staging/"
  (cd "$staging" && sha256sum -c MANIFEST.txt >/dev/null) || {
    rm -rf -- "$staging"
    log "封存后二次校验失败: $src"
    return 1
  }
  chown -R root:root "$staging"
  chmod -R go-rwx,a-w "$staging"
  mv "$staging" "$target"
  ln -sfn "$target" "$ARCHIVE/latest"
  date -u +%s > "$STATE/last_success"
  log "封存成功: $target"
}

while IFS= read -r -d '' src; do
  finalize_snapshot "$src"
done < <(find "$INCOMING" -mindepth 1 -maxdepth 1 -type d -name '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]' -print0)

mapfile -t snapshots < <(
  find "$ARCHIVE" -mindepth 1 -maxdepth 1 -type d \
    -name '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-*' -printf '%p\n' |
    sort -r
)
if ((${#snapshots[@]} > KEEP)); then
  for victim in "${snapshots[@]:KEEP}"; do
    [[ "$victim" == "$ARCHIVE/"* ]] || continue
    rm -rf -- "$victim"
    log "轮转清理: $victim"
  done
fi

# incoming 也只保留有限的日期目录；非日期目录（如受校验的运行包）不触碰。
mapfile -t incoming_snapshots < <(
  find "$INCOMING" -mindepth 1 -maxdepth 1 -type d \
    -name '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]' -printf '%p\n' |
    sort -r
)
if ((${#incoming_snapshots[@]} > KEEP)); then
  for victim in "${incoming_snapshots[@]:KEEP}"; do
    [[ "$victim" == "$INCOMING/"* ]] || continue
    rm -rf -- "$victim"
    log "incoming 轮转清理: $victim"
  done
fi
