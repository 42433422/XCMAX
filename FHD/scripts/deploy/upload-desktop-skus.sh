#!/usr/bin/env bash
# 上传 release/xcagi-v{version}/enterprise/ 桌面制品至 update 服务器。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# 版本默认值取自 SSOT（FHD/VERSION.md），避免脚本内硬编码产物版本。
VERSION="${1:-$(. "$ROOT/scripts/deploy/lib/version.sh" && product_version)}"
SKU="${2:-enterprise}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"

RELEASE_ROOT="${ROOT}/release/xcagi-v${VERSION}"

HOST="${XCAGI_UPDATE_SSH_HOST:-119.27.178.147}"
USER="${XCAGI_UPDATE_SSH_USER:-root}"
# 公网 OTA / 下载路径：https://xiu-ci.com/releases/stable/{sku}/
REMOTE_BASE="${XCAGI_UPDATE_SSH_PATH:-/var/www/update/releases/stable}"
SSH_KEY="${XCAGI_UPDATE_SSH_KEY:-}"

SSH_OPTS=(-o StrictHostKeyChecking=no -o ServerAliveInterval=30)
SCP_OPTS=(-o StrictHostKeyChecking=no -o ServerAliveInterval=30)
if [[ -n "${SSH_KEY}" ]]; then
  SSH_OPTS+=(-i "${SSH_KEY}")
  SCP_OPTS+=(-i "${SSH_KEY}")
fi
REMOTE="${USER}@${HOST}"

if [[ "${SKU}" != enterprise ]]; then
  echo "[err] desktop upload supports only the enterprise SKU" >&2
  exit 1
fi

[[ -d "${RELEASE_ROOT}" ]] || {
  echo "[err] 本地 release 不存在: ${RELEASE_ROOT}" >&2
  exit 1
}

atomic_upload() {
  local src="$1"
  local dest="$2"
  local part="${dest}.part"
  local local_sz
  local_sz="$(wc -c < "${src}" | tr -d '[:space:]')"
  scp "${SCP_OPTS[@]}" "${src}" "${REMOTE}:${part}"
  ssh "${SSH_OPTS[@]}" "${REMOTE}" "REMOTE_SZ=\$(wc -c < '${part}'); \
    if [ \"\${REMOTE_SZ}\" = '${local_sz}' ]; then mv -f '${part}' '${dest}'; echo OK; \
    else rm -f '${part}'; echo SIZE_MISMATCH; exit 1; fi"
}

local_dir="${RELEASE_ROOT}/${SKU}"
[[ -d "${local_dir}" ]] || { echo "[err] 缺少目录 ${local_dir}" >&2; exit 1; }
trimmed_remote_base="${REMOTE_BASE%/}"
legacy_remote_dir="${trimmed_remote_base}/${SKU}"
versioned_remote_dir="${trimmed_remote_base}/xcagi-v${VERSION}/${SKU}"
echo "[upload] ${SKU} -> ${REMOTE}:${legacy_remote_dir}/ 和 ${REMOTE}:${versioned_remote_dir}/"
ssh "${SSH_OPTS[@]}" "${REMOTE}" "mkdir -p '${legacy_remote_dir}' '${versioned_remote_dir}'"
shopt -s nullglob
for pattern in \
  "XCAGI-*-Setup-${VERSION}-x64.exe" \
  "XCAGI-*-Setup-${VERSION}-x64.exe.blockmap" \
  "XCAGI-*-${VERSION}-mac-*.dmg" \
  "XCAGI-*-${VERSION}-mac-*.dmg.blockmap" \
  "XCAGI-*-${VERSION}-mac-*.zip" \
  "XCAGI-*-${VERSION}-mac-*.zip.blockmap" \
  "XCAGI-*-Android-${VERSION}.apk" \
  "latest.yml" \
  "latest-mac.yml"; do
  for f in "${local_dir}"/${pattern}; do
    [[ -f "${f}" ]] || continue
    echo "  -> $(basename "${f}")"
    atomic_upload "${f}" "${legacy_remote_dir}/$(basename "${f}")"
    atomic_upload "${f}" "${versioned_remote_dir}/$(basename "${f}")"
  done
done
shopt -u nullglob

echo "[ok] upload complete (${VERSION})"
