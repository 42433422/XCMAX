"""临时：直连 mimo 看原始 chat_dispatch 响应。可删。"""
from __future__ import annotations

import asyncio
import json
import os
import sys


async def go() -> None:
    from modstore_server.llm_chat_proxy import chat_dispatch

    api_key = os.environ.get("MIMO_API_KEY", "")
    if not api_key:
        print("set MIMO_API_KEY", file=sys.stderr)
        sys.exit(2)

    model = sys.argv[1] if len(sys.argv) > 1 else "mimo-v2.5-pro"

    r = await chat_dispatch(
        "xiaomi",
        api_key=api_key,
        base_url=None,
        model=model,
        messages=[
            {"role": "system", "content": "You answer with valid JSON only, no markdown fences."},
            {"role": "user", "content": 'Respond with JSON {"hello":"world"}'},
        ],
        max_tokens=128,
    )
    print("OK" if r.get("ok") else "ERR", "model=", model)
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    asyncio.run(go())
