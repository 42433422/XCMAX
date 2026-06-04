#!/usr/bin/env bash
# 可选：桌面版 SQLite 增量复制（Litestream）
# 配置见仓库根 litestream.yml；需已安装 litestream 并设置 LITESTREAM_* 环境变量。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
if ! command -v litestream >/dev/null 2>&1; then
  echo "litestream 未安装。macOS: brew install litestream" >&2
  exit 1
fi
export LITESTREAM_DATA_DIR="${LITESTREAM_DATA_DIR:-$ROOT/data}"
exec litestream replicate -config "$ROOT/litestream.yml"
