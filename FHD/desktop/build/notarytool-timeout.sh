#!/bin/bash
set -euo pipefail

timeout_value="${XCAGI_NOTARYTOOL_TIMEOUT:-45m}"
if [[ "${1:-}" == "submit" ]]; then
  exec xcrun notarytool "$@" --timeout "$timeout_value"
fi
exec xcrun notarytool "$@"
