"""``planner`` —— 让 LLM 根据 Brief + 上下文输出执行计划 ``plan.md``。

计划是后续 ``code_writer`` / ``observer`` 的共同语言：
- 步骤列表：每步一行短句
- 输入/输出契约：路径、字段、格式
- 验收标准：可机器判定（给 ``observer`` 用）
"""

from __future__ import annotations

from typing import Optional

from modstore_server.script_agent.brief import Brief, ContextBundle, PlanResult
from modstore_server.script_agent.llm_client import SCRIPT_AGENT_PLAN_MAX_TOKENS, LlmClient

PLAN_SYSTEM_PROMPT = """\
你是 Python 编程代理的"计划官"。基于用户的任务描述，输出一份 plan.md（Markdown）。
要求：
1. 列出可顺序执行的步骤（每步一行，不超过 8 步）
2. 写明输入契约（``inputs/`` 下文件名 + 关键字段）
3. 写明输出契约（``outputs/`` 下文件名 + 字段 + 示例）
4. 写明验收标准——必须机器可判定，例如"outputs/result.json 存在且包含 'amount' 数字字段"
5. 标注哪些步骤需要调 LLM/知识库/员工（``modstore_runtime`` SDK），哪些是确定性逻辑
不要写代码，仅产出 plan.md 内容。"""


async def make_plan(
    brief: Brief,
    ctx: ContextBundle,
    *,
    llm: LlmClient,
    max_tokens: int = SCRIPT_AGENT_PLAN_MAX_TOKENS,
    plan_hint: Optional[str] = None,
) -> PlanResult:
    """同步等同 LLM 输出，纯文本即认为是 plan.md。

    ``plan_hint`` 用于"用户对中间产物给反馈"场景：把用户最新一句话拼到提示尾。
    """
    sys_msg = PLAN_SYSTEM_PROMPT
    if ctx.as_system_prompt_appendix():
        sys_msg += "\n\n# 上下文\n" + ctx.as_system_prompt_appendix()

    user_msg = ctx.brief_md
    if plan_hint and plan_hint.strip():
        user_msg += "\n\n# 用户最新反馈\n" + plan_hint.strip()

    raw = await llm.chat(
        [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=max_tokens,
    )
    return PlanResult(plan_md=(raw or "").strip(), raw=raw or "")
