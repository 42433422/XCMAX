"""Generic fallback employee implementation."""

from __future__ import annotations

import json
from typing import Any, Dict

EMPLOYEE_LABEL = "员工"
SYSTEM_PROMPT = "根据 payload 完成员工任务并返回结构化结果。"


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    call_llm = ctx.get("call_llm")
    if not callable(call_llm):
        return {
            "summary": "ctx.call_llm 未注入；请在宿主 build_run_context 中挂载 LLM 调度。",
            "items": [],
            "warnings": ["call_llm_missing"],
        }
    user_msg = json.dumps(payload or {}, ensure_ascii=False)[:4000]
    result = await call_llm(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=1024,
        temperature=0.2,
    )
    if not result.get("ok"):
        return {
            "summary": f"员工 {EMPLOYEE_LABEL} 调用 LLM 失败："
            + str(result.get("error") or "")[:300],
            "items": [],
            "warnings": ["call_llm_failed"],
        }
    return {
        "summary": str(result.get("content") or "").strip()[:2000],
        "items": [],
        "warnings": [],
    }
