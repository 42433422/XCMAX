#!/usr/bin/env bash
# Bound one shared DR transfer so a slow receiver cannot starve every producer.

xcmax_run_bounded_transfer() {
  local max_seconds="$1" label="$2" log_file="$3"
  shift 3

  [[ "$max_seconds" =~ ^[0-9]+$ && "$max_seconds" -ge 1 ]] || {
    echo "invalid transfer timeout: $max_seconds" >&2
    return 2
  }
  command -v timeout >/dev/null 2>&1 || {
    echo "timeout command is required for bounded DR transfers" >&2
    return 2
  }

  local rc=0
  if timeout --foreground --signal=TERM --kill-after=30s \
    "${max_seconds}s" "$@" >>"$log_file" 2>&1; then
    return 0
  else
    rc="$?"
  fi
  if [[ "$rc" == "124" || "$rc" == "137" ]]; then
    printf '[%s] ERROR: DR transfer timed out: label=%s max_seconds=%s\n' \
      "$(date -Is)" "$label" "$max_seconds" | tee -a "$log_file" >&2
  fi
  return "$rc"
}
