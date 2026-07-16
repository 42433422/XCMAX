#!/usr/bin/env bash
# Agent 收工 / session 结束：自动清理工作区运行时残留（不改业务源码、不 git clean）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# 吞掉 hook stdin，避免阻塞
cat >/dev/null || true

if command -v python3 >/dev/null 2>&1; then
  python3 "$ROOT/scripts/dev/clean_agent_workspace.py" \
    >/tmp/xcmax-workspace-clean.json \
    2>/tmp/xcmax-workspace-clean.err || true
else
  echo '{"status":"skipped","reason":"python3 missing"}' >/tmp/xcmax-workspace-clean.json
fi

# stop / sessionEnd：静默成功，不发 followup，避免循环打扰
echo '{}'
exit 0
