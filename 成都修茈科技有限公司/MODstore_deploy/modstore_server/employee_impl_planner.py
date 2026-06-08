"""brief → 员工实现规划器（Phase 3 第一步）。

把用户自然语言 brief 拆成一个**可执行**的实现计划：
- handlers：本次员工真正会跑的分支（仅限 ``echo`` / ``llm_md`` / ``webhook`` / ``vibe_*``）
- io_schemas：每个 handler 的输入/输出字段约定（用于后续生成代码 + 校验）
- tools_required：是否需要读 package.json / 扫目录 / HTTP 抓取等宿主受控工具

下游可以：
1. 用 :func:`inject_plan_into_manifest` 把规划结果回写到 ``employee_config_v2.actions``，
   让 manifest 与运行时实际行为完全对齐（消除 actions.handlers=["echo"] 但实跑 LLM 的根因）。
2. 用 :func:`plan_to_vibe_brief` 把每个 handler 的 io_schema 翻译成 vibe-coding 能消费的
   brief，由 :mod:`vibe_coding` 生成包内 ``backend/employees/*.py``，与画布 ESkill 同源。

本模块**不**直接发起 LLM 请求；调用方传入 ``llm_chat`` 异步函数（接收 messages、
返回 content 字符串）。这样即可在测试 / 离线场景下注入桩，避免双轨耦合。

可被 :func:`modstore_server.employee_ai_scaffold.build_employee_pack_zip` 通过
``code_generator=`` 参数接入；当前主链未启用，等编排侧准备好再切换，避免拖慢 8 步流水线。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

# ── 合法 handler 集合（与 employee_pack_blueprints_template._DISPATCH 一致）────
LEGAL_HANDLERS = ("echo", "llm_md", "webhook", "vibe_edit", "vibe_heal", "vibe_code")

# ── 受控宿主工具白名单（供 prompt 声明，禁止 LLM 假装能读 fs）──────────────
HOST_TOOLS = {
    "read_package_json": "读取调用方传入路径下的 package.json 并返回 dict；路径需在工作区白名单内",
    "scan_directory": "列出指定子目录下文件名（非递归），用于让员工知道仓库结构",
    "http_get": "通过 ctx.http_get 发起 GET 请求；不可硬编码内网地址",
}


@dataclass
class HandlerSpec:
    """一个 handler 的完整契约。"""

    name: str
    purpose: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass
class EmployeePackPlan:
    """员工包实现计划。"""

    handlers: List[HandlerSpec]
    tools_required: List[str] = field(default_factory=list)
    rationale: str = ""

    def declared_handler_names(self) -> List[str]:
        return [h.name for h in self.handlers]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "handlers": [asdict(h) for h in self.handlers],
            "tools_required": list(self.tools_required),
            "rationale": self.rationale,
        }


# ── prompt ────────────────────────────────────────────────────────────────────

_SYS_PLAN = """你是 XCAGI 员工实现规划器。读用户的 brief，输出一份**可执行**的实现计划，
帮助下游代码生成器写出真正干活、而不是把 payload 转发给 LLM 的员工代码。

只输出一个 JSON 对象（不要 Markdown 围栏），字段：
- handlers: 数组，每项 = {name, purpose, input_schema, output_schema, notes}
  * name 仅限：echo / llm_md / webhook / vibe_edit / vibe_heal / vibe_code
  * 想让模型回话写 "llm_md"，**不要写 "echo" 撒谎**
  * input_schema / output_schema 用 JSON Schema 风格描述（type/properties/required）
- tools_required: 数组，从受控工具白名单中挑选；不在白名单的工具一律不要写
  受控工具白名单：
{tools}
- rationale: 不超过 80 字，说明为什么挑这些 handlers / tools

约束：
1. handlers 数组至少 1 个、至多 4 个；按主路径排在前面
2. 同一 brief 不要同时声明 echo 和 llm_md（互斥；echo 只在用户明确要求"原样回显"时使用）
3. 若 brief 提到"读代码 / 改文件 / refactor / heal"等关键词，可加入 vibe_edit / vibe_heal
4. tools_required 必须真实可用；不要编造 read_database / call_external_api 这种没有的工具
"""


def _sys_plan_prompt() -> str:
    tool_lines = "\n".join(f"  - {k}: {v}" for k, v in HOST_TOOLS.items())
    return _SYS_PLAN.format(tools=tool_lines)


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


# ── public API ────────────────────────────────────────────────────────────────

LlmChat = Callable[[List[Dict[str, str]]], Awaitable[str]]


async def plan_employee_implementation(
    brief: str,
    *,
    llm_chat: LlmChat,
    fallback_handler: str = "llm_md",
) -> Tuple[Optional[EmployeePackPlan], str]:
    """主入口：brief → :class:`EmployeePackPlan`。

    解析失败时返回 ``(None, error)``；空 brief 返回单 handler 兜底计划。
    """
    brief = (brief or "").strip()
    if not brief:
        return _fallback_plan(fallback_handler, reason="brief 为空"), ""

    try:
        content = await llm_chat(
            [
                {"role": "system", "content": _sys_plan_prompt()},
                {"role": "user", "content": brief[:6000]},
            ]
        )
    except Exception as e:  # noqa: BLE001
        return _fallback_plan(fallback_handler, reason=f"LLM 不可用：{e}"), ""

    raw = _strip_fence(str(content or ""))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"规划器返回非合法 JSON：{e}"
    if not isinstance(data, dict):
        return None, "规划器返回非对象"

    plan, err = _coerce_plan(data, fallback_handler=fallback_handler)
    if err:
        return None, err
    return plan, ""


def _coerce_plan(
    data: Dict[str, Any], *, fallback_handler: str
) -> Tuple[Optional[EmployeePackPlan], str]:
    raw_handlers = data.get("handlers")
    if not isinstance(raw_handlers, list) or not raw_handlers:
        return None, "handlers 必须是非空数组"
    seen: List[str] = []
    handlers: List[HandlerSpec] = []
    for item in raw_handlers[:4]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name not in LEGAL_HANDLERS:
            continue
        if name in seen:
            continue
        seen.append(name)
        handlers.append(
            HandlerSpec(
                name=name,
                purpose=str(item.get("purpose") or "")[:200],
                input_schema=(
                    item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {}
                ),
                output_schema=(
                    item.get("output_schema") if isinstance(item.get("output_schema"), dict) else {}
                ),
                notes=str(item.get("notes") or "")[:200],
            )
        )
    if not handlers:
        # LLM 返回了 handlers 数组但全部非法 → 回退到一条 fallback
        return _fallback_plan(fallback_handler, reason="规划器未给出合法 handler"), ""

    # echo 与 llm_md 互斥（约束 #2）
    names = {h.name for h in handlers}
    if "echo" in names and "llm_md" in names:
        handlers = [h for h in handlers if h.name != "echo"]

    raw_tools = data.get("tools_required")
    tools: List[str] = []
    if isinstance(raw_tools, list):
        for t in raw_tools:
            if isinstance(t, str) and t.strip() in HOST_TOOLS:
                tools.append(t.strip())

    return (
        EmployeePackPlan(
            handlers=handlers,
            tools_required=tools,
            rationale=str(data.get("rationale") or "")[:160],
        ),
        "",
    )


def _fallback_plan(handler: str, *, reason: str) -> EmployeePackPlan:
    h = handler if handler in LEGAL_HANDLERS else "llm_md"
    return EmployeePackPlan(
        handlers=[
            HandlerSpec(
                name=h,
                purpose="fallback：" + reason,
                input_schema={"type": "object"},
                output_schema={"type": "object", "required": ["ok", "summary"]},
                notes="规划器不可用时的兜底 handler。",
            )
        ],
        tools_required=[],
        rationale="fallback：" + reason,
    )


def inject_plan_into_manifest(manifest: Dict[str, Any], plan: EmployeePackPlan) -> Dict[str, Any]:
    """把规划写回 ``manifest.employee_config_v2.actions``，让 manifest 与运行时一致。

    幂等：重复调用结果相同。返回**新**的 manifest dict。
    """
    out = dict(manifest or {})
    v2 = (
        dict(out.get("employee_config_v2") or {})
        if isinstance(out.get("employee_config_v2"), dict)
        else {}
    )
    actions = dict(v2.get("actions") or {}) if isinstance(v2.get("actions"), dict) else {}
    actions["handlers"] = plan.declared_handler_names()
    if plan.tools_required:
        actions["tools_required"] = list(plan.tools_required)
    actions["plan"] = plan.to_dict()
    v2["actions"] = actions
    out["employee_config_v2"] = v2
    return out


def plan_to_vibe_brief(spec: HandlerSpec, *, employee_label: str) -> str:
    """把单个 handler 翻译成 vibe-coding 可消费的 brief。

    下游可以把它喂给 :class:`vibe_coding.NLCodeSkillFactory.code` 来生成实现，
    替代 :func:`render_employee_pack_employee_py` 的静态模板（双轨合并）。
    """
    return (
        f"为员工「{employee_label}」生成 handler={spec.name} 的实现。\n"
        f"用途：{spec.purpose}\n"
        f"输入 schema：{json.dumps(spec.input_schema, ensure_ascii=False)}\n"
        f"输出 schema：{json.dumps(spec.output_schema, ensure_ascii=False)}\n"
        f"附注：{spec.notes}\n"
        "要求：返回 dict 必须含 ok/summary/items/warnings/error/meta 六字段；"
        "异常用 try/except 兜底；不要硬编码 max_tokens（从 ctx 或 manifest 注入）。"
    )
