#!/usr/bin/env bash
# 上传 release/xcagi-v{version}/{personal,enterprise}/ 桌面制品至 update 服务器。
set -euo pipefail

VERSION="${1:-10.0.0}"
SKU="${2:-all}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASE_ROOT="${ROOT}/release/xcagi-v${VERSION}"

HOST="${XCAGI_UPDATE_SSH_HOST:-119.27.178.147}"
USER="${XCAGI_UPDATE_SSH_USER:-root}"
REMOTE_BASE="${XCAGI_UPDATE_SSH_PATH:-/var/www/update/releases/stable}"
SSH_KEY="${XCAGI_UPDATE_SSH_KEY:-}"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
SCP_OPTS=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
if [[ -n "${SSH_KEY}" ]]; then
  SSH_OPTS+=(-i "${SSH_KEY}")
  SCP_OPTS+=(-i "${SSH_KEY}")
fi
REMOTE="${USER}@${HOST}"

skus=()
case "${SKU}" in
  all) skus=(personal enterprise) ;;
  personal | enterprise) skus=("${SKU}") ;;
  *)
    echo "[err] SKU 须为 personal|enterprise|all" >&2
    exit 1
    ;;
esac

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

for sku in "${skus[@]}"; do
  local_dir="${RELEASE_ROOT}/${sku}"
  [[ -d "${local_dir}" ]] || { echo "[err] 缺少目录 ${local_dir}" >&2; exit 1; }
  trimmed_remote_base="${REMOTE_BASE%/}"
  legacy_remote_dir="${trimmed_remote_base}/${sku}"
  versioned_remote_dir="${trimmed_remote_base}/xcagi-v${VERSION}/${sku}"
  echo "[upload] ${sku} -> ${REMOTE}:${legacy_remote_dir}/ 和 ${REMOTE}:${versioned_remote_dir}/"
  ssh "${SSH_OPTS[@]}" "${REMOTE}" "mkdir -p '${legacy_remote_dir}' '${versioned_remote_dir}'"
  shopt -s nullglob
  for pattern in \
    "XCAGI-*-Setup-${VERSION}-x64.exe" \
    "XCAGI-*-Setup-${VERSION}-x64.exe.blockmap" \
    "XCAGI-${VERSION}-mac-*.dmg" \
    "XCAGI-${VERSION}-mac-*.zip" \
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
done

echo "[ok] upload complete (${VERSION})"
