#!/usr/bin/env python3
"""Test ASR proxy WebSocket through nginx (health + optional token)."""

import asyncio
import json
import os
import sys

import websockets

URL = os.getenv("ASR_WS_URL", "ws://127.0.0.1:8765/api/asr/funasr")
TOKEN = os.getenv("ASR_TOKEN", "")


async def main():
    qs = f"?token={TOKEN}" if TOKEN else ""
    url = URL + qs
    print("connecting", url[:80] + ("..." if len(url) > 80 else ""))
    try:
        async with websockets.connect(url, open_timeout=8) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=8)
            print("recv:", msg[:500])
            data = json.loads(msg)
            if data.get("type") == "error":
                print("ERROR from server:", data.get("message"))
                return 1
            if data.get("type") == "connected":
                print("connected OK, health=", data.get("health"))
                return 0
            print("unexpected:", data)
            return 1
    except Exception as e:
        print("FAIL:", e)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
