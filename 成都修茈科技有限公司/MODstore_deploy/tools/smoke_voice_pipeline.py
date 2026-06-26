#!/usr/bin/env python3
"""语音全链路冒烟：ASR 代理 → FunASR →（可选）TTS。

用法（在已配置 .env 的 MODstore 根目录或 API 容器内）：

  # 仅测 ASR 握手 + 静音
  python tools/smoke_voice_pipeline.py --asr-only

  # TTS + ASR 三轮（需 edge-tts、ffmpeg）
  python tools/smoke_voice_pipeline.py

  # 公网 WSS（需 ASR_TOKEN 或容器内自动签发）
  ASR_WS_URL=wss://xiu-ci.com/api/asr/funasr python tools/smoke_voice_pipeline.py

环境变量：
  ASR_WS_URL   默认 ws://127.0.0.1:9999/api/asr/funasr
  ASR_TOKEN    JWT；留空则在 MODstore 目录内自动 create_access_token
  TTS_URL      默认 http://127.0.0.1:9999/api/workbench/tts/edge
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHUNK_SAMPLES = 960
SAMPLE_RATE = 16000

ASR_CFG = {
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

PHRASES = [
    "你好，今天天气怎么样",
    "帮我查一下订单状态",
    "打开工作台首页",
]


def _root() -> Path:
    return Path(os.getenv("MODSTORE_ROOT", Path(__file__).resolve().parents[1]))


def ensure_token() -> str:
    tok = os.getenv("ASR_TOKEN", "").strip()
    if tok:
        return tok
    root = _root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
        from modstore_server.auth_service import create_access_token

        return create_access_token(1, "smoke-voice-pipeline")
    except Exception as e:
        raise RuntimeError(f"无法签发 ASR_TOKEN: {e}") from e


def build_asr_url() -> str:
    base = os.getenv("ASR_WS_URL", "ws://127.0.0.1:9999/api/asr/funasr")
    token = ensure_token()
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}token={token}"


def extract_text(msg: dict) -> str:
    direct = str(msg.get("text") or "").strip()
    if direct:
        return direct
    sents = msg.get("stamp_sents") or []
    if isinstance(sents, list) and sents:
        return "".join(str(s.get("text_seg") or "").replace(" ", "") for s in sents).strip()
    return ""


async def smoke_asr_handshake() -> dict:
    import websockets

    url = build_asr_url()
    t0 = time.time()
    async with websockets.connect(url, open_timeout=15, max_size=8 * 1024 * 1024) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        msg = json.loads(raw)
        if msg.get("type") == "error":
            return {"ok": False, "step": "handshake", "error": msg.get("message"), "ms": 0}
        if msg.get("type") != "connected":
            return {"ok": False, "step": "handshake", "error": f"unexpected: {msg}", "ms": 0}
        await ws.send(json.dumps(ASR_CFG))
        await ws.send(b"\x00" * (CHUNK_SAMPLES * 2 * 3))
        await ws.send(json.dumps({"is_speaking": False}))
        texts: list[str] = []
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                r = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                break
            if isinstance(r, bytes):
                continue
            j = json.loads(r)
            t = extract_text(j)
            if t:
                texts.append(t)
    ms = int((time.time() - t0) * 1000)
    return {
        "ok": True,
        "step": "handshake",
        "ms": ms,
        "note": "静音无文字属正常" if not texts else f"partials={texts}",
    }


async def synthesize_pcm(text: str, workdir: Path) -> bytes:
    import edge_tts

    mp3 = workdir / "utt.mp3"
    pcm = workdir / "utt.pcm"
    voice = os.getenv("ASR_TEST_VOICE", "zh-CN-XiaoxiaoNeural")
    await edge_tts.Communicate(text, voice).save(str(mp3))
    import shutil

    ffmpeg = shutil.which("ffmpeg") or os.getenv("FFMPEG", "ffmpeg")
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
    return pcm.read_bytes()


async def recognize_pcm(pcm: bytes, label: str) -> dict:
    import websockets

    url = build_asr_url()
    texts: list[str] = []
    t0 = time.time()
    async with websockets.connect(url, open_timeout=15, max_size=8 * 1024 * 1024) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if hello.get("type") == "error":
            return {"label": label, "ok": False, "error": hello.get("message"), "ms": 0}
        await ws.send(json.dumps(ASR_CFG))
        step = CHUNK_SAMPLES * 2
        for i in range(0, len(pcm), step):
            chunk = pcm[i : i + step]
            if len(chunk) < step:
                chunk = chunk + b"\x00" * (step - len(chunk))
            await ws.send(chunk)
            await asyncio.sleep(0.03)
        await ws.send(json.dumps({"is_speaking": False}))
        deadline = time.time() + 12
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                if texts:
                    break
                continue
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            text = extract_text(msg)
            if text:
                texts.append(text)
    final = texts[-1] if texts else ""
    return {
        "label": label,
        "ok": bool(final),
        "text": final,
        "partials": texts,
        "ms": int((time.time() - t0) * 1000),
    }


async def smoke_tts() -> dict:
    import urllib.request

    url = os.getenv("TTS_URL", "http://127.0.0.1:9999/api/workbench/tts/edge")
    payload = json.dumps(
        {"text": "语音服务测试", "voice": "zh-CN-XiaoxiaoNeural", "rate": 1.0}
    ).encode()
    req = urllib.request.Request(
        url, data=payload, method="POST", headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        ok = len(data) > 500
        return {"ok": ok, "step": "tts", "bytes": len(data), "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "step": "tts", "error": str(e), "ms": int((time.time() - t0) * 1000)}


async def check_funasr_direct() -> dict:
    import websockets

    host = os.getenv("FUNASR_HOST", "127.0.0.1")
    port = os.getenv("FUNASR_PORT", "10095")
    use_ssl = os.getenv("FUNASR_USE_SSL", "0").strip().lower() not in ("0", "false", "no", "off")
    scheme = "wss" if use_ssl else "ws"
    url = f"{scheme}://{host}:{port}"
    try:
        kw: dict = {"open_timeout": 4}
        if use_ssl:
            import ssl

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kw["ssl"] = ctx
        async with websockets.connect(url, **kw):
            return {"ok": True, "step": "funasr_direct", "url": url}
    except Exception as e:
        return {"ok": False, "step": "funasr_direct", "url": url, "error": str(e)}


def print_result(r: dict) -> None:
    mark = "PASS" if r.get("ok") else "FAIL"
    step = r.get("step") or r.get("label") or "?"
    extra = {k: v for k, v in r.items() if k not in ("ok", "step", "label")}
    print(f"  [{mark}] {step} {extra}")


async def smoke_unified_ws_handshake() -> dict:
    """统一语音 WS 握手（不跑 LLM）。"""
    try:
        import websockets
    except ImportError:
        return {"ok": False, "step": "unified_ws", "error": "websockets not installed"}

    base = os.getenv("UNIFIED_WS_URL", "ws://127.0.0.1:9999/api/workbench/voice/unified/ws")
    token = os.getenv("ASR_TOKEN", "").strip()
    if not token:
        try:
            root = Path(__file__).resolve().parents[1]
            sys.path.insert(0, str(root))
            from modstore_server.auth_service import create_access_token

            token = create_access_token(sub="1", username="smoke")
        except Exception as e:
            return {"ok": False, "step": "unified_ws", "error": f"no token: {e}"}
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}token={token}"
    try:
        async with websockets.connect(url, open_timeout=8) as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=6))
            if msg.get("type") not in ("ready", "connected", "error"):
                return {"ok": False, "step": "unified_ws", "first": msg}
            if msg.get("type") == "error":
                return {"ok": False, "step": "unified_ws", "error": msg.get("message")}
            return {"ok": True, "step": "unified_ws", "first": msg.get("type")}
    except Exception as e:
        return {"ok": False, "step": "unified_ws", "error": str(e)}


async def main() -> int:
    parser = argparse.ArgumentParser(description="语音 ASR/TTS 全链路冒烟")
    parser.add_argument("--asr-only", action="store_true", help="仅测 ASR 握手，不做 TTS 合成识别")
    args = parser.parse_args()

    print("=== smoke_voice_pipeline ===")
    print(f"ASR_WS_URL={os.getenv('ASR_WS_URL', 'ws://127.0.0.1:9999/api/asr/funasr')}")

    results: list[dict] = []

    r0 = await check_funasr_direct()
    results.append(r0)
    print_result(r0)

    ru = await smoke_unified_ws_handshake()
    results.append(ru)
    print_result(ru)

    r1 = await smoke_asr_handshake()
    results.append(r1)
    print_result(r1)
    if not r1.get("ok"):
        print(
            "\n断点：API 代理无法连 FunASR。检查 FUNASR_HOST / FUNASR_USE_SSL（--certfile 0 时必须为 0）"
        )
        return 1

    if not args.asr_only:
        rt = await smoke_tts()
        results.append(rt)
        print_result(rt)

        try:
            import edge_tts  # noqa: F401
        except ImportError:
            print("  [SKIP] speech 需 edge-tts")
        else:
            with tempfile.TemporaryDirectory(prefix="smoke_voice_") as td:
                work = Path(td)
                for phrase in PHRASES:
                    print(f"\n--- TTS→ASR: {phrase!r} ---")
                    pcm = await synthesize_pcm(phrase, work / "u")
                    rs = await recognize_pcm(pcm, phrase)
                    results.append(rs)
                    print_result(rs)

    passed = sum(1 for r in results if r.get("ok"))
    total = len(results)
    print(f"\n=== SUMMARY {passed}/{total} passed ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
