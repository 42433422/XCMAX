#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
# shellcheck source=../lib/bounded_transfer.sh
# shellcheck disable=SC1091
. "$ROOT/lib/bounded_transfer.sh"

tmp="$(mktemp -d /tmp/xcmax-bounded-transfer.XXXXXX)"
trap 'rm -rf -- "$tmp"' EXIT
log="$tmp/transfer.log"

xcmax_run_bounded_transfer 2 success "$log" sh -c 'printf success'
grep -q success "$log"

if xcmax_run_bounded_transfer 1 timeout "$log" sleep 5; then
  echo "expected timeout" >&2
  exit 1
fi
grep -q 'DR transfer timed out: label=timeout' "$log"
echo "bounded transfer tests passed"
