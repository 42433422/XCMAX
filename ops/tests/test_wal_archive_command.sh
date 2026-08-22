#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." &>/dev/null && pwd)"
# shellcheck source=../lib/wal_archive_command.sh
. "$REPO_ROOT/ops/lib/wal_archive_command.sh"

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
archive="$work/archive"
source_file="$work/000000010000000000000001"
segment="$(basename "$source_file")"
mkdir -p "$archive"
printf 'complete-wal-segment-v1' >"$source_file"
: >"$archive/$segment"

command="$(xcmax_wal_archive_command "$archive")"
command="${command//%p/$source_file}"
command="${command//%f/$segment}"
sh -ceu "$command"
cmp -s "$source_file" "$archive/$segment"
test ! -e "$archive/.$segment.tmp"

# A non-empty but corrupt destination must also be replaced.
printf 'different-content' >"$archive/$segment"
sh -ceu "$command"
cmp -s "$source_file" "$archive/$segment"
test ! -e "$archive/.$segment.tmp"

echo "wal archive command: PASS"
