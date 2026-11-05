#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; tmp="$(mktemp -d)"; trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1])" "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/backups/daily/keep"; printf sentinel > "$tmp/backups/daily/keep/file"; before="$(shasum -a 256 "$tmp/backups/daily/keep/file")"
printf '#!/bin/sh\necho 160004\n' > "$tmp/bin/psql"
cat > "$tmp/bin/docker" <<'SH'
#!/usr/bin/env bash
case "$*" in
  *pg_dump*--version*) echo 'pg_dump (PostgreSQL) 16.4' ;; *pg_restore*--version*) echo 'pg_restore (PostgreSQL) 16.4' ;;
  *pg_dump*) [[ "${FAKE_FAIL:-}" != dump ]] || exit 1; cat >/dev/null; printf 'PGDMP\001\020\000snapshot' ;;
  *pg_restore*--list*) [[ "${FAKE_FAIL:-}" != archive ]] || exit 1; cat >/dev/null; echo 'TABLE public.example' ;;
  *) exit 2 ;;
esac
SH
printf '#!/bin/sh\n[ "${FAKE_FAIL:-}" = manifest ] && [ "$1" = -c ] && exit 1\nexec "$REAL_SHA256SUM" "$@"\n' > "$tmp/bin/sha256sum"
printf '#!/bin/sh\n[ "${FAKE_FAIL:-}" = lock ] && exit 1\nexit 0\n' > "$tmp/bin/flock"
chmod +x "$tmp/bin/psql" "$tmp/bin/docker" "$tmp/bin/sha256sum" "$tmp/bin/flock"
printf '%s\n' 'DATABASE_URL=postgresql://backup-user:private@127.0.0.1/modstore' > "$tmp/modstore.env"; sha=736a7818f62b087ecd4ea218d8cd24af95d3fb7b
printf 'printf() { case "$1" in scope=*) return 1;; esac; builtin printf "$@"; }\n' > "$tmp/fail-receipt.sh"
run_snapshot() { env PATH="$tmp/bin:$PATH" REAL_SHA256SUM="$(command -v sha256sum)" FAKE_FAIL="${FAKE_FAIL:-}" BASH_ENV="${BASH_ENV:-}" OPS_MODSTORE_ENV="$tmp/modstore.env" OPS_PG_DUMP_CONTAINER_IMAGE=pg16-test OPS_BACKUP_DIR="${OPS_BACKUP_DIR:-$tmp/backups}" OPS_LOG_DIR="$tmp/log" bash -s -- --modstore-release "$sha" < "$ROOT/ops/backup/xcmax_backup.sh"; }
run_snapshot >/dev/null; run_snapshot >/dev/null
[[ "$(find "$tmp/backups/modstore-release/$sha" -name release-backup.txt | wc -l | tr -d ' ')" == 2 ]]
for failure in lock dump archive manifest receipt; do
  if FAKE_FAIL="$failure" BASH_ENV="$([[ "$failure" == receipt ]] && echo "$tmp/fail-receipt.sh")" OPS_BACKUP_DIR="$tmp/failures" run_snapshot >"$tmp/$failure.log" 2>&1; then echo "$failure unexpectedly succeeded" >&2; exit 1; fi
done
[[ "$(shasum -a 256 "$tmp/backups/daily/keep/file")" == "$before" ]]
while IFS= read -r receipt; do
  grep -qx "target_sha=$sha" "$receipt"; grep -q 'pg_dump 16.4; pg_restore 16.4; PostgreSQL 16' "$receipt"; grep -qx 'archive_validation=pg_restore --list passed' "$receipt"
  (cd "$(dirname "$receipt")" && sha256sum -c MANIFEST.txt >/dev/null); [[ "$(awk '{print $2}' "$(dirname "$receipt")/MANIFEST.txt")" == modstore_pg.dump && ! -e "$(dirname "$receipt")/payment_pg.dump" ]]
done < <(find "$tmp/backups/modstore-release/$sha" -name release-backup.txt -print)
