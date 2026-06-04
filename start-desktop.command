#!/usr/bin/env bash
# macOS 双击启动：委托 XCAGI 内 SQLite 桌面开发脚本（与 start-desktop-sqlite.bat 等价）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "${ROOT}/XCAGI/start-desktop-sqlite.command"
