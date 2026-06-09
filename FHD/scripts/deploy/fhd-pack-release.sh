#!/usr/bin/env bash
# 打包 FHD 生产 API 发布物（tar.gz + manifest.json）。
# 用法（在 FHD 根目录）:
#   bash scripts/deploy/fhd-pack-release.sh
# 输出: dist/deploy/fhd-full-<version>-<sha>.tar.gz 与同目录 manifest.json
# macOS 打包时禁用 xattr，避免 Linux 解压 LIBARCHIVE.xattr 警告。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FHD_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"
# shellcheck source=lib/deploy_emit.sh
. "$SCRIPT_DIR/lib/deploy_emit.sh"
export DEPLOY_SCRIPT_ID="fhd_pack_release"

OUT_DIR="${FHD_RELEASE_OUT_DIR:-$FHD_ROOT/dist/deploy}"
CHANNEL="${FHD_RELEASE_CHANNEL:-stable}"
mkdir -p "$OUT_DIR"

deploy_emit bootstrap started "fhd_root=$FHD_ROOT"

VERIFY="$FHD_ROOT/scripts/dev/verify_version_anchors.py"
if [[ ! -f "$VERIFY" ]]; then
  echo "[err] missing $VERIFY" >&2
  deploy_emit verify failed "missing_script"
  exit 1
fi
deploy_emit verify started
if ! python3 "$VERIFY"; then
  deploy_emit verify failed "anchor_mismatch"
  exit 1
fi
deploy_emit verify ok

VERSION="$(
  python3 - <<'PY' "$FHD_ROOT/pyproject.toml" 2>/dev/null || echo "10.0.0"
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
print(m.group(1) if m else "10.0.0")
PY
)"

GIT_SHA="local"
if command -v git >/dev/null 2>&1 && git -C "$FHD_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_SHA="$(git -C "$FHD_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo local)"
fi

ARTIFACT="fhd-full-${VERSION}-${GIT_SHA}.tar.gz"
TARBALL="$OUT_DIR/$ARTIFACT"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/fhd-pack.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT

export COPYFILE_DISABLE=1

deploy_emit pack started "artifact=$ARTIFACT"

# 仅打包运行时代码；不含 .env / data / uploads / 前端构建缓存。
RSYNC_EXCLUDES=(
  --exclude '.git'
  --exclude '.venv'
  --exclude '**/__pycache__'
  --exclude '**/*.pyc'
  --exclude 'node_modules'
  --exclude 'frontend'
  --exclude 'desktop'
  --exclude 'mobile-android'
  --exclude 'tests'
  --exclude 'data'
  --exclude 'uploads'
  --exclude 'dist'
  --exclude '.coverage'
  --exclude '.pytest_cache'
  --exclude '.ruff_cache'
  --exclude '.secrets'
  --exclude '.env'
  --exclude '.env.*'
)

for item in app XCAGI alembic alembic.ini mods xcagi_common resources requirements-base.txt requirements.txt pyproject.toml; do
  src="$FHD_ROOT/$item"
  if [[ -e "$src" ]]; then
    rsync -a "${RSYNC_EXCLUDES[@]}" "$src" "$STAGING/"
  fi
done

# 服务器端拉取式部署脚本（随制品一并下发，避免生产机 git pull）
mkdir -p "$STAGING/scripts/deploy/lib" "$STAGING/docker"
cp "$SCRIPT_DIR/fhd-auto-update.sh" \
  "$SCRIPT_DIR/fhd-apply-release.sh" \
  "$SCRIPT_DIR/fhd-apply-release-compose.sh" \
  "$STAGING/scripts/deploy/"
cp "$SCRIPT_DIR/lib/deploy_emit.sh" "$STAGING/scripts/deploy/lib/"
cp "$FHD_ROOT/docker/docker-compose.fhd-prod.yml" "$STAGING/docker/"

COPYFILE_DISABLE=1 tar -C "$STAGING" -czf "$TARBALL" .
SHA256="$(python3 - <<'PY' "$TARBALL"
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"

BUILT_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
MANIFEST="$OUT_DIR/fhd-manifest.json"

python3 - <<'PY' "$MANIFEST" "$VERSION" "$GIT_SHA" "$ARTIFACT" "$SHA256" "$BUILT_AT" "$CHANNEL"
import json, sys
path, version, git_sha, artifact, sha256, built_at, channel = sys.argv[1:8]
doc = {
    "product": "fhd-full",
    "channel": channel,
    "version": version,
    "git_sha": git_sha,
    "deploy_mode": "tarball",
    "artifact": artifact,
    "sha256": sha256,
    "built_at": built_at,
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
print(json.dumps(doc, ensure_ascii=False))
PY

deploy_emit pack ok "sha256=${SHA256:0:16}..."
echo "[ok] tarball: $TARBALL"
echo "[ok] manifest: $MANIFEST"
