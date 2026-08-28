#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
# shellcheck source=../lib/wal_transfer_frontier.sh
. "$ROOT/lib/wal_transfer_frontier.sh"

tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
archive="$tmp/archive"
state="$tmp/state"
mkdir -p "$archive" "$state"
for index in 1 2 3 4 5; do
  touch "$archive/$(printf '%024X' "$index")"
done

cat >"$state/wal-status" <<'EOF'
latest_segment=000000000000000000000003
EOF
xcmax_prepare_wal_file_list \
  "$archive" "$state/frontier" "$state/wal-status" "$state/list"
diff -u <(printf '%024X\n' 4 5) "$state/list"

xcmax_commit_wal_frontier "$state/frontier" "$(printf '%024X' 4)"
xcmax_prepare_wal_file_list \
  "$archive" "$state/frontier" "$state/wal-status" "$state/list"
diff -u <(printf '%024X\n' 5) "$state/list"

printf 'not-a-segment\n' >"$state/frontier"
if xcmax_prepare_wal_file_list \
  "$archive" "$state/frontier" "$state/wal-status" "$state/list"; then
  echo "corrupt frontier must fail closed" >&2
  exit 1
fi

echo "WAL transfer frontier tests passed"
