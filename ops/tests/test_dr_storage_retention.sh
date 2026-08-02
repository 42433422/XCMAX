#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
tmp="$(mktemp -d /tmp/xcmax-dr-retention-test.XXXXXX)"
trap 'rm -rf -- "$tmp"' EXIT
incoming="$tmp/incoming"
state="$tmp/state"
mkdir -p "$incoming/runtime-releases" "$tmp/releases" "$tmp/runtime" "$state"

for digit in 1 2 3 4 5; do
  sha="$(printf "%040d" "$digit")"
  mkdir -p "$incoming/runtime-releases/$sha" "$tmp/releases/$sha"
  touch -t "20260101010${digit}" "$incoming/runtime-releases/$sha" "$tmp/releases/$sha"
done
printf '%040d\n' 1 >"$state/release_applied_modstore_sha"

for stream in wal wal-pg16; do
  mkdir -p "$incoming/$stream/archive" "$incoming/$stream/base"
  for index in 1 2 3 4; do
    segment="$(printf '%024X' "$index")"
    printf x >"$incoming/$stream/archive/$segment"
  done
  touch -t 202601010100 "$incoming/$stream/archive/000000000000000000000001" \
    "$incoming/$stream/archive/000000000000000000000002"
  for index in 1 2 3 4; do
    snapshot="2026080${index}T000000Z-${index}"
    mkdir -p "$incoming/$stream/base/$snapshot"
    printf 'created_at_epoch=%s\n' "$(date -u +%s)" >"$incoming/$stream/base/$snapshot/BASE_INFO"
    touch "$incoming/$stream/base/$snapshot/BASE_READY"
    touch -t "2026080${index}0000" "$incoming/$stream/base/$snapshot"
  done
done
printf '20260801T000000Z-1\n' >"$state/wal_base_applied"
printf '20260801T000000Z-1\n' >"$state/wal_pg16_base_applied"

XCMAX_DR_RETENTION_TEST_MODE=1 \
OPS_DR_ROOT="$tmp" OPS_DR_STATE="$state" \
OPS_DR_STORAGE_LOG="$tmp/storage-retention.log" \
OPS_DR_STORAGE_LOCK="$tmp/storage-retention.lock" \
OPS_DR_RUNTIME_RELEASE_KEEP=2 OPS_DR_BASE_KEEP=2 \
OPS_DR_WAL_KEEP_MIN_SEGMENTS=2 \
  bash "$ROOT/dr/xcmax_dr_storage_retention.sh"

test -d "$incoming/runtime-releases/0000000000000000000000000000000000000001"
test -d "$incoming/runtime-releases/0000000000000000000000000000000000000005"
test ! -d "$incoming/runtime-releases/0000000000000000000000000000000000000002"
test -d "$incoming/wal/base/20260801T000000Z-1"
test ! -d "$incoming/wal/base/20260802T000000Z-2"
test ! -e "$incoming/wal/archive/000000000000000000000001"
test -e "$incoming/wal/archive/000000000000000000000004"
grep -q 'removed_dirs=' "$tmp/storage-retention.log"
echo "DR storage retention tests passed"
