#!/usr/bin/env bash
# 同步 e2e-agent.mjs + trae_failover.mjs 到 runtime para-main-agent
# 用法：bash FHD/scripts/autonomy/runtime_tools/install_e2e_agent.sh
#
# 部署后需重启 e2e-agent（watchdog 会拉起）：
#   pkill -f 'para-main-agent/e2e-agent.mjs' || true

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="${E2E_AGENT_DEST_DIR:-/Users/a4243342/XCMAX-runtime/para-main-agent}"

node --test "$ROOT/report_only_target_branch.test.mjs"

for name in e2e-agent.mjs trae_failover.mjs; do
  src="$ROOT/$name"
  dest="$DEST_DIR/$name"
  if [[ ! -f "$src" ]]; then
    echo "[error] source not found: $src" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
  echo "[ok] synced $name → $dest"
done

echo ""
echo "重启 e2e-agent："
echo "  pkill -f 'para-main-agent/e2e-agent.mjs' || true"
echo "  # watchdog LaunchAgent 会在数秒内拉起新进程"
