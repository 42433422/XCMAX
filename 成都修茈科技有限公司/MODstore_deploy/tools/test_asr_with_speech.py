#!/usr/bin/env python3
"""Generate TTS speech clips and run them through FunASR via ASR proxy."""
from __future__ import annotations

import asyncio
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHUNK_SAMPLES = 960  # 60ms @ 16kHz, matches frontend FunASRBackend
SAMPLE_RATE = 16000

PHRASES = [
    "你好，今天天气怎么样",
    "帮我查一下订单状态",
    "打开工作台首页",
]

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


def _require(cmd: str) -> str:
    import shutil

    override = os.getenv("FFMPEG") if cmd == "ffmpeg" else None
    if override and Path(override).exists():
        return override
    path = shutil.which(cmd)
    if not path:
        raise RuntimeError(f"缺少依赖: {cmd}（可设置 FFMPEG=/path/to/ffmpeg）")
    return path


async def synthesize_pcm(text: str, workdir: Path) -> bytes:
    import edge_tts

    workdir.mkdir(parents=True, exist_ok=True)
    mp3 = workdir / "utt.mp3"
    pcm = workdir / "utt.pcm"
    voice = os.getenv("ASR_TEST_VOICE", "zh-CN-XiaoxiaoNeural")
    await edge_tts.Communicate(text, voice).save(str(mp3))
    ffmpeg = _require("ffmpeg")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(mp3),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-f",
            "s16le",
            str(pcm),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    data = pcm.read_bytes()
    if len(data) < CHUNK_SAMPLES * 2:
        raise RuntimeError(f"PCM 过短: {len(data)} bytes for {text!r}")
    return data


def iter_pcm_chunks(pcm: bytes):
    step = CHUNK_SAMPLES * 2
    for i in range(0, len(pcm), step):
        yield pcm[i : i + step]


def build_ws_url() -> str:
    base = os.getenv("ASR_WS_URL", "ws://127.0.0.1:8765/api/asr/funasr")
    token = os.getenv("ASR_TOKEN", "")
    if token and "token=" not in base:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}token={token}"
    return base


def ensure_token() -> None:
    if os.getenv("ASR_TOKEN"):
        return
    try:
        from modstore_server.auth_service import create_access_token

        os.environ["ASR_TOKEN"] = create_access_token(1, "asr-speech-smoke")
    except Exception:
        pass


async def recognize_pcm(pcm: bytes, label: str) -> dict:
    import websockets

    url = build_ws_url()
    texts: list[str] = []
    finals: list[str] = []
    t0 = time.time()

    async with websockets.connect(url, open_timeout=15, max_size=8 * 1024 * 1024) as ws:
        hello = await asyncio.wait_for(ws.recv(), timeout=10)
        hello_j = json.loads(hello)
        if hello_j.get("type") == "error":
            return {"label": label, "ok": False, "error": hello_j.get("message"), "latency_ms": 0}

        await ws.send(json.dumps(CFG))
        chunks = 0
        for chunk in iter_pcm_chunks(pcm):
            if len(chunk) < CHUNK_SAMPLES * 2:
                chunk = chunk + b"\x00" * (CHUNK_SAMPLES * 2 - len(chunk))
            await ws.send(chunk)
            chunks += 1
            # 模拟实时送帧，避免一次性灌入
            await asyncio.sleep(0.03)

        await ws.send(json.dumps({"is_speaking": False}))

        deadline = time.time() + 12
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
    ensure_token()
    if not os.getenv("ASR_TOKEN") and "127.0.0.1" not in build_ws_url():
        print("FAIL: 公网测试需要 ASR_TOKEN 或在 API 容器内运行")
        return 1

    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("FAIL: 需要 edge-tts，请在 API 容器内运行")
        return 1

    _require("ffmpeg")
    results = []
    with tempfile.TemporaryDirectory(prefix="asr_speech_") as td:
        work = Path(td)
        for i, phrase in enumerate(PHRASES):
            print(f"\n=== TTS + ASR: {phrase!r} ===")
            pcm = await synthesize_pcm(phrase, work / f"utt_{i}")
            print(f"pcm={len(pcm)} bytes (~{len(pcm)/2/SAMPLE_RATE:.1f}s)")
            result = await recognize_pcm(pcm, phrase)
            results.append(result)
            status = "PASS" if result["ok"] else "FAIL"
            print(f"{status} text={result.get('text')!r} latency={result['latency_ms']}ms chunks={result['chunks']}")
            if result.get("partials"):
                print("partials:", " | ".join(result["partials"]))

    passed = sum(1 for r in results if r["ok"])
    print(f"\n=== SUMMARY {passed}/{len(results)} passed ===")
    for r in results:
        mark = "OK" if r["ok"] else "XX"
        print(f"  [{mark}] {r['label']!r} -> {r.get('text')!r}")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
