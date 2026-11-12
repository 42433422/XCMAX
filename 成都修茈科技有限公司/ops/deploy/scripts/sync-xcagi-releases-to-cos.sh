#!/usr/bin/env bash
# 将 CVM 上的 XCAGI 安装包同步到腾讯云 COS（供 CDN 回源）
# 依赖：coscli（推荐）或 coscmd，且已配置密钥
#
# 用法（在 CVM 或本机，能访问 /var/www/update 时）：
#   export COS_SECRET_ID=xxx COS_SECRET_KEY=yyy   # 若 coscli 未写 ~/.cos.yaml
#   bash deploy/scripts/sync-xcagi-releases-to-cos.sh
#
# 环境变量：
#   COS_BUCKET   默认 xiuci-website-1374207682
#   COS_PREFIX   默认 xcagi-v8.0.0（须与 VITE_XCAGI_DOWNLOAD_BASE_URL 路径一致）
#   LOCAL_ROOT   默认 /var/www/update/releases/stable
#   COS_REGION   默认 ap-chengdu

set -euo pipefail

COS_BUCKET="${COS_BUCKET:-xcagi-releases-1374207682}"
COS_PREFIX="${COS_PREFIX:-xcagi-v8.0.0}"
LOCAL_ROOT="${LOCAL_ROOT:-/var/www/update/releases/stable}"
COS_REGION="${COS_REGION:-ap-guangzhou}"

if [[ ! -d "$LOCAL_ROOT" ]]; then
  echo "ERROR: LOCAL_ROOT not found: $LOCAL_ROOT" >&2
  exit 1
fi

cos_target="cos://${COS_BUCKET}/${COS_PREFIX}/"

upload_coscli() {
  if ! command -v coscli >/dev/null 2>&1; then
    return 1
  fi
  echo "==> coscli sync ${LOCAL_ROOT}/ -> ${cos_target}"
  coscli sync "${LOCAL_ROOT}/" "${cos_target}" \
    --recursive \
    --include ".*\\.(exe|dmg|yml|blockmap)$"
  return 0
}

upload_coscmd() {
  if ! command -v coscmd >/dev/null 2>&1; then
    return 1
  fi
  echo "==> coscmd upload ${LOCAL_ROOT} -> /${COS_PREFIX}/"
  for edition in personal offline enterprise; do
    if [[ -d "${LOCAL_ROOT}/${edition}" ]]; then
      coscmd upload -r "${LOCAL_ROOT}/${edition}" "${COS_PREFIX}/${edition}/"
    fi
  done
  return 0
}

echo "Bucket: ${COS_BUCKET}  Prefix: ${COS_PREFIX}  Region: ${COS_REGION}"
echo "Local:  ${LOCAL_ROOT}"
ls -lh "${LOCAL_ROOT}"/*/*.exe 2>/dev/null || ls -lh "${LOCAL_ROOT}"/*.exe 2>/dev/null || true

if upload_coscli; then
  :
elif upload_coscmd; then
  :
else
  echo "ERROR: 未找到 coscli 或 coscmd。请先安装并配置：" >&2
  echo "  https://cloud.tencent.com/document/product/436/60418" >&2
  exit 1
fi

echo ""
echo "OK. 请在腾讯云控制台："
echo "  1) 确认 COS 对象：${cos_target}{personal,offline,enterprise}/"
echo "  2) 为 dl.xiu-ci.com 配置 CDN CNAME（勿再 A 记录到 CVM）"
echo "  3) 验证：curl -sI https://dl.xiu-ci.com/${COS_PREFIX}/enterprise/XCAGI-Enterprise-Setup-8.0.0-x64.exe"
echo "详见：deploy/docs/runbooks/xcagi-download-cdn.md"
