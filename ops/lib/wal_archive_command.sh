#!/usr/bin/env bash
# Build a crash-safe PostgreSQL archive_command.

xcmax_wal_archive_command() {
  local archive_dir="${1:?archive directory is required}"
  printf '%s' \
    "dst=\"${archive_dir}/%f\"; tmp=\"${archive_dir}/.%f.tmp\"; "\
"if test -f \"\$dst\" && cmp -s \"%p\" \"\$dst\"; then true; "\
"else rm -f \"\$tmp\"; cp \"%p\" \"\$tmp\" && mv -f \"\$tmp\" \"\$dst\"; fi"
}
