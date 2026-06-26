#!/usr/bin/env python3
import asyncio
import sys
import websockets


async def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "wss://xiu-ci.com"
    for path in (
        "/api/workbench/voice/s2s/ws",
        "/api/workbench/voice/unified/ws",
        "/api/asr/funasr",
    ):
        url = base.rstrip("/") + path
        try:
            async with websockets.connect(url, open_timeout=12) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=8)
                print(f"OK {path} -> {msg[:100]}")
        except Exception as exc:
            print(f"FAIL {path} -> {exc}")


if __name__ == "__main__":
    asyncio.run(main())
