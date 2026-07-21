#!/usr/bin/env bash
# 安装 sync-runtime-to-source.sh 的本地 cron（默认每小时 :15）。
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SYNC_SCRIPT="$SCRIPT_DIR/sync-runtime-to-source.sh"
MARKER="# xcmax-sync-runtime-to-source"
INTERVAL="${XCMAX_RUNTIME_SYNC_CRON:-15 * * * *}"
LOG_DIR="${XCMAX_RUNTIME_SYNC_LOG_DIR:-$HOME/.xcmax/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/sync-runtime-to-source.log"
[[ -x "$SYNC_SCRIPT" ]] || chmod +x "$SYNC_SCRIPT"
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'sync-runtime-to-source\.sh' | grep -v "$MARKER" >"$TMP" || true
{
  cat "$TMP"
  echo "$MARKER"
  echo "${INTERVAL} /bin/bash \"$SYNC_SCRIPT\" --commit >>\"$LOG_FILE\" 2>&1"
} | crontab -
rm -f "$TMP"
echo "[ok] cron installed: ${INTERVAL} $SYNC_SCRIPT --commit"
crontab -l | grep -E 'sync-runtime-to-source|xcmax-sync-runtime' || true
