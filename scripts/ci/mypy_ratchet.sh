#!/usr/bin/env bash
# mypy ratchet：允许 baseline 已知错误，禁止新增。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
BASELINE="${ROOT}/mypy-baseline.txt"
TMP="$(mktemp)"
if ! python3 -m mypy app/ --config-file pyproject.toml >"$TMP" 2>&1; then
  true
fi
if [[ ! -f "$BASELINE" ]]; then
  cp "$TMP" "$BASELINE"
  echo "mypy baseline created at mypy-baseline.txt ($(wc -l <"$BASELINE") lines)"
  exit 0
fi
if diff -u "$BASELINE" "$TMP" >/dev/null 2>&1; then
  echo "mypy ratchet OK (matches baseline)"
  exit 0
fi
echo "mypy ratchet FAILED: diff from baseline (fix errors or update baseline intentionally)"
diff -u "$BASELINE" "$TMP" | head -80 || true
exit 1
