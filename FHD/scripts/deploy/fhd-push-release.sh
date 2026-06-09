#!/usr/bin/env bash
# 本机：打包 FHD API 发布物并原子 scp 到 update 服务器（供 cron 拉取式应用）。
#
# 用法（FHD 根目录或任意目录）:
#   bash scripts/deploy/fhd-push-release.sh
#
# 环境变量:
#   FHD_SKIP_PACK=1              跳过 pack（使用已有 dist/deploy 产物）
#   FHD_PUSH_HOST                默认 119.27.178.147
#   FHD_PUSH_USER                默认 root
#   FHD_RELEASE_CHANNEL          stable（prod）| staging；决定默认远端目录
#   FHD_PUSH_REMOTE_DIR          默认 /var/www/update/releases/<channel>/server
#   FHD_PUSH_SSH_KEY             SSH 私钥路径（默认 ~/.ssh/id_rsa 等）
#   FHD_RELEASE_OUT_DIR          与 pack 脚本一致
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FHD_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"
# shellcheck source=lib/deploy_emit.sh
. "$SCRIPT_DIR/lib/deploy_emit.sh"
export DEPLOY_SCRIPT_ID="fhd_push_release"

OUT_DIR="${FHD_RELEASE_OUT_DIR:-$FHD_ROOT/dist/deploy}"
CHANNEL="${FHD_RELEASE_CHANNEL:-stable}"
case "$CHANNEL" in
  stable | staging) ;;
  *)
    echo "[err] FHD_RELEASE_CHANNEL 须为 stable 或 staging，当前: $CHANNEL" >&2
    exit 1
    ;;
esac
HOST="${FHD_PUSH_HOST:-119.27.178.147}"
USER="${FHD_PUSH_USER:-root}"
REMOTE_DIR="${FHD_PUSH_REMOTE_DIR:-/var/www/update/releases/${CHANNEL}/server}"
SSH_KEY="${FHD_PUSH_SSH_KEY:-}"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
SCP_OPTS=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTS+=(-i "$SSH_KEY")
  SCP_OPTS+=(-i "$SSH_KEY")
fi

REMOTE="${USER}@${HOST}"
SSH=(ssh "${SSH_OPTS[@]}")
SCP=(scp "${SCP_OPTS[@]}")

deploy_emit bootstrap started "host=$HOST channel=$CHANNEL remote_dir=$REMOTE_DIR"

if [[ "${FHD_SKIP_PACK:-0}" != "1" ]]; then
  deploy_emit pack started "invoke=fhd-pack-release.sh channel=$CHANNEL"
  FHD_RELEASE_CHANNEL="$CHANNEL" bash "$SCRIPT_DIR/fhd-pack-release.sh"
  deploy_emit pack ok
fi

if [[ -n "${FHD_IMAGE_REF:-}" && -n "${FHD_IMAGE_DIGEST:-}" ]]; then
  deploy_emit merge started "invoke=fhd-merge-manifest-image.sh"
  FHD_MANIFEST_PATH="$OUT_DIR/fhd-manifest.json" \
    bash "$SCRIPT_DIR/fhd-merge-manifest-image.sh"
  deploy_emit merge ok
fi

MANIFEST="$OUT_DIR/fhd-manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
  echo "[err] manifest 不存在: $MANIFEST" >&2
  deploy_emit push failed "missing_manifest"
  exit 1
fi

read -r ARTIFACT SHA256 VERSION GIT_SHA DEPLOY_MODE IMAGE IMAGE_DIGEST <<<"$(
  python3 - <<'PY' "$MANIFEST"
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
print(
    doc.get("artifact", ""),
    doc.get("sha256", ""),
    doc.get("version", ""),
    doc.get("git_sha", ""),
    doc.get("deploy_mode", "tarball"),
    doc.get("image", ""),
    doc.get("image_digest", ""),
)
PY
)"

TARBALL="$OUT_DIR/$ARTIFACT"
if [[ -z "$ARTIFACT" || ! -f "$TARBALL" ]]; then
  echo "[err] tarball 不存在: $TARBALL" >&2
  deploy_emit push failed "missing_tarball"
  exit 1
fi

LOCAL_SHA="$(python3 - <<'PY' "$TARBALL"
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"

if [[ "$LOCAL_SHA" != "$SHA256" ]]; then
  echo "[err] manifest sha256 与本地 tarball 不符" >&2
  deploy_emit push failed "sha256_mismatch"
  exit 1
fi

deploy_emit push started "artifact=$ARTIFACT version=$VERSION sha=$GIT_SHA"

"${SSH[@]}" "$REMOTE" "mkdir -p '$REMOTE_DIR'"

atomic_upload() {
  local src="$1"
  local dest="$2"
  local base
  base="$(basename "$dest")"
  local part="${dest}.part"
  local local_sz
  local_sz="$(wc -c < "$src" | tr -d '[:space:]')"
  "${SCP[@]}" "$src" "${REMOTE}:${part}"
  "${SSH[@]}" "$REMOTE" "REMOTE_SZ=\$(wc -c < '$part'); \
    if [ \"\$REMOTE_SZ\" = '$local_sz' ]; then mv -f '$part' '$dest'; echo OK_MOVED; \
    else echo SIZE_MISMATCH \"\$REMOTE_SZ\" vs '$local_sz'; rm -f '$part'; exit 1; fi"
}

atomic_upload "$TARBALL" "${REMOTE_DIR}/${ARTIFACT}"
atomic_upload "$MANIFEST" "${REMOTE_DIR}/fhd-manifest.json"

IMAGE_TAR="$OUT_DIR/fhd-api-image.tar.gz"
if [[ -f "$IMAGE_TAR" ]]; then
  deploy_emit push started "artifact=fhd-api-image.tar.gz"
  atomic_upload "$IMAGE_TAR" "${REMOTE_DIR}/fhd-api-image.tar.gz"
  echo "[ok] image_tar=fhd-api-image.tar.gz"
fi

deploy_emit push ok "channel=$CHANNEL version=$VERSION git_sha=$GIT_SHA mode=${DEPLOY_MODE:-tarball}"
echo "[ok] 已发布至 ${HOST}:${REMOTE_DIR}/ (channel=$CHANNEL)"
echo "[ok] artifact=$ARTIFACT sha256=${SHA256:0:16}... deploy_mode=${DEPLOY_MODE:-tarball}"
if [[ -n "${IMAGE:-}" && -n "${IMAGE_DIGEST:-}" ]]; then
  echo "[ok] image=$IMAGE digest=${IMAGE_DIGEST:0:19}..."
fi
echo "[hint] 服务器 cron 将在 5 分钟内自动应用；或手动:"
if [[ "${DEPLOY_MODE:-tarball}" == "image" ]]; then
  echo "       FHD_API_IMAGE=$IMAGE FHD_API_IMAGE_DIGEST=$IMAGE_DIGEST bash /opt/fhd-full/scripts/deploy/fhd-apply-release-compose.sh"
else
  echo "       FHD_RELEASE_TARBALL=${REMOTE_DIR}/${ARTIFACT} bash /opt/fhd-full/scripts/deploy/fhd-apply-release.sh"
fi
