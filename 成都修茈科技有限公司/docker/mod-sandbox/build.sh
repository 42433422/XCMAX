#!/usr/bin/env bash
# Assembles a minimal build context and builds xcagi-mod-sandbox (no --ignorefile required).
# Run from repository root:  bash docker/mod-sandbox/build.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CTX="$(mktemp -d "${TMPDIR:-/tmp}/xcagi-mod-sandbox-XXXXXX")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cleanup() { rm -rf "$CTX"; }
trap cleanup EXIT

cp -a "$REPO_ROOT/app" "$CTX/app"
mkdir -p "$CTX/XCAGI"
cp -a "$REPO_ROOT/XCAGI/requirements.txt" "$CTX/XCAGI/"
cp -a "$REPO_ROOT/XCAGI/run.py" "$REPO_ROOT/XCAGI/run_fastapi.py" "$CTX/XCAGI/"
cp -a "$REPO_ROOT/resources" "$CTX/resources"
cp -a "$SCRIPT_DIR/Dockerfile" "$CTX/Dockerfile"

docker build -t xcagi-mod-sandbox "$CTX"
