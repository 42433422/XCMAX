#!/usr/bin/env bash
# 将 CI 构建的镜像引用与 digest 合并进 fhd-manifest.json（manifest v2）。
#
# 用法:
#   FHD_IMAGE_REF=ghcr.io/org/repo/xcagi-fhd-api \
#   FHD_IMAGE_DIGEST=sha256:abc... \
#   bash scripts/deploy/fhd-merge-manifest-image.sh
#
# 环境变量:
#   FHD_MANIFEST_PATH     默认 dist/deploy/fhd-manifest.json（相对 FHD 根）
#   FHD_MANIFEST_DEPLOY_MODE  默认保持 tarball；设为 image 可切换服务器路由
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FHD_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"
# shellcheck source=lib/deploy_emit.sh
. "$SCRIPT_DIR/lib/deploy_emit.sh"
export DEPLOY_SCRIPT_ID="fhd_merge_manifest_image"

MANIFEST="${FHD_MANIFEST_PATH:-$FHD_ROOT/dist/deploy/fhd-manifest.json}"
IMAGE_REF="${FHD_IMAGE_REF:-}"
IMAGE_DIGEST="${FHD_IMAGE_DIGEST:-}"
DEPLOY_MODE_OVERRIDE="${FHD_MANIFEST_DEPLOY_MODE:-}"

if [[ -z "$IMAGE_REF" || -z "$IMAGE_DIGEST" ]]; then
  echo "[err] 需要 FHD_IMAGE_REF 与 FHD_IMAGE_DIGEST" >&2
  deploy_emit merge failed "missing_image_fields"
  exit 1
fi

if [[ ! -f "$MANIFEST" ]]; then
  echo "[err] manifest 不存在: $MANIFEST" >&2
  deploy_emit merge failed "missing_manifest"
  exit 1
fi

deploy_emit merge started "image=${IMAGE_REF}"

python3 - <<'PY' "$MANIFEST" "$IMAGE_REF" "$IMAGE_DIGEST" "$DEPLOY_MODE_OVERRIDE"
import json, sys

path, image, digest, mode_override = sys.argv[1:5]
doc = json.load(open(path, encoding="utf-8"))
doc["image"] = image
doc["image_digest"] = digest
if mode_override:
    doc["deploy_mode"] = mode_override
elif "deploy_mode" not in doc:
    doc["deploy_mode"] = "tarball"
with open(path, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
print(json.dumps(doc, ensure_ascii=False))
PY

deploy_emit merge ok "digest=${IMAGE_DIGEST:0:19}..."
echo "[ok] manifest 已合并镜像字段: $MANIFEST"
