#!/usr/bin/env bash
# XCAGI desktop long-run probe. Defaults to eight hours; CI may shorten it.
set -euo pipefail

BASE_URL="${XCAGI_SOAK_BASE_URL:-http://127.0.0.1:17500}"
DURATION_SECONDS="${XCAGI_SOAK_DURATION_SECONDS:-28800}"
INTERVAL_SECONDS="${XCAGI_SOAK_INTERVAL_SECONDS:-30}"
MAX_CONSECUTIVE_FAILURES="${XCAGI_SOAK_MAX_CONSECUTIVE_FAILURES:-3}"
OUTPUT="${XCAGI_SOAK_OUTPUT:-desktop-soak-$(date -u +%Y%m%dT%H%M%SZ).csv}"
DESKTOP_PID="${XCAGI_SOAK_DESKTOP_PID:-}"

case "${DURATION_SECONDS}:${INTERVAL_SECONDS}:${MAX_CONSECUTIVE_FAILURES}" in
  *[!0-9:]*|'') printf 'ERROR: soak numeric settings are invalid\n' >&2; exit 2 ;;
esac
if [[ "${DURATION_SECONDS}" -le 0 || "${INTERVAL_SECONDS}" -le 0 || "${MAX_CONSECUTIVE_FAILURES}" -le 0 ]]; then
  printf 'ERROR: soak numeric settings must be positive\n' >&2
  exit 2
fi

mkdir -p "$(dirname "${OUTPUT}")"
printf 'timestamp_utc,endpoint,http_status,latency_seconds,desktop_rss_kb\n' >"${OUTPUT}"
started="$(date +%s)"
deadline="$((started + DURATION_SECONDS))"
consecutive_failures=0
samples=0

while [[ "$(date +%s)" -lt "${deadline}" ]]; do
  for endpoint in /api/ping /api/health /api/desktop/status; do
    metrics="$(curl --silent --show-error --output /dev/null --write-out '%{http_code},%{time_total}' --max-time 20 "${BASE_URL}${endpoint}" || printf '000,20')"
    status="${metrics%%,*}"
    latency="${metrics#*,}"
    rss=""
    if [[ -n "${DESKTOP_PID}" ]]; then
      rss="$(ps -o rss= -p "${DESKTOP_PID}" 2>/dev/null | tr -d ' ' || true)"
    fi
    printf '%s,%s,%s,%s,%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${endpoint}" "${status}" "${latency}" "${rss}" >>"${OUTPUT}"
    samples="$((samples + 1))"
    if [[ "${status}" =~ ^2[0-9][0-9]$ ]]; then
      consecutive_failures=0
    else
      consecutive_failures="$((consecutive_failures + 1))"
      if [[ "${consecutive_failures}" -ge "${MAX_CONSECUTIVE_FAILURES}" ]]; then
        printf 'ERROR: %s consecutive soak failures; evidence=%s\n' "${consecutive_failures}" "${OUTPUT}" >&2
        exit 1
      fi
    fi
  done
  sleep "${INTERVAL_SECONDS}"
done

printf 'PASS: desktop soak completed samples=%s duration_seconds=%s evidence=%s\n' "${samples}" "${DURATION_SECONDS}" "${OUTPUT}"
