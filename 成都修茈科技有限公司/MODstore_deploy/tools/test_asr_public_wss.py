#!/usr/bin/env python3
import asyncio
import ssl
import sys

import websockets


async def main():
    url = "wss://xiu-ci.com/api/asr/funasr"
    ctx = ssl.create_default_context()
    try:
        async with websockets.connect(url, ssl=ctx, open_timeout=10) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            print("public wss OK:", msg[:200])
            return 0
    except Exception as e:
        print("public wss FAIL:", e)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
