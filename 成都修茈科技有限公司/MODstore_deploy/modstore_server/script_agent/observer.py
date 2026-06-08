"""``observer`` —— 判断脚本运行结果是否满足 plan 的验收标准。

短路规则：
- 进程超时 / 非零退出码 / 无产物 → 直接 ``ok=False``，不调 LLM
- 否则把 stdout/stderr 末段、产物清单、plan 验收喂给 LLM 做"判官"，要求输出 JSON
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from modstore_server.script_agent.brief import Brief, PlanResult, Verdict
from modstore_server.script_agent.llm_client import SCRIPT_AGENT_JUDGE_MAX_TOKENS, LlmClient
from modstore_server.script_agent.sandbox_runner import SandboxResult

OBSERVE_SYSTEM_PROMPT = """\
你是 Python 编程代理的"验收官"。基于 plan.md 中"验收标准"判断脚本本次运行是否通过。
仅输出 JSON 对象，不要解释；schema:
{"ok": true|false, "reason": "<一句话原因>", "suggestions": ["<下一轮可改进的建议，1-3 条>"]}"""


def _short(text: str, n: int = 4000) -> str:
    if len(text) <= n:
        return text
    return text[: n // 2] + "\n…[省略]…\n" + text[-n // 2 :]


def _parse_verdict(raw: str) -> Verdict:
    text = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 兜底：从原文里识别明显的 ok 字样
        ok = bool(re.search(r"\b\"?ok\"?\s*:\s*true\b", raw, re.I))
        return Verdict(
            ok=ok,
            reason="LLM 返回非 JSON，已尝试启发式解析",
            suggestions=[],
        )
    suggestions: List[str] = []
    raw_sugg = data.get("suggestions") or []
    if isinstance(raw_sugg, list):
        suggestions = [str(s) for s in raw_sugg if isinstance(s, (str, int, float))]
    return Verdict(
        ok=bool(data.get("ok")),
        reason=str(data.get("reason") or ""),
        suggestions=suggestions,
    )


async def judge(
    brief: Brief,
    plan: PlanResult,
    result: SandboxResult,
    *,
    llm: LlmClient,
    max_tokens: int = SCRIPT_AGENT_JUDGE_MAX_TOKENS,
) -> Verdict:
    if result.timed_out:
        return Verdict(ok=False, reason=f"脚本超时：{', '.join(result.errors)}")
    if result.returncode != 0:
        return Verdict(
            ok=False,
            reason=f"脚本退出码 {result.returncode}",
            suggestions=[result.stderr[-500:].strip()] if result.stderr else [],
        )
    if not result.outputs:
        return Verdict(ok=False, reason="没有产物文件，至少需要 outputs/ 下一个文件")

    outputs_listing = "\n".join(f"- {o['filename']} ({o['size']}B)" for o in result.outputs)
    user_msg = (
        "# 用户需求\n"
        + brief.as_markdown()
        + "\n\n# 计划\n"
        + plan.plan_md
        + "\n\n# 运行 stdout\n"
        + _short(result.stdout)
        + "\n\n# 运行 stderr\n"
        + _short(result.stderr)
        + "\n\n# outputs/ 产物清单\n"
        + outputs_listing
    )
    raw = await llm.chat(
        [
            {"role": "system", "content": OBSERVE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=max_tokens,
    )
    return _parse_verdict(raw)
