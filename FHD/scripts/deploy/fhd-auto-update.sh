#!/usr/bin/env bash
# 服务器 cron：读取 manifest，按 deploy_mode 路由 tarball 或 compose 应用。
# 替代 git_auto_update.sh（生产机不再 git pull）。
#
# 环境变量:
#   FHD_MANIFEST_PATH   默认 /var/www/update/releases/stable/server/fhd-manifest.json
#   FHD_ARTIFACT_DIR    默认与 manifest 同目录
#   FHD_DEPLOY_ROOT     默认 /opt/fhd-full
#   FHD_DEPLOY_MODE     覆盖 manifest deploy_mode（tarball|image）
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
APPLY_TARBALL="$SCRIPT_DIR/fhd-apply-release.sh"
APPLY_COMPOSE="$SCRIPT_DIR/fhd-apply-release-compose.sh"
LOG="${FHD_DEPLOY_LOG:-/var/log/fhd-auto-update.log}"

MANIFEST="${FHD_MANIFEST_PATH:-/var/www/update/releases/stable/server/fhd-manifest.json}"
ARTIFACT_DIR="${FHD_ARTIFACT_DIR:-$(dirname "$MANIFEST")}"
DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"
LOCK="${FHD_AUTO_UPDATE_LOCK:-/tmp/fhd-auto-update.lock}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
}

exec 9>"$LOCK"
if ! flock -n 9; then
  log "另一实例运行中，跳过"
  exit 0
fi

if [[ ! -f "$MANIFEST" ]]; then
  log "manifest 不存在: $MANIFEST"
  exit 0
fi

read -r DEPLOY_MODE REMOTE_SHA ARTIFACT VERSION GIT_SHA IMAGE IMAGE_DIGEST <<<"$(
  python3 - <<'PY' "$MANIFEST"
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
print(
    doc.get("deploy_mode", "tarball"),
    doc.get("sha256", ""),
    doc.get("artifact", ""),
    doc.get("version", ""),
    doc.get("git_sha", ""),
    doc.get("image", ""),
    doc.get("image_digest", ""),
)
PY
)"

DEPLOY_MODE="${FHD_DEPLOY_MODE:-$DEPLOY_MODE}"
DEPLOY_MODE="${DEPLOY_MODE:-tarball}"

if [[ "$DEPLOY_MODE" == "image" ]]; then
  if [[ -z "$IMAGE" || -z "$IMAGE_DIGEST" ]]; then
    log "ERROR: deploy_mode=image 但 manifest 缺少 image / image_digest"
    exit 1
  fi

  LOCAL_DIGEST=""
  if [[ -f "$DEPLOY_ROOT/.deploy-image-digest" ]]; then
    LOCAL_DIGEST="$(tr -d '[:space:]' < "$DEPLOY_ROOT/.deploy-image-digest")"
  fi

  if [[ "$IMAGE_DIGEST" == "$LOCAL_DIGEST" ]]; then
    log "已是最新（compose） version=$VERSION digest=${IMAGE_DIGEST:0:19}..."
    exit 0
  fi

  log "发现新镜像 version=$VERSION sha=$GIT_SHA digest=${IMAGE_DIGEST:0:19}...，开始 compose 应用"
  FHD_API_IMAGE="$IMAGE" \
    FHD_API_IMAGE_DIGEST="$IMAGE_DIGEST" \
    FHD_DEPLOY_ROOT="$DEPLOY_ROOT" \
    bash "$APPLY_COMPOSE"
  log "compose 自动更新完成 version=$VERSION"
  exit 0
fi

# --- tarball 模式（Phase 1 默认）---
if [[ -z "$REMOTE_SHA" || -z "$ARTIFACT" ]]; then
  log "manifest 字段不完整（tarball 模式需要 sha256 + artifact）"
  exit 1
fi

LOCAL_SHA=""
if [[ -f "$DEPLOY_ROOT/.deploy-sha256" ]]; then
  LOCAL_SHA="$(tr -d '[:space:]' < "$DEPLOY_ROOT/.deploy-sha256")"
fi

if [[ "$REMOTE_SHA" == "$LOCAL_SHA" ]]; then
  log "已是最新 version=$VERSION sha=$GIT_SHA"
  exit 0
fi

TARBALL="$ARTIFACT_DIR/$ARTIFACT"
if [[ ! -f "$TARBALL" ]]; then
  log "ERROR: artifact 不存在: $TARBALL"
  exit 1
fi

LOCAL_FILE_SHA="$(python3 - <<'PY' "$TARBALL"
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"

if [[ "$LOCAL_FILE_SHA" != "$REMOTE_SHA" ]]; then
  log "ERROR: tarball sha256 与 manifest 不符 (file=$LOCAL_FILE_SHA manifest=$REMOTE_SHA)"
  exit 1
fi

log "发现新版本 version=$VERSION sha=$GIT_SHA，开始 tarball 应用"
FHD_RELEASE_TARBALL="$TARBALL" \
  FHD_DEPLOY_ROOT="$DEPLOY_ROOT" \
  FHD_EXPECTED_SHA256="$REMOTE_SHA" \
  FHD_SKIP_PIP="${FHD_SKIP_PIP:-1}" \
  bash "$APPLY_TARBALL"
log "tarball 自动更新完成 version=$VERSION"
