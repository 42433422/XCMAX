#!/usr/bin/env bash
# Retry npm ci only when a dependency installer fails because of transient network errors.
# All non-network failures remain immediately fatal; the install is never skipped.
set -uo pipefail

attempt=1
max_attempts="${NPM_CI_NETWORK_RETRIES:-3}"
log_file="$(mktemp)"
trap 'rm -f "$log_file"' EXIT

if ! [[ "$max_attempts" =~ ^[1-5]$ ]]; then
  echo "NPM_CI_NETWORK_RETRIES must be an integer from 1 to 5" >&2
  exit 2
fi

while (( attempt <= max_attempts )); do
  : >"$log_file"
  npm ci "$@" 2>&1 | tee "$log_file"
  status=${PIPESTATUS[0]}
  if (( status == 0 )); then
    exit 0
  fi

  if (( attempt >= max_attempts )) || ! grep -Eqi 'ETIMEDOUT|ENETUNREACH|ECONNRESET|EAI_AGAIN|ECONNREFUSED' "$log_file"; then
    exit "$status"
  fi

  delay=$((attempt * 10))
  echo "::warning::npm ci hit a transient network error; retrying in ${delay}s (${attempt}/${max_attempts})."
  sleep "$delay"
  attempt=$((attempt + 1))
done

exit 1
