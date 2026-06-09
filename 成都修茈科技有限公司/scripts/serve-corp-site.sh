#!/usr/bin/env bash
# 本地预览官网静态页（developer.html 等）。勿用 file:// 打开，否则 /developer.html 无法跳转。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8088}"
cd "$ROOT"
echo "官网静态服: http://127.0.0.1:${PORT}/index.html"
echo "开发者门户: http://127.0.0.1:${PORT}/developer.html"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
