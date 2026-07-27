#!/usr/bin/env bash
# Stop and verify the production CVM through a least-privilege Tencent Cloud
# identity, then mint the short-lived local proof consumed by the DR guard.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

ENV_FILE="${OPS_DR_TENCENT_FENCE_ENV:-/etc/xcmax-dr-tencent-fence.env}"
[[ -s "$ENV_FILE" ]] || {
  echo "缺少腾讯云 fencing 配置: $ENV_FILE" >&2
  exit 1
}
env_owner="$(stat -c '%u' "$ENV_FILE")"
env_mode="$(stat -c '%a' "$ENV_FILE")"
[[ "$env_owner" == "0" && $((8#$env_mode & 077)) == 0 ]] || {
  echo "fencing 配置必须归 root 且权限不高于 0600: $ENV_FILE" >&2
  exit 2
}
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

REGION="${OPS_DR_PRIMARY_REGION:-ap-chengdu}"
INSTANCE_ID="${OPS_DR_PRIMARY_INSTANCE_ID:-ins-fsv07ypz}"
PRIMARY_IP="${OPS_DR_PRIMARY_IP:-119.27.178.147}"
PROOF="${OPS_DR_FENCE_PROOF:-/var/lib/xcmax-dr/provider-fence-proof.json}"
USE_CVM_ROLE="${OPS_DR_TENCENT_USE_CVM_ROLE:-1}"

[[ "$REGION" =~ ^[a-z0-9-]+$ ]] || {
  echo "生产地域格式非法" >&2
  exit 2
}
[[ "$INSTANCE_ID" =~ ^ins-[a-z0-9]+$ ]] || {
  echo "生产实例 ID 格式非法" >&2
  exit 2
}
[[ "$PRIMARY_IP" == "119.27.178.147" ]] || {
  echo "拒绝 fencing 非预期生产 IP: $PRIMARY_IP" >&2
  exit 2
}
command -v tccli >/dev/null 2>&1 || {
  echo "缺少 tccli；请预装腾讯云 CLI" >&2
  exit 1
}

declare -a auth_args=()
if [[ "$USE_CVM_ROLE" == "1" ]]; then
  auth_args+=(--use-cvm-role)
else
  : "${TENCENTCLOUD_SECRET_ID:?缺少 TENCENTCLOUD_SECRET_ID}"
  : "${TENCENTCLOUD_SECRET_KEY:?缺少 TENCENTCLOUD_SECRET_KEY}"
fi

describe_instance() {
  tccli cvm DescribeInstances \
    --region "$REGION" \
    --InstanceIds "[\"$INSTANCE_ID\"]" \
    "${auth_args[@]}" |
    python3 -c '
import json
import sys
doc = json.load(sys.stdin)
items = doc.get("Response", {}).get("InstanceSet", [])
if len(items) != 1:
    raise SystemExit("生产实例查询结果不唯一")
item = items[0]
print(
    item.get("InstanceState", "")
    + "|"
    + item.get("LatestOperationState", "")
)
'
}

instance="$(describe_instance)"
state="${instance%%|*}"
latest_operation="${instance#*|}"
stop_requested=0
case "$state" in
  STOPPED) ;;
  RUNNING|STOPPING)
    if [[ "$state" == "RUNNING" ]]; then
      tccli cvm StopInstances \
        --region "$REGION" \
        --InstanceIds "[\"$INSTANCE_ID\"]" \
        --StopType SOFT_FIRST \
        --StoppedMode KEEP_CHARGING \
        "${auth_args[@]}" >/dev/null
      stop_requested=1
    fi
    deadline=$((SECONDS + 180))
    while ((SECONDS < deadline)); do
      instance="$(describe_instance)"
      state="${instance%%|*}"
      latest_operation="${instance#*|}"
      [[ "$state" == "STOPPED" && "$latest_operation" == "SUCCESS" ]] && break
      sleep 5
    done
    [[ "$state" == "STOPPED" && "$latest_operation" == "SUCCESS" ]] || {
      echo "生产实例 fencing 超时: state=$state latest_operation=$latest_operation" >&2
      exit 1
    }
    ;;
  *)
    echo "拒绝未知生产实例状态: $state" >&2
    exit 1
    ;;
esac

if ((stop_requested)); then
  echo "腾讯云已确认关机操作成功: state=$state latest_operation=$latest_operation"
else
  echo "腾讯云已确认生产实例已处于 STOPPED"
fi

install -d -m 0700 "$(dirname "$PROOF")"
python3 - "$PROOF" "$PRIMARY_IP" "$REGION" "$INSTANCE_ID" <<'PY'
import json
import os
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
now = int(time.time())
doc = {
    "primary_ip": sys.argv[2],
    "region": sys.argv[3],
    "instance_id": sys.argv[4],
    "fenced": True,
    "fenced_at": now,
    "expires_at": now + 300,
}
tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
tmp.write_text(json.dumps(doc, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
echo "生产实例已由云平台 fencing: region=$REGION instance=$INSTANCE_ID"
