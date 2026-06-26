#!/usr/bin/env python3
"""本地验证 MiMo（xiaomi）平台密钥与网关。用法：.venv_local/bin/python scripts/verify_mimo_local.py"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)
load_dotenv(ROOT / ".env.local", override=True)

from modstore_server.llm_chat_proxy import chat_dispatch
from modstore_server.llm_key_resolver import platform_api_key, platform_base_url


async def main() -> int:
    key = platform_api_key("xiaomi")
    base = platform_base_url("xiaomi")
    if not key:
        print("FAIL: 未配置 MIMO_API_KEY / XIAOMI_API_KEY / XIAOMI_MIMO_API_KEY")
        return 1
    print(f"base_url={base}")
    res = await chat_dispatch(
        "xiaomi",
        api_key=key,
        base_url=base,
        model="mimo-v2.5-pro",
        messages=[{"role": "user", "content": "只回复：连通"}],
        max_tokens=32,
    )
    if res.get("ok"):
        print("OK:", (res.get("content") or "")[:200])
        return 0
    err = str(res.get("error") or "")[:400]
    print("FAIL:", err)
    if "502" in err:
        print(
            "提示：国内 token-plan-cn 网关若 502，请到 https://platform.xiaomimimo.com/ "
            "订阅页核对专属 Base URL 与集群（cn/sgp/ams）；tp- 密钥不能跨集群使用。"
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
