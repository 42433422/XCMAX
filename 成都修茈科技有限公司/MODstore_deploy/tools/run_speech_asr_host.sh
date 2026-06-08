#!/bin/bash
set -e
PCM_DIR=/tmp/asr_pcm_samples
rm -rf "$PCM_DIR"
mkdir -p "$PCM_DIR"
export FFMPEG=/usr/bin/ffmpeg

phrases=(
  "1_你好今天天气怎么样|你好，今天天气怎么样"
  "2_帮我查一下订单状态|帮我查一下订单状态"
  "3_打开工作台首页|打开工作台首页"
)

python3 <<'PY'
import asyncio, os, subprocess, sys
from pathlib import Path
import edge_tts

FFMPEG = os.environ["FFMPEG"]
PCM_DIR = Path("/tmp/asr_pcm_samples")
RATE = 16000
VOICE = "zh-CN-XiaoxiaoNeural"
items = [
    ("1_你好今天天气怎么样", "你好，今天天气怎么样"),
    ("2_帮我查一下订单状态", "帮我查一下订单状态"),
    ("3_打开工作台首页", "打开工作台首页"),
]

async def one(name, text):
    td = PCM_DIR / name
    td.mkdir(parents=True, exist_ok=True)
    mp3 = td / "utt.mp3"
    pcm = PCM_DIR / f"{name}.pcm"
    await edge_tts.Communicate(text, VOICE).save(str(mp3))
    subprocess.run([
        FFMPEG, "-y", "-i", str(mp3), "-ar", str(RATE), "-ac", "1", "-f", "s16le", str(pcm)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"generated {pcm.name} {pcm.stat().st_size} bytes <- {text!r}")

async def main():
    for name, text in items:
        await one(name, text)

asyncio.run(main())
PY

TOKEN=$(docker exec -w /app modstore_deploy-api-1 python -c "from modstore_server.auth_service import create_access_token; print(create_access_token(1,'speech-smoke'))")
export ASR_TOKEN="$TOKEN"
export ASR_PCM_DIR="$PCM_DIR"
export ASR_WS_URL="ws://127.0.0.1:8765/api/asr/funasr"

echo "=== local API ==="
python3 /tmp/test_asr_send_pcm.py
echo ""
echo "=== public WSS ==="
ASR_WS_URL="wss://xiu-ci.com/api/asr/funasr" python3 /tmp/test_asr_send_pcm.py
