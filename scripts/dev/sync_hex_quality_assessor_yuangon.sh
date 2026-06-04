#!/usr/bin/env bash
# 将 hex-quality-assessor 元工定义同步到生产 MODstore 并补登记 Catalog。
# 用法（需本机可 ssh root@119.27.178.147）:
#   bash scripts/dev/sync_hex_quality_assessor_yuangon.sh
set -euo pipefail

HOST="${XCMAX_REMOTE_HOST:-119.27.178.147}"
SSH_OPTS=(-o StrictHostKeyChecking=no)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${REPO_ROOT%/FHD}/成都修茈科技有限公司/yuangon/craft-workshop/hex-quality-assessor"
REMOTE_YUANGON="/root/成都修茈科技有限公司/yuangon/craft-workshop/hex-quality-assessor"

if [[ ! -f "${SRC}/employee.yaml" ]]; then
  echo "缺少源定义: ${SRC}/employee.yaml" >&2
  exit 1
fi

echo "==> 同步 yuangon 到 ${HOST}:${REMOTE_YUANGON}"
ssh "${SSH_OPTS[@]}" "root@${HOST}" "mkdir -p '$(dirname "${REMOTE_YUANGON}")'"
scp "${SSH_OPTS[@]}" -r "${SRC}" "root@${HOST}:${REMOTE_YUANGON}"

echo "==> 触发 yuangon onboard (hex-quality-assessor)"
ssh "${SSH_OPTS[@]}" "root@${HOST}" \
  "/root/modstore-git/MODstore_deploy/.venv/bin/python /root/成都修茈科技有限公司/MODstore_deploy/modstore_server/scripts/onboard_yuangon_employees.py --repo-root /root/成都修茈科技有限公司 --pkg-ids hex-quality-assessor"

echo "==> 完成。请在桌面「服务器后台 → 值班总览」刷新状态。"
