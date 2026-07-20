#!/usr/bin/env bash
# 同步 FHD/scripts/autonomy/runtime_tools/merge_worker.mjs 到 runtime 部署路径
# 用法：bash FHD/scripts/autonomy/runtime_tools/install_merge_worker.sh
#
# 部署后需重启 merge-worker LaunchAgent：
#   launchctl unload ~/Library/LaunchAgents/com.xcmax.para-merge-worker.plist
#   launchctl load ~/Library/LaunchAgents/com.xcmax.para-merge-worker.plist

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/merge_worker.mjs"
DEST="${MERGE_WORKER_DEST:-/Users/a4243342/XCMAX-runtime/para-main-agent/merge-worker.mjs}"

if [[ ! -f "$SRC" ]]; then
  echo "[error] source not found: $SRC" >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
cp "$SRC" "$DEST"
echo "[ok] synced merge_worker.mjs → $DEST"
echo ""
echo "重启 merge-worker："
echo "  launchctl unload ~/Library/LaunchAgents/com.xcmax.para-merge-worker.plist"
echo "  launchctl load   ~/Library/LaunchAgents/com.xcmax.para-merge-worker.plist"
