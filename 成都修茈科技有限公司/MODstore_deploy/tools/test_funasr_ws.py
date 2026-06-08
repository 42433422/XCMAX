#!/usr/bin/env python3
import asyncio
import os
import socket
import sys

HOST = os.getenv("FUNASR_HOST", "funasr")
PORT = int(os.getenv("FUNASR_PORT", "10095"))


def tcp_test():
    try:
        s = socket.create_connection((HOST, PORT), 5)
        s.close()
        print(f"TCP {HOST}:{PORT} OK")
        return True
    except Exception as e:
        print(f"TCP {HOST}:{PORT} FAIL: {e}")
        return False


async def ws_test():
    import websockets

    url = f"ws://{HOST}:{PORT}"
    try:
        ws = await asyncio.wait_for(websockets.connect(url), timeout=5)
        print(f"WS {url} OK")
        await ws.close()
        return True
    except Exception as e:
        print(f"WS {url} FAIL: {e}")
        return False


if __name__ == "__main__":
    ok = tcp_test()
    ok = asyncio.run(ws_test()) and ok
    sys.exit(0 if ok else 1)
