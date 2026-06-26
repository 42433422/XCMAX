#!/usr/bin/env python3
"""TTS smoke test with JWT (run inside API container: python -m tools.test_tts_smoke)."""

import json
import sys
import time
import urllib.request

from modstore_server.auth_service import create_access_token


def main() -> int:
    token = create_access_token(1, "smoke-tts")
    body = json.dumps(
        {"text": "冒烟测试通过", "voice": "zh-CN-XiaoxiaoNeural", "rate": 1.0}
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8765/api/workbench/tts/edge",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = r.read()
            ms = int((time.time() - t0) * 1000)
            ok = len(data) > 500
            print(f"TTS {'OK' if ok else 'WARN'} bytes={len(data)} latency_ms={ms}")
            return 0 if ok else 1
    except Exception as e:
        print(f"TTS FAIL: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
