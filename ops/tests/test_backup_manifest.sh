#!/usr/bin/env bash
set -euo pipefail

OPS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
DEST="$tmp/daily"; mkdir -p "$DEST"
for name in fhd_pg.dump modstore_pg.dump payment_pg.dump modstore_sqlite.db.gz configs.tar.gz stale.dump; do printf '%s' "$name" > "$DEST/$name"; done
DRY_RUN=0; FAILURES=(); fail() { FAILURES+=("$1"); }
eval "$(sed -n '/^write_manifest() {/,/^}/p' "$OPS/backup/xcmax_backup.sh")"; write_manifest
expected="$(printf '%s\n' configs.tar.gz fhd_pg.dump modstore_pg.dump modstore_sqlite.db.gz payment_pg.dump)"
actual="$(awk '{sub(/^\.\//, "", $2); print $2}' "$DEST/MANIFEST.txt" | sort)"
[[ ${#FAILURES[@]} -eq 0 && "$actual" == "$expected" && -f "$DEST/stale.dump" ]]
(cd "$DEST" && sha256sum -c MANIFEST.txt >/dev/null)
