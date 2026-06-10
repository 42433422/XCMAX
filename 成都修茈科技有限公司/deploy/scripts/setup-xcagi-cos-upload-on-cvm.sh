#!/usr/bin/env bash
# 在 CVM 上一键上传 XCAGI 安装包到 xcagi-releases 桶（需先配置密钥）
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/root/成都修茈科技有限公司}"
CRED_FILE="${CRED_FILE:-/root/.xcagi-cos.env}"
PY="${REPO_ROOT}/deploy/scripts/upload-xcagi-releases-cos.py"

if [[ ! -f "$CRED_FILE" ]]; then
  cat >&2 <<'EOF'
缺少 /root/.xcagi-cos.env，请创建（chmod 600）：

  COS_SECRET_ID=你的SecretId
  COS_SECRET_KEY=你的SecretKey
  COS_BUCKET=xcagi-releases-1374207682
  COS_REGION=ap-guangzhou
  COS_PREFIX=xcagi-v8.0.0

密钥：腾讯云控制台 → 访问管理 → API 密钥管理 → 新建（仅需 COS 读写该桶）

创建后执行：
  bash /root/成都修茈科技有限公司/deploy/scripts/setup-xcagi-cos-upload-on-cvm.sh
EOF
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$CRED_FILE"
set +a

pip3 install -q cos-python-sdk-v5
python3 "$PY"

echo ""
echo "上传完成后，在 CDN 控制台对 dl.xiu-ci.com 提交「缓存预热」："
echo "  /xcagi-v8.0.0/enterprise/XCAGI-Enterprise-Setup-8.0.0-x64.exe"
echo "  （personal / offline 同理）"
