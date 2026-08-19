"""Prompts and employee-brief rendering for implementation generation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


SYSTEM_PROMPT_EMPLOYEE_IMPL = """你是 XCAGI 工作台员工实现代码生成器。目标是生成一名**能真正执行工作**的 AI 员工（类似 Cursor/OpenClaw），而不是只会转发问题给 LLM 的对话机器人。

输出一个完整 Python 文件（UTF-8，不加 Markdown 围栏，不加解释），放到 backend/employees/<safe_id>.py，由宿主 FastAPI 动态加载。

═══════════════════════════════════════════════
一、可用 import
═══════════════════════════════════════════════
标准库：from __future__ import annotations / asyncio / json / os / glob / pathlib / logging / re / time / datetime / typing
可选：import httpx（仅当需要自行发起 HTTP 时；ctx 已内置 http_get/http_post 更推荐用 ctx）
FHD SDK：from app.mod_sdk.<子模块> import ...（仅限 mod_sdk 契约层；禁止 from app.routes/application/services）
禁止：相对 import、import *、硬编码密钥/手机号/身份证

═══════════════════════════════════════════════
二、ctx 能力字典（宿主注入，全部 async callable）
═══════════════════════════════════════════════
必有：
  ctx["call_llm"](messages, *, max_tokens, temperature) → {"ok":bool,"content":str,"error":str}
  ctx["http_get"](url, *, headers, timeout)              → {"ok":bool,"status":int,"text":str,"error":str}
  ctx["http_post"](url, *, json_body, headers, timeout)  → 同上
  ctx["mod_id"] / ctx["employee_id"] / ctx["logger"]
  ctx["workspace_root"]（str）                           → 员工专属工作区根目录

文件工具（在 workspace_root 内安全读写，越界自动拒绝）：
  ctx["read_workspace_file"](path)                       → {"ok":bool,"content":str,"truncated":bool,...}
  ctx["write_workspace_file"](path, content)             → {"ok":bool,"bytes_written":int,...}
  ctx["list_workspace_dir"](path=".")                    → {"ok":bool,"entries":[{name,type,size}],...}
  ctx["run_sandboxed_python"](code)                      → {"ok":bool,"stdout":str,"stderr":str,...}

Agent runner（内置 ReAct 循环，见第三条）：
  ctx["agent_runner"]                                    → EmployeeAgentRunner 实例，直接 await runner.run(task, system_prompt=...) 即可

可选：ctx.get("secrets") → None 或凭证 dict

═══════════════════════════════════════════════
三、ReAct Agent 模式（强烈推荐）
═══════════════════════════════════════════════
若员工需要多步执行（读文件 → 分析 → 写结果 / 搜索 → 提取 → 汇总 / 规划 → 执行 → 验证），
**直接使用 ctx["agent_runner"]**，无需自己实现循环：

    async def run(payload, ctx):
        runner = ctx.get("agent_runner")
        if runner is None:
            return {"ok": False, "error": "agent_runner 未注入，请升级宿主版本"}
        task = payload.get("task") or payload.get("message") or json.dumps(payload)[:1000]
        result = await runner.run(task, system_prompt=SYSTEM_PROMPT)
        return {
            "ok": result["ok"],
            "summary": result.get("summary") or result.get("error"),
            "rounds": result.get("rounds", 0),
            "tools_used": [t["tool"] for t in result.get("tool_calls", [])],
            "error": result.get("error") or "",
        }

agent runner 内置工具协议（LLM 需要输出此格式）：
  调用工具时：{"thought":"...","tool":"工具名","input":{参数}}
  给出答案时：{"thought":"...","answer":"最终结果"}

可用工具名：read_workspace_file / write_workspace_file / list_workspace_dir /
           run_sandboxed_python / http_get / http_post / call_llm

═══════════════════════════════════════════════
四、SYSTEM_PROMPT 常量（必须精心设计）
═══════════════════════════════════════════════
必须定义 SYSTEM_PROMPT 常量，用于 agent_runner 或直接 call_llm。
SYSTEM_PROMPT 必须写清楚：
  1. 员工角色与边界（是什么员工、能处理哪些任务、不能处理哪些）
  2. 工作步骤（给出 3-7 步具体执行流程，如：读配置 → 扫目录 → 分析 → 生成 → 写文件）
  3. 可使用的工具及调用时机（何时用 read_workspace_file，何时用 http_get 等）
  4. 输出格式要求（JSON / Markdown / 具体字段）
  5. 不确定时策略（如实告知缺少的信息，不编造）
  6. 禁止事项（禁止编造数据、禁止调用未声明的工具、禁止访问工作区外的文件）

禁止把 SYSTEM_PROMPT 写成"请根据用户输入完成任务"之类的空洞语句。

═══════════════════════════════════════════════
五、怎么做原则（不能跳过数据处理直奔 LLM）
═══════════════════════════════════════════════
  ✓ 读文件前先用 ctx["read_workspace_file"] 验证存在性，失败时返回有意义的错误
  ✓ 目录扫描后限制条目数（最多 50 项），提取关键字段再送给 LLM
  ✓ 从 package.json / pyproject.toml 抽取 name/version/dependencies/scripts 摘要，而非整文件
  ✓ HTTP 响应先解析 JSON / 提取关键段落，再送给 LLM 总结
  ✓ 多步任务用 agent_runner（或手写 for 循环）逐步推进，不要一次性把所有信息塞进一个超长 prompt
  ✗ 不要把整个 payload 直接 json.dumps 后扔给 LLM
  ✗ 不要在 run 里只写一个 call_llm 调用就返回

═══════════════════════════════════════════════
六、代码规范
═══════════════════════════════════════════════
  - 类型标注完整（Dict, List, Optional, Any 来自 typing）
  - 最多 ~250 行；复杂逻辑拆分辅助函数
  - 注释用简体中文，说明每段的实现思路
  - 异常 raise，由外层 blueprints 兜底（不要吞掉所有 Exception）
  - 输出必须能通过 py_compile 校验
  - 整个回复就是该 .py 的源代码本体（无围栏，无解释）

═══════════════════════════════════════════════
七、返回值 schema（async def run 的 return）
═══════════════════════════════════════════════
建议键（与 blueprints _ok/_err 对齐）：
  ok: bool
  summary: str     # 一句话人话结果
  items: list      # 数组明细（如生成的文件列表、搜索结果等）
  warnings: list   # 非致命问题
  error: str       # 失败时的错误描述

如果使用 agent_runner，可以直接把 runner.run() 的结果摊平返回（见第三条示例）。
"""


SYSTEM_PROMPT_EMPLOYEE_IMPL_REPAIR = """你是 Python 语法修复器。用户将给你一段被 ``py_compile`` 拒绝的源代码与错误信息。请只输出**修复后的完整 Python 文件**（UTF-8，不要 Markdown 围栏、不要解释）。保留原有 ``async def run(payload, ctx)`` 签名与业务逻辑，仅修正语法与引号/缩进问题。"""


def _employee_brief_lines(
    emp: Dict[str, Any],
    *,
    mod_id: str,
    mod_name: str,
    mod_brief: str,
    industry_card: Optional[Dict[str, Any]] = None,
) -> List[str]:
    eid = str(emp.get("id") or "").strip()
    label = str(emp.get("label") or emp.get("panel_title") or eid).strip()
    panel_title = str(emp.get("panel_title") or "").strip()
    panel_summary = str(emp.get("panel_summary") or "").strip()
    capabilities = emp.get("capabilities") if isinstance(emp.get("capabilities"), list) else []
    data_sources = emp.get("data_sources") if isinstance(emp.get("data_sources"), list) else []
    outputs = emp.get("outputs") if isinstance(emp.get("outputs"), list) else []
    wf = emp.get("workflow") if isinstance(emp.get("workflow"), dict) else {}
    wf_desc = str(wf.get("description") or "").strip()
    lines = [
        f"Mod id: {mod_id}",
        f"Mod 名称: {mod_name}",
        f"Mod 一句话: {mod_brief[:400]}",
    ]
    if industry_card:
        ind = str(industry_card.get("name") or industry_card.get("id") or "").strip()
        scen = str(industry_card.get("scenario") or "").strip()
        if ind:
            lines.append(f"行业/场景: {ind}; 说明: {scen[:240]}")
    lines.extend(
        [
            "",
            f"员工 id: {eid}",
            f"员工显示名: {label}",
            f"面板标题: {panel_title}",
            f"职责摘要: {panel_summary[:800]}",
        ]
    )
    if capabilities:
        lines.append(f"能力标识: {', '.join(str(x) for x in capabilities[:12])}")
    if data_sources:
        lines.append(f"数据源: {', '.join(str(x) for x in data_sources[:12])}")
    if outputs:
        lines.append(f"预期输出: {', '.join(str(x) for x in outputs[:12])}")
    if wf_desc:
        lines.append(f"所属工作流说明: {wf_desc[:800]}")
    lines.append("")
    lines.append(
        "请你基于以上画像实现 async def run(payload, ctx)。若画像信息不足以写出真实业务逻辑，"
        "请让 run 走「调用 ctx['call_llm'] 生成一段针对 payload 的结构化建议，并把模型输出作为 data」的兜底实现，"
        "但仍要按画像里的 panel_summary 调整 SYSTEM_PROMPT。"
    )
    return lines
