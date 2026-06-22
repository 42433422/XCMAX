#!/usr/bin/env bash
# 将 templates/vue-dist 上传到 update 站（供企业端拉取，管理端不直连企业机）。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FHD_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"

CHANNEL="${FHD_RELEASE_CHANNEL:-stable}"
HOST="${FHD_PUSH_HOST:-119.27.178.147}"
USER="${FHD_PUSH_USER:-root}"
REMOTE_DIR="${FHD_PUSH_REMOTE_DIR:-/var/www/update/releases/${CHANNEL}/server}"
SSH_KEY="${FHD_PUSH_SSH_KEY:-}"
VUE_DIST="${FHD_VUE_DIST:-$FHD_ROOT/templates/vue-dist}"

SSH_OPTS=(-o StrictHostKeyChecking=no -o ServerAliveInterval=30)
SCP_OPTS=(-o StrictHostKeyChecking=no -o ServerAliveInterval=30)
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTS+=(-i "$SSH_KEY")
  SCP_OPTS+=(-i "$SSH_KEY")
fi
REMOTE="${USER}@${HOST}"

[[ -d "$VUE_DIST" ]] || {
  echo "[err] vue-dist 不存在: $VUE_DIST（请先 cd frontend && npm run build）" >&2
  exit 1
}

echo "[upload] vue-dist -> ${REMOTE}:${REMOTE_DIR}/vue-dist/"
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '${REMOTE_DIR}/vue-dist'"
scp "${SCP_OPTS[@]}" -r "${VUE_DIST}/." "${REMOTE}:${REMOTE_DIR}/vue-dist/"
echo "[ok] vue-dist 已发布至 update 站"
