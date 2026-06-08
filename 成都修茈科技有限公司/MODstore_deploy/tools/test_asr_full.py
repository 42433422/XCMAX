#!/usr/bin/env python3
import asyncio
import json
import struct
import sys

from modstore_server.auth_service import create_access_token


async def main():
    token = create_access_token(1, "test-asr-probe")
    url = f"ws://127.0.0.1:8765/api/asr/funasr?token={token}"
    print("token len", len(token))
    import websockets

    async with websockets.connect(url, open_timeout=10) as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=10)
        print("connected msg:", msg)
        cfg = {
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
        await ws.send(json.dumps(cfg))
        print("sent config")
        # 960 samples int16 silence
        silence = struct.pack("<960h", *([0] * 960))
        for i in range(5):
            await ws.send(silence)
        await ws.send(json.dumps({"is_speaking": False}))
        print("sent audio + end")
        for _ in range(5):
            try:
                r = await asyncio.wait_for(ws.recv(), timeout=3)
                print("asr:", r[:300])
            except asyncio.TimeoutError:
                print("no more msgs")
                break
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
