#!/usr/bin/env bash
# 将 Whisper ONNX 模型安装到 /data/hf-hub/，供浏览器同源加载（/hf-hub/ → nginx alias）
# 依赖：pip install modelscope
# 用法：sudo bash scripts/install-whisper-hub-models.sh

set -euo pipefail

MODEL_ID="${WHISPER_HUB_MODEL:-onnx-community/whisper-base}"
DEST="/data/hf-hub/onnx-community/whisper-base/resolve/main"
CACHE="${MODELSCOPE_CACHE:-/data/modelscope-cache}"

echo "[whisper-hub] model=$MODEL_ID dest=$DEST"

python3 - <<'PY' "$MODEL_ID" "$CACHE" "$DEST"
import os, shutil, sys
from modelscope.hub.snapshot_download import snapshot_download

model_id, cache_dir, dest = sys.argv[1:4]
os.makedirs(dest, exist_ok=True)
os.makedirs(cache_dir, exist_ok=True)
print(f"[whisper-hub] snapshot_download {model_id} ...")
src = snapshot_download(model_id, cache_dir=cache_dir)
print(f"[whisper-hub] cache: {src}")
for name in os.listdir(src):
    sp = os.path.join(src, name)
    dp = os.path.join(dest, name)
    if os.path.isdir(sp):
        if os.path.exists(dp):
            shutil.rmtree(dp)
        shutil.copytree(sp, dp)
    else:
        shutil.copy2(sp, dp)
    print(f"  + {name}")
print("[whisper-hub] done.")
PY

if [ -f "$DEST/config.json" ]; then
  echo "[whisper-hub] OK: $DEST/config.json"
else
  echo "[whisper-hub] ERROR: config.json missing" >&2
  exit 1
fi
