#!/usr/bin/env python3
"""通过 modstore ASR 代理发送示例 WAV，验证 offline 文本回传。"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import wave

import websockets

ROOT = os.environ.get("MODSTORE_ROOT", "/root/modstore-git/MODstore_deploy")
WAV = os.environ.get("ASR_TEST_WAV", "/tmp/asr_example.wav")


def load_pcm16_16k(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        ch, sr, sw, n = w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("need 16-bit wav")
    samples = list(struct.unpack("<" + "h" * (len(raw) // 2), raw))
    if ch == 2:
        samples = [(samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples), 2)]
    if sr != 16000:
        ratio = 16000 / sr
        out_len = int(len(samples) * ratio)
        out: list[int] = []
        for i in range(out_len):
            src = i / ratio
            j = int(src)
            frac = src - j
            a = samples[min(j, len(samples) - 1)]
            b = samples[min(j + 1, len(samples) - 1)]
            out.append(int(a + (b - a) * frac))
        samples = out
    return struct.pack("<" + "h" * len(samples), *samples)


def extract_text(msg: dict) -> str:
    direct = str(msg.get("text") or "").strip()
    if direct:
        return direct
    sents = msg.get("stamp_sents") or []
    if isinstance(sents, list) and sents:
        return "".join(str(s.get("text_seg") or "").replace(" ", "") for s in sents).strip()
    return ""


async def main() -> int:
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
    from modstore_server.auth_service import create_access_token

    token = create_access_token(1, "asr_test", is_admin=True)
    url = f"ws://127.0.0.1:9999/api/asr/funasr?token={token}"
    pcm = load_pcm16_16k(WAV)
    print(f"PCM={len(pcm)} bytes, wav={WAV}")

    results: list[str] = []
    async with websockets.connect(url, max_size=10 * 1024 * 1024) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
        print("connected:", hello)
        cfg = {
            "mode": "2pass",
            "chunk_size": [5, 10, 5],
            "chunk_interval": 10,
            "encoder_chunk_look_back": 4,
            "decoder_chunk_look_back": 0,
            "wav_name": "test",
            "wav_format": "pcm",
            "audio_fs": 16000,
            "is_speaking": True,
            "hotwords": "",
            "itn": True,
        }
        await ws.send(json.dumps(cfg))
        chunk = 960 * 2
        for i in range(0, len(pcm), chunk):
            await ws.send(pcm[i : i + chunk])
            await asyncio.sleep(0.06)
        await ws.send(json.dumps({"is_speaking": False}))
        print("is_speaking=false sent, waiting offline (max 12s)...")
        deadline = asyncio.get_event_loop().time() + 12
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                continue
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            text = extract_text(msg)
            mode = str(msg.get("mode") or "")
            if text:
                print(f"  [{mode}] {text}")
                results.append(text)
                if "offline" in mode or msg.get("is_final"):
                    break

    final = results[-1] if results else ""
    print("FINAL:", final or "(empty)")
    return 0 if final else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
