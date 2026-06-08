"""临时：用真正的 SYSTEM_PROMPT_EMPLOYEE 直连 mimo，观察 content / reasoning_tokens。"""
from __future__ import annotations

import asyncio
import json
import os
import sys


async def go() -> None:
    from modstore_server.llm_chat_proxy import chat_dispatch
    from modstore_server.employee_ai_scaffold import SYSTEM_PROMPT_EMPLOYEE

    api_key = os.environ.get("MIMO_API_KEY", "")
    if not api_key:
        print("set MIMO_API_KEY", file=sys.stderr)
        sys.exit(2)

    model = sys.argv[1] if len(sys.argv) > 1 else "mimo-v2.5-pro"
    max_tokens = int(sys.argv[2]) if len(sys.argv) > 2 else 2048

    brief = "做一个【文档整理员】员工：当输入一段或多段代码变更（按文件路径列出）时，自动识别变更主题（API 路由/配置/依赖）、按段抽取关键点（请求方法、路径、参数、返回值、版本号），输出结构化 markdown 文档草稿，落到 docs/ 下对应文件。"

    r = await chat_dispatch(
        "xiaomi",
        api_key=api_key,
        base_url=None,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_EMPLOYEE},
            {"role": "user", "content": brief},
        ],
        max_tokens=max_tokens,
    )
    print("ok=", r.get("ok"))
    usage = r.get("usage") or {}
    print("usage=", json.dumps(usage, ensure_ascii=False))
    content = str(r.get("content") or "")
    print("content_len=", len(content))
    print("--- CONTENT START ---")
    print(content[:4000])
    print("--- CONTENT END ---")
    raw = r.get("raw") or {}
    if isinstance(raw, dict):
        choices = raw.get("choices") or []
        if choices:
            msg = (choices[0] or {}).get("message") or {}
            rc = msg.get("reasoning_content") or ""
            print("reasoning_content_len=", len(rc))
            print("reasoning_content_preview=", rc[:600])
            print("finish_reason=", (choices[0] or {}).get("finish_reason"))


if __name__ == "__main__":
    asyncio.run(go())
