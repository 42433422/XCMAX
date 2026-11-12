#!/usr/bin/env bash
# 顺序上传 3 个安装包到 COS，完成后写入 /var/log/xcagi-cos-upload.done
set -euo pipefail
LOG=/var/log/xcagi-cos-upload.log
DONE=/var/log/xcagi-cos-upload.done
PY=/root/成都修茈科技有限公司/deploy/scripts/upload-one-xcagi-cos.py

exec >>"$LOG" 2>&1
echo "=== upload-all start $(date -Iseconds) ==="

set -a
source /root/.xcagi-cos.env
set +a

upload() {
  local edition=$1 file=$2
  echo "--- $(date -Iseconds) begin $edition/$file ---"
  PYTHONUNBUFFERED=1 python3 "$PY" "$edition" "$file"
  echo "--- $(date -Iseconds) done $edition/$file ---"
}

rm -f "$DONE"
upload personal  XCAGI-Personal-Setup-8.0.0-x64.exe
upload offline   XCAGI-Offline-Setup-8.0.0-x64.exe
upload enterprise XCAGI-Enterprise-Setup-8.0.0-x64.exe

bash /root/成都修茈科技有限公司/deploy/scripts/list-xcagi-cos.sh
echo "=== upload-all finished $(date -Iseconds) ===" | tee "$DONE"
