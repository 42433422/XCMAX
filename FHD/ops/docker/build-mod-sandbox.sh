#!/usr/bin/env bash
# Assembles a minimal build context and builds xcagi-mod-sandbox (no --ignorefile required).
# Run from repository root:  bash ops/docker/build-mod-sandbox.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CTX="$(mktemp -d "${TMPDIR:-/tmp}/xcagi-mod-sandbox-XXXXXX")"
cleanup() { rm -rf "$CTX"; }
trap cleanup EXIT

for item in app packages config resources requirements-server-api.txt; do
  cp -a "$REPO_ROOT/$item" "$CTX/$item"
done
cp -a "$SCRIPT_DIR/Dockerfile.mod-sandbox" "$CTX/Dockerfile"

docker build -t xcagi-mod-sandbox "$CTX"
