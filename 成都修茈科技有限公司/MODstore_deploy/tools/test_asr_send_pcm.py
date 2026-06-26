#!/usr/bin/env python3
"""Only send pre-generated 16kHz s16le PCM files through ASR proxy."""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import time
from pathlib import Path

CHUNK_SAMPLES = 960
SAMPLE_RATE = 16000
CFG = {
    "mode": "2pass",
    "chunk_size": [5, 10, 5],
    "chunk_interval": 10,
    "encoder_chunk_look_back": 4,
    "decoder_chunk_look_back": 0,
    "wav_name": "mic",
    "wav_format": "pcm",
    "audio_fs": SAMPLE_RATE,
    "is_speaking": True,
    "hotwords": "",
    "itn": True,
}


def build_ws_url() -> str:
    base = os.getenv("ASR_WS_URL", "ws://127.0.0.1:8765/api/asr/funasr")
    token = os.getenv("ASR_TOKEN", "")
    if token and "token=" not in base:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}token={token}"
    return base


def iter_pcm_chunks(pcm: bytes):
    step = CHUNK_SAMPLES * 2
    for i in range(0, len(pcm), step):
        yield pcm[i : i + step]


async def recognize_pcm(pcm: bytes, label: str) -> dict:
    import ssl
    import websockets

    url = build_ws_url()
    texts: list[str] = []
    finals: list[str] = []
    chunks = 0
    t0 = time.time()
    connect_kw: dict = {"open_timeout": 15, "max_size": 8 * 1024 * 1024}
    if url.startswith("wss://"):
        connect_kw["ssl"] = ssl.create_default_context()

    try:
        async with websockets.connect(url, **connect_kw) as ws:
            hello = await asyncio.wait_for(ws.recv(), timeout=10)
            hello_j = json.loads(hello)
            if hello_j.get("type") == "error":
                return {
                    "label": label,
                    "ok": False,
                    "error": hello_j.get("message"),
                    "latency_ms": int((time.time() - t0) * 1000),
                }

            await ws.send(json.dumps(CFG))
            for chunk in iter_pcm_chunks(pcm):
                if len(chunk) < CHUNK_SAMPLES * 2:
                    chunk = chunk + b"\x00" * (CHUNK_SAMPLES * 2 - len(chunk))
                await ws.send(chunk)
                chunks += 1
                await asyncio.sleep(0.03)

            await ws.send(json.dumps({"is_speaking": False}))

            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                except asyncio.TimeoutError:
                    if finals:
                        break
                    continue
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                text = str(msg.get("text") or "").strip()
                if text:
                    texts.append(text)
                    if msg.get("is_final"):
                        finals.append(text)
    except Exception as e:
        return {
            "label": label,
            "ok": False,
            "error": str(e),
            "latency_ms": int((time.time() - t0) * 1000),
        }

    latency_ms = int((time.time() - t0) * 1000)
    final_text = finals[-1] if finals else (texts[-1] if texts else "")
    return {
        "label": label,
        "ok": bool(final_text),
        "text": final_text,
        "partials": texts,
        "chunks": chunks,
        "pcm_bytes": len(pcm),
        "latency_ms": latency_ms,
    }


async def main() -> int:
    pcm_dir = Path(os.getenv("ASR_PCM_DIR", "/tmp/asr_pcm_samples"))
    if not pcm_dir.is_dir():
        print(f"FAIL: PCM 目录不存在 {pcm_dir}")
        return 1

    files = sorted(pcm_dir.glob("*.pcm"))
    if not files:
        print(f"FAIL: {pcm_dir} 下无 .pcm 文件")
        return 1

    results = []
    for f in files:
        label = f.stem
        pcm = f.read_bytes()
        print(f"\n=== ASR: {label!r} pcm={len(pcm)} ===")
        result = await recognize_pcm(pcm, label)
        results.append(result)
        mark = "PASS" if result["ok"] else "FAIL"
        err = result.get("error")
        extra = f" error={err!r}" if err else ""
        print(f"{mark} -> {result.get('text')!r} ({result['latency_ms']}ms){extra}")
        if result.get("partials"):
            print("partials:", " | ".join(result["partials"]))

    passed = sum(1 for r in results if r["ok"])
    print(f"\n=== SUMMARY {passed}/{len(results)} ===")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
