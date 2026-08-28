#!/usr/bin/env bash
# Bound DR disk use without deleting the active runtime or WAL needed by standby.

set -euo pipefail

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
INCOMING="${OPS_DR_INCOMING:-$DR_ROOT/incoming}"
RELEASES="${OPS_DR_RELEASES:-$DR_ROOT/releases}"
RUNTIME="${OPS_DR_RUNTIME:-$DR_ROOT/runtime}"
STATE="${OPS_DR_STATE:-/var/lib/xcmax-dr}"
LOG="${OPS_DR_STORAGE_LOG:-/var/log/xcmax-dr/storage-retention.log}"
LOCK="${OPS_DR_STORAGE_LOCK:-/run/lock/xcmax-dr-storage-retention.lock}"
RELEASE_KEEP="${OPS_DR_RUNTIME_RELEASE_KEEP:-4}"
BASE_KEEP="${OPS_DR_BASE_KEEP:-2}"
WAL_KEEP_MIN="${OPS_DR_WAL_KEEP_MIN_SEGMENTS:-16}"
WAL_PREVIOUS_KEEP="${OPS_DR_WAL_PREVIOUS_KEEP:-2}"
TEST_MODE="${XCMAX_DR_RETENTION_TEST_MODE:-0}"

if [[ "$TEST_MODE" != "1" && "${EUID}" != "0" ]]; then
  echo "请以 root 运行" >&2
  exit 2
fi
if [[ "$DR_ROOT" != "/srv/xcmax-dr" ]]; then
  [[ "$TEST_MODE" == "1" && "$DR_ROOT" == /tmp/xcmax-dr-retention-test.* ]] || {
    echo "拒绝非标准 DR 根目录: $DR_ROOT" >&2
    exit 2
  }
fi
for value in "$RELEASE_KEEP" "$BASE_KEEP" "$WAL_KEEP_MIN" "$WAL_PREVIOUS_KEEP"; do
  [[ "$value" =~ ^[0-9]+$ && "$value" -ge 1 ]] || {
    echo "DR retention values must be positive integers" >&2
    exit 2
  }
done
[[ "$INCOMING" == "$DR_ROOT/incoming" && "$RELEASES" == "$DR_ROOT/releases" ]] || {
  echo "拒绝非标准 DR 存储布局" >&2
  exit 2
}

install -d -m 0700 "$STATE" "$(dirname "$LOG")"
touch "$LOG"
exec 9>"$LOCK"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

# Never race the restricted receiver. The next cron pass will prune after it exits.
if [[ "$TEST_MODE" != "1" ]] &&
  { pgrep -u xcmaxdr -x rsync >/dev/null 2>&1 ||
    pgrep -u xcmaxdr -f '/rrsync([[:space:]]|$)' >/dev/null 2>&1; }; then
  log "接收端传输进行中，跳过本轮存储轮转"
  exit 0
fi

declare -A protected_shas=()
protect_sha() {
  local value="${1:-}"
  [[ "$value" =~ ^[0-9a-f]{40}$ ]] && protected_shas["$value"]=1
}
for state_file in \
  "$STATE/release_applied_modstore_sha" \
  "$STATE/release_applied_fhd_sha"; do
  [[ -s "$state_file" ]] && protect_sha "$(cat "$state_file")"
done
for runtime_path in "$RUNTIME/source" "$RUNTIME/fhd"; do
  if [[ -e "$runtime_path" || -L "$runtime_path" ]]; then
    target="$(readlink -f "$runtime_path" 2>/dev/null || true)"
    [[ "$target" == "$RELEASES/"* ]] && protect_sha "$(basename "$(dirname "$target")")"
  fi
done

removed_dirs=0
removed_wal=0
removed_bytes=0

remove_tree() {
  local root="$1" victim="$2" size=0
  [[ "$victim" == "$root/"* && -d "$victim" && ! -L "$victim" ]] || return 1
  size="$(du -sk "$victim" 2>/dev/null | awk '{print $1 * 1024}' || true)"
  rm -rf -- "$victim"
  removed_dirs=$((removed_dirs + 1))
  removed_bytes=$((removed_bytes + ${size:-0}))
}

prune_previous_tree() {
  local root="$DR_ROOT/wal" prefix="$1" index=0 path
  [[ -d "$root" ]] || return 0
  while IFS= read -r path; do
    index=$((index + 1))
    ((index <= WAL_PREVIOUS_KEEP)) && continue
    [[ "$path" == "$root/${prefix}.previous-"* ]] || continue
    remove_tree "$root" "$path"
  done < <(
    find "$root" -mindepth 1 -maxdepth 1 -type d \
      -name "${prefix}.previous-*" -printf '%T@ %p\n' |
      sort -nr | cut -d' ' -f2-
  )
}

prune_release_tree() {
  local root="$1" index=0 sha path
  [[ -d "$root" ]] || return 0
  while IFS= read -r path; do
    sha="$(basename "$path")"
    [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || continue
    index=$((index + 1))
    ((index <= RELEASE_KEEP)) && continue
    [[ -n "${protected_shas[$sha]:-}" ]] && continue
    remove_tree "$root" "$path"
  done < <(
    find "$root" -mindepth 1 -maxdepth 1 -type d \
      -regextype posix-extended -regex '.*/[0-9a-f]{40}' \
      -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-
  )
}

prune_base_tree() {
  local root="$1" applied_file="$2" applied="" index=0 name path
  [[ -d "$root" ]] || return 0
  [[ -s "$applied_file" ]] && applied="$(cat "$applied_file")"
  while IFS= read -r path; do
    name="$(basename "$path")"
    [[ "$name" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || continue
    index=$((index + 1))
    ((index <= BASE_KEEP)) && continue
    [[ "$name" == "$applied" ]] && continue
    remove_tree "$root" "$path"
  done < <(
    find "$root" -mindepth 1 -maxdepth 1 -type d -name '*Z-*' \
      -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-
  )
}

prune_wal_before_applied_base() {
  local stream="$1" applied_file="$2" archive base snapshot created cutoff
  local index=0 path mtime size
  archive="$INCOMING/$stream/archive"
  [[ -d "$archive" && -s "$applied_file" ]] || return 0
  snapshot="$(cat "$applied_file")"
  base="$INCOMING/$stream/base/$snapshot"
  [[ -e "$base/BASE_READY" && -s "$base/BASE_INFO" ]] || return 0
  created="$(sed -n 's/^created_at_epoch=//p' "$base/BASE_INFO" | tail -1)"
  [[ "$created" =~ ^[0-9]+$ ]] || return 0
  cutoff=$((created - 3600))

  while IFS= read -r path; do
    index=$((index + 1))
    ((index <= WAL_KEEP_MIN)) && continue
    mtime="$(stat -c %Y "$path")"
    ((mtime < cutoff)) || continue
    size="$(stat -c %s "$path")"
    rm -f -- "$path"
    removed_wal=$((removed_wal + 1))
    removed_bytes=$((removed_bytes + size))
  done < <(
    find "$archive" -maxdepth 1 -type f \
      -regextype posix-extended -regex '.*/[0-9A-F]{24}' \
      -printf '%f %p\n' | sort -r | cut -d' ' -f2-
  )
}

replay_segment_for_stream() {
  local stream="$1" container="$2" user="$3" archive=""
  local override="" replay_info="" timeline="" lsn="" newest="" segment_size=""
  archive="$INCOMING/$stream/archive"
  if [[ "$stream" == "wal" ]]; then
    override="${OPS_DR_WAL_REPLAY_SEGMENT:-}"
  else
    override="${OPS_DR_WAL_PG16_REPLAY_SEGMENT:-}"
  fi
  if [[ -n "$override" ]]; then
    [[ "$override" =~ ^[0-9A-F]{24}$ ]] || {
      echo "invalid replay WAL segment for $stream: $override" >&2
      return 2
    }
    printf '%s\n' "$override"
    return 0
  fi
  [[ "$TEST_MODE" != "1" ]] || return 0
  docker inspect "$container" >/dev/null 2>&1 || return 0
  [[ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null)" == "true" ]] ||
    return 0
  replay_info="$(
    docker exec -u postgres "$container" \
      psql -U "$user" -d postgres -Atqc \
      "SELECT timeline_id || '|' || COALESCE(pg_last_wal_replay_lsn()::text, '') FROM pg_control_checkpoint()" \
      2>/dev/null || true
  )"
  timeline="${replay_info%%|*}"
  lsn="${replay_info#*|}"
  [[ "$timeline" =~ ^[0-9]+$ && "$lsn" =~ ^[0-9A-F]+/[0-9A-F]+$ ]] || return 0
  newest="$(
    find "$archive" -maxdepth 1 -type f \
      -regextype posix-extended -regex '.*/[0-9A-F]{24}' -printf '%f %p\n' |
      LC_ALL=C sort | tail -1
  )"
  [[ -n "$newest" ]] || return 0
  segment_size="$(stat -c %s "${newest#* }")"
  python3 - "$timeline" "$lsn" "$segment_size" <<'PY'
import sys

timeline = int(sys.argv[1])
high_hex, low_hex = sys.argv[2].split("/", 1)
segment_size = int(sys.argv[3])
if segment_size <= 0 or (1 << 32) % segment_size:
    raise SystemExit("invalid WAL segment size")
high = int(high_hex, 16)
low = int(low_hex, 16)
print(f"{timeline:08X}{high:08X}{low // segment_size:08X}")
PY
}

prune_wal_before_replay() {
  local stream="$1" replay_segment="$2" archive=""
  local index=0 path name size
  archive="$INCOMING/$stream/archive"
  [[ -d "$archive" && -n "$replay_segment" ]] || return 0
  [[ "$replay_segment" =~ ^[0-9A-F]{24}$ ]] || return 2
  while IFS= read -r path; do
    index=$((index + 1))
    ((index <= WAL_KEEP_MIN)) && continue
    name="$(basename "$path")"
    [[ "$name" < "$replay_segment" ]] || continue
    size="$(stat -c %s "$path")"
    rm -f -- "$path"
    removed_wal=$((removed_wal + 1))
    removed_bytes=$((removed_bytes + size))
  done < <(
    find "$archive" -maxdepth 1 -type f \
      -regextype posix-extended -regex '.*/[0-9A-F]{24}' \
      -printf '%f %p\n' | LC_ALL=C sort -r | cut -d' ' -f2-
  )
}

prune_release_tree "$INCOMING/runtime-releases"
prune_release_tree "$RELEASES"
prune_previous_tree postgres10-data
prune_previous_tree postgres16-data
prune_base_tree "$INCOMING/wal/base" "$STATE/wal_base_applied"
prune_base_tree "$INCOMING/wal-pg16/base" "$STATE/wal_pg16_base_applied"
wal_replay_segment="$(
  replay_segment_for_stream wal xcmax-dr-postgres10 postgres
)"
pg16_user="$(cat "$STATE/wal_pg16_superuser" 2>/dev/null || true)"
wal_pg16_replay_segment=""
if [[ -n "$pg16_user" || "$TEST_MODE" == "1" ]]; then
  wal_pg16_replay_segment="$(
    replay_segment_for_stream wal-pg16 xcmax-dr-postgres16-wal "$pg16_user"
  )"
fi
prune_wal_before_replay wal "$wal_replay_segment"
prune_wal_before_replay wal-pg16 "$wal_pg16_replay_segment"
prune_wal_before_applied_base wal "$STATE/wal_base_applied"
prune_wal_before_applied_base wal-pg16 "$STATE/wal_pg16_base_applied"

date -u +%s >"$STATE/storage_retention_last_success"
log "DR 存储轮转完成: removed_dirs=$removed_dirs removed_wal=$removed_wal removed_bytes=$removed_bytes replay_wal=${wal_replay_segment:-none} replay_pg16=${wal_pg16_replay_segment:-none}"
