#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/Users/a4243342/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
CACHE_DIR="/tmp/xc-brand-film-swift-cache"
BIN="$ROOT/output/render-brand-film"

mkdir -p "$ROOT/output" "$CACHE_DIR"
"$PYTHON" "$ROOT/scripts/prepare_assets.py"

SWIFT_MODULECACHE_PATH="$CACHE_DIR" \
CLANG_MODULE_CACHE_PATH="$CACHE_DIR" \
xcrun swiftc \
  -O \
  -framework AppKit \
  -framework AVFoundation \
  -framework CoreImage \
  -framework CoreMedia \
  -framework CoreVideo \
  "$ROOT/scripts/render_brand_film.swift" \
  -o "$BIN"

"$BIN" "$ROOT"
