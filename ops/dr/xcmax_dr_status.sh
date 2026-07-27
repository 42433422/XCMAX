#!/usr/bin/env bash
# Concise machine-readable DR status used by operators and CI smoke checks.

set -euo pipefail

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
STATE="${OPS_DR_STATE:-/var/lib/xcmax-dr}"
CONTAINER="${OPS_DR_WAL_CONTAINER:-xcmax-dr-postgres10}"
PG16_CONTAINER="${OPS_DR_WAL_PG16_CONTAINER:-xcmax-dr-postgres16-wal}"

printf 'archive_latest=%s\n' "$(readlink -f "$DR_ROOT/archive/latest" 2>/dev/null || true)"
printf 'logical_snapshot=%s\n' "$(cat "$STATE/last_restored_snapshot" 2>/dev/null || true)"
printf 'wal_base=%s\n' "$(cat "$STATE/wal_base_applied" 2>/dev/null || true)"
printf 'release_sha=%s\n' "$(cat "$STATE/release_applied_sha" 2>/dev/null || true)"
printf 'release_modstore_sha=%s\n' \
  "$(cat "$STATE/release_applied_modstore_sha" 2>/dev/null || true)"
printf 'release_fhd_sha=%s\n' \
  "$(cat "$STATE/release_applied_fhd_sha" 2>/dev/null || true)"
printf 'edge_mode=%s\n' "$(cat "$STATE/edge_mode" 2>/dev/null || true)"

if docker inspect "$CONTAINER" >/dev/null 2>&1 &&
  [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" == "true" ]]; then
  recovery="$(
    docker exec -u postgres "$CONTAINER" \
      psql -U postgres -d postgres -Atqc "SELECT pg_is_in_recovery()"
  )"
  replay_lsn="$(
    docker exec -u postgres "$CONTAINER" \
      psql -U postgres -d postgres -Atqc \
      "SELECT COALESCE(pg_last_wal_replay_lsn()::text, '')"
  )"
  printf 'wal_container=running\n'
  printf 'wal_in_recovery=%s\n' "$recovery"
  printf 'wal_replay_lsn=%s\n' "$replay_lsn"
else
  printf 'wal_container=stopped\n'
fi

if docker inspect "$PG16_CONTAINER" >/dev/null 2>&1 &&
  [[ "$(docker inspect -f '{{.State.Running}}' "$PG16_CONTAINER")" == "true" ]]; then
  pg16_user="$(cat "$STATE/wal_pg16_superuser" 2>/dev/null || true)"
  pg16_recovery="$(
    docker exec -u postgres "$PG16_CONTAINER" \
      psql -U "$pg16_user" -d postgres -Atqc "SELECT pg_is_in_recovery()"
  )"
  pg16_replay_lsn="$(
    docker exec -u postgres "$PG16_CONTAINER" \
      psql -U "$pg16_user" -d postgres -Atqc \
      "SELECT COALESCE(pg_last_wal_replay_lsn()::text, '')"
  )"
  printf 'wal_pg16_base=%s\n' \
    "$(cat "$STATE/wal_pg16_base_applied" 2>/dev/null || true)"
  printf 'wal_pg16_container=running\n'
  printf 'wal_pg16_in_recovery=%s\n' "$pg16_recovery"
  printf 'wal_pg16_replay_lsn=%s\n' "$pg16_replay_lsn"
else
  printf 'wal_pg16_container=stopped\n'
fi

for unit in xcmax-dr-modstore xcmax-dr-fhd xcmax-dr-payment xcmax-dr-scheduler nginx; do
  printf '%s=%s\n' "$unit" "$(systemctl is-active "$unit" 2>/dev/null || true)"
done
