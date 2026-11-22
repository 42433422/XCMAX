#!/usr/bin/env bash
# 给备份 COS bucket 安装生命周期规则，用对象存储原生能力替代脚本内保留逻辑。
#
# 规则来自 fhd-cos-lifecycle.json：
#   postgres/daily/    7 天
#   postgres/weekly/   28 天
#   postgres/monthly/  365 天
#   config/uploads/mods daily  30 天
#   manifests/         365 天
#
# 用法（有腾讯云凭证的机器上执行）:
#   bash fhd-install-cos-lifecycle.sh
#
# 环境变量:
#   FHD_COS_BUCKET   默认 xcagi-cvm-backup-sh
#   FHD_COS_REGION   默认 ap-shanghai
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"
RULES_FILE="$SCRIPT_DIR/fhd-cos-lifecycle.json"

[[ -f "$RULES_FILE" ]] || { echo "[err] 缺少 $RULES_FILE" >&2; exit 1; }
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$RULES_FILE"

if ! command -v tccli >/dev/null 2>&1; then
  echo "[warn] 未安装 tccli，无法自动写入生命周期。请在 COS 控制台按以下规则手工配置："
  echo "       bucket=$COS_BUCKET region=$COS_REGION"
  python3 - "$RULES_FILE" <<'PY'
import json, sys
for r in json.load(open(sys.argv[1]))["Rules"]:
    print(f"       {r['Filter']['Prefix']:<24} {r['Expiration']['Days']:>4} 天")
PY
  exit 0
fi

tccli cos PutBucketLifecycle \
  --Bucket "$COS_BUCKET" \
  --Region "$COS_REGION" \
  --LifecycleConfiguration "$(cat "$RULES_FILE")"

echo "[install] 生命周期规则已写入 $COS_BUCKET"
