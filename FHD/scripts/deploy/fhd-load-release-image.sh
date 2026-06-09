#!/usr/bin/env bash
# 从 update 站 fhd-api-image.tar.gz 加载 CI 导出镜像（无需 GHCR PAT）。
#
# 用法:
#   FHD_IMAGE_TARBALL=/var/www/update/.../fhd-api-image.tar.gz \
#   FHD_API_IMAGE_DIGEST=sha256:... \
#     bash scripts/deploy/fhd-load-release-image.sh
#
# 环境变量:
#   FHD_IMAGE_TARBALL      必填（或第一个参数）
#   FHD_API_IMAGE          可选，加载后校验 RepoTags 前缀
#   FHD_API_IMAGE_DIGEST   可选，加载后校验本地 digest 存在
set -euo pipefail

TARBALL="${FHD_IMAGE_TARBALL:-${1:-}}"
IMAGE="${FHD_API_IMAGE:-}"
DIGEST="${FHD_API_IMAGE_DIGEST:-}"

if [[ -z "$TARBALL" || ! -f "$TARBALL" ]]; then
  echo "[err] 镜像 tar 不存在: ${TARBALL:-<empty>}" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[err] 未安装 docker" >&2
  exit 1
fi

echo "[info] 加载镜像 tar: $TARBALL"
load_out=""
if [[ "$TARBALL" == *.gz ]]; then
  load_out="$(gunzip -c "$TARBALL" | docker load 2>&1 | tee /dev/stderr)"
else
  load_out="$(docker load -i "$TARBALL" 2>&1 | tee /dev/stderr)"
fi

loaded_id=""
loaded_id="$(echo "$load_out" | sed -n 's/^Loaded image ID: //p' | tail -1)"
if [[ -z "$loaded_id" ]]; then
  loaded_id="$(echo "$load_out" | sed -n 's/^Loaded image: //p' | awk '{print $NF}' | tail -1)"
fi

if [[ -n "$IMAGE" && -n "$loaded_id" ]]; then
  tag_sha="${FHD_GIT_SHA:-${DIGEST#sha256:}}"
  tag_sha="${tag_sha:0:12}"
  if [[ -n "$tag_sha" ]]; then
    docker tag "$loaded_id" "${IMAGE}:sha-${tag_sha}"
    echo "[ok] 已打 tag ${IMAGE}:sha-${tag_sha}"
  fi
fi

if [[ -n "$DIGEST" && -n "$IMAGE" ]]; then
  if docker image inspect "${IMAGE}@${DIGEST}" >/dev/null 2>&1; then
    echo "[ok] 已加载 ${IMAGE}@${DIGEST:0:19}..."
    exit 0
  fi
  tag_sha="${FHD_GIT_SHA:-${DIGEST#sha256:}}"
  tag_sha="${tag_sha:0:12}"
  if [[ -n "$tag_sha" ]] && docker image inspect "${IMAGE}:sha-${tag_sha}" >/dev/null 2>&1; then
    echo "[ok] 已加载 ${IMAGE}:sha-${tag_sha}（本地 tag）"
    exit 0
  fi
  echo "[warn] 加载完成但未找到 ${IMAGE}@${DIGEST:0:19}...（compose 将用 sha tag）"
fi

echo "[ok] docker load 完成"
