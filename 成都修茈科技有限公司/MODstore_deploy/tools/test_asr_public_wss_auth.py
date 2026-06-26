#!/usr/bin/env python3
"""公网 WSS ASR 冒烟：带 token 握手 + 可选 TTS 语音识别。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ASR_CFG = {
    "mode": "2pass",
    "chunk_size": [5, 10, 5],
    "chunk_interval": 10,
    "encoder_chunk_look_back": 4,
    "decoder_chunk_look_back": 0,
    "wav_name": "mic",
    "wav_format": "pcm",
    "audio_fs": 16000,
    "is_speaking": True,
    "hotwords": "",
    "itn": True,
}


def ensure_token() -> str:
    tok = os.getenv("ASR_TOKEN", "").strip()
    if tok:
        return tok
    os.chdir(ROOT)
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from modstore_server.auth_service import create_access_token

    return create_access_token(1, "public-wss-smoke")


async def main() -> int:
    import websockets

    base = os.getenv("ASR_WS_URL", "wss://xiu-ci.com/api/asr/funasr")
    token = ensure_token()
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}token={token}"
    print("connect", url[:72] + "...")

    import ssl

    ctx = ssl.create_default_context()
    async with websockets.connect(url, ssl=ctx, open_timeout=15) as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print("hello:", msg)
        if msg.get("type") == "error":
            print("FAIL:", msg.get("message"))
            return 1
        await ws.send(json.dumps(ASR_CFG))
        await ws.send(b"\x00" * 5760)
        await ws.send(json.dumps({"is_speaking": False}))
        texts = []
        while len(texts) < 3:
            try:
                r = await asyncio.wait_for(ws.recv(), timeout=3)
            except asyncio.TimeoutError:
                break
            if isinstance(r, str):
                j = json.loads(r)
                t = str(j.get("text") or "").strip()
                if t:
                    texts.append(t)
                    print("text:", t)
    print("PASS connected + proxy OK" if msg.get("type") == "connected" else "FAIL")
    return 0 if msg.get("type") == "connected" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
