#!/bin/sh
set -eu

case "$0" in
  */*) launcher_dir=${0%/*} ;;
  *) launcher_dir=. ;;
esac
launcher_dir=$(CDPATH= cd -- "$launcher_dir" && pwd)
deploy_root=$(CDPATH= cd -- "$launcher_dir/.." && pwd)
test_path="$deploy_root/tests/test_self_maintenance_loop_runner_policy.py"

resolve_python() {
  candidate=$1
  case "$candidate" in
    */*)
      if [ -x "$candidate" ]; then
        printf '%s\n' "$candidate"
      fi
      ;;
    *) command -v "$candidate" 2>/dev/null || true ;;
  esac
}

supports_focused_tests() {
  "$1" -c '
import sys
if sys.version_info < (3, 11):
    raise SystemExit(1)
import apscheduler
import pytest
from starlette.exceptions import StarletteDeprecationWarning
' >/dev/null 2>&1
}

run_if_supported() {
  resolved=$(resolve_python "$1")
  if [ -n "$resolved" ] && supports_focused_tests "$resolved"; then
    exec "$resolved" -m pytest "$test_path" -q
  fi
}

if [ -n "${MODSTORE_SELF_MAINTENANCE_TEST_PYTHON:-}" ]; then
  run_if_supported "$MODSTORE_SELF_MAINTENANCE_TEST_PYTHON"
else
  run_if_supported "$deploy_root/.venv/bin/python"
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    run_if_supported "$candidate"
  done
fi

printf '%s\n' \
  'self-maintenance focused test requires Python >=3.11 with apscheduler, pytest, and compatible Starlette' \
  >&2
exit 2
