#!/usr/bin/env python3
"""Probe local voice WebSocket endpoints (no auth = expect ready or error after accept)."""

from __future__ import annotations

import asyncio
import sys

import websockets


async def probe(url: str) -> None:
    try:
        async with websockets.connect(url, open_timeout=8) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"OK {url} -> {msg[:120]}")
    except Exception as exc:
        print(f"FAIL {url} -> {exc}")


async def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:9999"
    token = sys.argv[2] if len(sys.argv) > 2 else ""
    q = f"?token={token}" if token else ""
    await probe(f"{base}/api/workbench/voice/s2s/ws{q}")
    await probe(f"{base}/api/asr/funasr{q}")


if __name__ == "__main__":
    asyncio.run(main())
