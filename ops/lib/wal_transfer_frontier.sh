#!/usr/bin/env bash
# Build a monotonic WAL shipment list. Receiver retention is allowed to remove
# already replayed segments, so absence on the receiver must never make the
# primary resend its entire local archive.

xcmax_is_wal_segment() {
  [[ "${1:-}" =~ ^[0-9A-F]{24}$ ]]
}

xcmax_read_wal_frontier() {
  local frontier_file="$1" legacy_status="$2" value=""

  if [[ -s "$frontier_file" ]]; then
    value="$(tr -d '[:space:]' <"$frontier_file")"
  elif [[ -s "$legacy_status" ]]; then
    value="$(sed -n 's/^latest_segment=//p' "$legacy_status" | tail -1)"
  fi
  if [[ -n "$value" ]] && ! xcmax_is_wal_segment "$value"; then
    echo "invalid WAL shipment frontier: $value" >&2
    return 1
  fi
  printf '%s\n' "$value"
}

xcmax_prepare_wal_file_list() {
  local archive="$1" frontier_file="$2" legacy_status="$3" output="$4"
  local frontier="" segment=""
  local LC_ALL=C

  frontier="$(xcmax_read_wal_frontier "$frontier_file" "$legacy_status")" ||
    return 1
  : >"$output"
  while IFS= read -r segment; do
    [[ -z "$frontier" || "$segment" > "$frontier" ]] || continue
    printf '%s\n' "$segment" >>"$output"
  done < <(
    find "$archive" -maxdepth 1 -type f \
      -regextype posix-extended -regex '.*/[0-9A-F]{24}' -printf '%f\n' |
      LC_ALL=C sort
  )
}

xcmax_commit_wal_frontier() {
  local frontier_file="$1" segment="$2" tmp=""
  xcmax_is_wal_segment "$segment" || {
    echo "refusing invalid WAL shipment frontier: $segment" >&2
    return 1
  }
  tmp="${frontier_file}.tmp.$$"
  printf '%s\n' "$segment" >"$tmp"
  chmod 0600 "$tmp"
  mv -f "$tmp" "$frontier_file"
}
