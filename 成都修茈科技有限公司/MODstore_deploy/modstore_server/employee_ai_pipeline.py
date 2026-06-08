"""7 阶段 AI 员工流水线：NL → 完整 employee_pack manifest + 实现代码。

每个阶段独立 LLM 调用 + 严格 JSON 校验；通过 on_event 回调推送 SSE 事件，
供 /api/workbench/employee-ai/draft 端点实时流式输出。

S1-S6 生成 manifest；S7 生成运行时代码（direct_python vendor/ 或 agent 实现）。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from modstore_server.employee_ai_scaffold import (
    _default_capabilities,
    _default_skill_entries,
    _normalize_behavior_rules,
    _normalize_employee_system_prompt,
    _strip_json_fence,
)
from modstore_server.script_agent.llm_client import LlmClient

# ── system prompts ────────────────────────────────────────────────────────────

_SYS_PARSE_INTENT = """你是 AI 员工意图解析器。用户用自然语言描述想要的 AI 员工。
你只输出一个 JSON 对象（不含 markdown 围栏），字段：
- id: 字符串，小写英文/数字/连字符，2-32 字符
- name: 简短中文显示名（不超过 12 字）
- role: 角色核心职能（不超过 20 字）
- scenario: 使用场景（不超过 80 字）
- industry: 行业分类（如"电商""金融""教育""通用"等）
- complexity: "low"/"medium"/"high"

示例：{"id":"refund-assistant","name":"退款客服助手","role":"退款流程处理","scenario":"用户提交退款申请后自动核查订单并输出处理意见","industry":"电商","complexity":"medium"}"""

_SYS_RANK_WORKFLOW = """你是 AI 工作流选型助手。给你员工意图描述和候选工作流列表，只输出一个 JSON 对象：
- best_index: 最匹配工作流的 index（从 0 开始），若均不匹配输出 -1
- score: 匹配度 0.0-1.0
- reason: 一句话理由（不超过 40 字）

当 score < 0.5 时，best_index 必须为 -1。"""

_SYS_DESIGN_V2 = """你是 XCAGI employee_config_v2 设计师。根据员工意图，只输出一个 JSON 对象，字段：
- perception: 对象，含 type（"text"|"document"|"event"|"web_rankings"|"multimodal"）
- memory: 对象，含 type（"session"|"long_term"|"none"）；需长期记忆时加 knowledge_base 字符串
- cognition: 对象，含 agent.system_prompt（至少 200 字专业 prompt，见要求）及 agent.model（provider/model_name/max_tokens/temperature）
- actions: 对象，含 handlers 数组（合法值见下方）

──────────────────────────────────────────────
handlers 合法值（按任务复杂度选择）：
  "agent"   → **ReAct 多步 agent 循环**（推荐）。员工可使用工具链：读写工作区文件、运行 Python、发起 HTTP。
              适用：需要多步推理、文件操作、代码执行、数据汇总等任何"做事"类任务。
  "direct_python" → **纯 Python 直接执行**，不调 LLM。员工 run(payload, ctx) 函数由宿主直接调用。
              适用：文件格式转换（Excel/Word/PDF/CSV 读取与生成）、数据提取、确定性计算等不需要 LLM 推理的任务。
              选择此 handler 时，system_prompt 可简短（描述输入输出契约即可），model 可省略。
  "llm_md"  → 单轮 LLM 调用，输出 Markdown。适用：纯问答/总结/翻译等一问一答类任务。
  "webhook" → 转发到 actions.webhook.url（必须同时提供 url）。适用：需要转发到外部 webhook 的通知类任务。
  "echo"    → 仅回显 payload，**不调 LLM**。适用：测试/调试，不要在正式员工中使用。
  "vibe_edit"  → 单轮多文件代码编辑（需配置 actions.vibe_edit.root）。
  "vibe_heal"  → 多轮代码自愈（需配置 actions.vibe_heal.root）。
  "vibe_code"  → NL → CodeSkill（需配置 actions.vibe_code.brief）。

选择原则：
  - 只要员工需要"做事"（写文件/读文件/执行步骤/多步分析/调用工具）→ 选 "agent"
  - 任务是确定性的文件处理/格式转换/数据提取，不需要 LLM 推理 → 选 "direct_python"
  - 只是"回答问题"（一问一答，不需要工具）→ 选 "llm_md"
  - 代码重构/自愈场景 → 选 vibe_edit/vibe_heal
  - 禁止在"做事"员工上写 "echo"（echo 不调 LLM，会让员工什么都做不了）
──────────────────────────────────────────────

system_prompt 要求（不少于 200 字）：
1. 必须是员工运行时真正使用的系统提示，不是产品介绍或使用说明；
2. 必须明确：
   a. 角色边界（我是谁、我能做什么、我不能做什么）
   b. 工作步骤（3-7 步具体执行流程，如：收到请求 → 读取配置 → 扫描目录 → 分析 → 生成输出 → 写入文件）
   c. 可用工具及调用时机（agent 模式下：read_workspace_file/write_workspace_file/list_workspace_dir/run_sandboxed_python 等）
   d. 输出格式（结构化 JSON / Markdown 章节 / 具体字段列表）
   e. 失败策略（工具失败如何降级，信息不足时如实告知）
   f. 禁止事项（禁止编造数据/结果/文件内容，禁止越界访问）
3. 若已绑定工作流或候选 Skill，必须在 system_prompt 中说明何时进入工作流及失败时降级方案；
4. 不要使用"用途/输入/输出/示例"模板章节，不要只复述用户 brief；
5. 不得编造未给出的外部系统状态、执行结果、数据来源。

model 建议：provider 默认 "auto"，model_name 默认 "auto"，temperature 0.2，
           agent 模式下 max_tokens 建议 2048（每轮工具调用），llm_md 模式下 max_tokens 建议 4000。"""

_SYS_SUGGEST_SKILLS = """你是 AI 技能推荐助手。根据员工角色和场景推荐合适的技能，只输出 JSON 数组（不含对象包裹），每项含：
- name: 技能名（不超过 16 字）
- brief: 技能简介（不超过 50 字）
- kind: 技能类型，从以下选一个：
    "project_directory_scan"  → 目录/文件树扫描
    "file_type_identification" → 文件类型识别与统计
    "manifest_reading"         → 读取项目配置文件（package.json/pyproject.toml/README 等）
    "readme_generation"        → 生成项目文档/README
    "code_analysis"            → 静态代码分析
    "domain_specific"          → 其他领域特定技能

推荐 2-5 个，按重要性排序。
示例：[{"name":"目录扫描","brief":"递归列出项目文件树，识别源码、配置、资源目录","kind":"project_directory_scan"}]"""

# Keywords that indicate a "project analysis / documentation" type employee.
# When detected, the pipeline forces `agent` handler and adds workspace config.
_PROJECT_ANALYSIS_KEYWORDS: frozenset = frozenset(
    {
        "readme",
        "文档",
        "documentation",
        "docs",
        "说明",
        "使用说明",
        "项目分析",
        "项目介绍",
        "技术栈",
        "目录结构",
        "安装指南",
        "部署指南",
        "生成文档",
        "generate readme",
        "generate docs",
        "project doc",
        "代码库",
        "codebase",
        "代码分析",
        "代码文件",
        "项目文件",
    }
)

_SYS_SUGGEST_PRICING = """你是 AI 定价顾问。根据员工复杂度、功能丰富度、行业特性建议定价，只输出一个 JSON 对象：
- tier: "free"/"basic"/"standard"/"pro"/"enterprise"
- cny: 月费（人民币），免费则 0
- period: "month"（月付）/ "year"（年付）/ "once"（买断）
- reasoning: 不超过 60 字的定价理由

定价参考区间：free=0，basic≤9，standard≤29，pro≤99，enterprise≥99"""

_SYS_REFINE_PROMPT = """你是专业 system prompt 优化助手。用户提供当前 system prompt 和优化指令，你须：
1. 输出优化后的 system prompt（与原文同语言，去掉废话/模糊表述，增强具体性和专业度）
2. 用一句话解释主要改动

只输出一个 JSON 对象：
- improved_prompt: 完整的优化后 system prompt（字符串）
- diff_explanation: 改动说明（不超过 80 字）"""


# ── dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class Intent:
    id: str
    name: str
    role: str
    scenario: str
    industry: str
    complexity: str  # "low" | "medium" | "high"


@dataclass
class WorkflowChoice:
    workflow_id: Optional[int]
    workflow_name: str
    match_score: float
    generated: bool
    sandbox_passed: bool = False


@dataclass
class EmployeeConfigV2:
    perception: Dict[str, Any]
    memory: Dict[str, Any]
    cognition: Dict[str, Any]
    actions: Dict[str, Any]


@dataclass
class SuggestedSkill:
    name: str
    brief: str
    unverified: bool = True
    kind: str = ""  # e.g. "project_directory_scan", "file_type_identification", etc.


def _is_project_analysis_intent(intent: Intent) -> bool:
    """Return True when the intent describes a project-analysis / doc-gen employee."""
    text = f"{intent.role} {intent.scenario}".lower()
    return any(kw in text for kw in _PROJECT_ANALYSIS_KEYWORDS)


@dataclass
class PricingHint:
    tier: str
    cny: float
    period: str
    reasoning: str


# ── JSON helpers ──────────────────────────────────────────────────────────────


def _parse_json(text: str) -> Tuple[Optional[Any], str]:
    raw = _strip_json_fence(text)
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败: {e}"


# ── stage 1: parse intent ─────────────────────────────────────────────────────


async def stage_parse_intent(brief: str, llm: LlmClient) -> Tuple[Optional[Intent], str]:
    content = await llm.chat(
        [{"role": "system", "content": _SYS_PARSE_INTENT}, {"role": "user", "content": brief}],
        max_tokens=2048,
    )
    data, err = _parse_json(content)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "LLM 须返回 JSON 对象"
    raw_id = re.sub(r"[^a-z0-9\-_]", "-", str(data.get("id") or "").lower().strip()).strip("-")
    safe_id = raw_id[:32] or "my-employee"
    return (
        Intent(
            id=safe_id,
            name=str(data.get("name") or safe_id)[:24],
            role=str(data.get("role") or "")[:40],
            scenario=str(data.get("scenario") or "")[:120],
            industry=str(data.get("industry") or "通用")[:20],
            complexity=str(data.get("complexity") or "medium").lower(),
        ),
        "",
    )


# ── stage 2: resolve workflow ─────────────────────────────────────────────────


async def stage_resolve_workflow(
    intent: Intent,
    eligible_workflows: List[Dict[str, Any]],
    llm: LlmClient,
    *,
    generate_fallback: Optional[Callable[[], Awaitable[Dict[str, Any]]]] = None,
    score_threshold: float = 0.55,
    on_progress: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Tuple[Optional[WorkflowChoice], str]:
    """LLM-rank eligible workflows; fall back to generation if score is below threshold."""
    if not eligible_workflows:
        if generate_fallback is None:
            return (
                WorkflowChoice(
                    workflow_id=None, workflow_name="", match_score=0.0, generated=False
                ),
                "",
            )
        if on_progress:
            await on_progress("未找到已通过沙箱的工作流，正在为您生成新工作流…")
        res = await generate_fallback()
        if not res.get("ok"):
            return None, f"工作流兜底生成失败: {res.get('error') or '未知错误'}"
        return (
            WorkflowChoice(
                workflow_id=int(res["workflow_id"]),
                workflow_name=str(res.get("name") or ""),
                match_score=0.0,
                generated=True,
            ),
            "",
        )

    cands = [
        {
            "index": i,
            "name": w.get("name", ""),
            "description": str(w.get("description", ""))[:120],
        }
        for i, w in enumerate(eligible_workflows)
    ]
    msg = (
        f"员工意图：{intent.role}（{intent.scenario}）\n"
        f"候选工作流：{json.dumps(cands, ensure_ascii=False)}"
    )
    content = await llm.chat(
        [{"role": "system", "content": _SYS_RANK_WORKFLOW}, {"role": "user", "content": msg}],
        max_tokens=1024,
    )
    data, err = _parse_json(content)
    if err:
        return None, err

    best_idx = int(data.get("best_index", -1))
    score = float(data.get("score", 0.0))

    if 0 <= best_idx < len(eligible_workflows) and score >= score_threshold:
        wf = eligible_workflows[best_idx]
        return (
            WorkflowChoice(
                workflow_id=int(wf["id"]),
                workflow_name=str(wf.get("name", "")),
                match_score=score,
                generated=False,
                sandbox_passed=bool(wf.get("sandbox_passed", False)),
            ),
            "",
        )

    # Score below threshold → try to generate
    if generate_fallback is None:
        return (
            WorkflowChoice(workflow_id=None, workflow_name="", match_score=score, generated=False),
            "",
        )
    if on_progress:
        await on_progress(f"现有工作流匹配度（{score:.0%}）不足，正在生成专属工作流…")
    res = await generate_fallback()
    if not res.get("ok"):
        return None, f"工作流兜底生成失败: {res.get('error') or '未知错误'}"
    return (
        WorkflowChoice(
            workflow_id=int(res["workflow_id"]),
            workflow_name=str(res.get("name") or ""),
            match_score=0.0,
            generated=True,
        ),
        "",
    )


# ── stage 3: design employee_config_v2 ───────────────────────────────────────


async def stage_design_v2(
    intent: Intent,
    workflow_choice: Optional[WorkflowChoice],
    llm: LlmClient,
    *,
    suggested_skills: Optional[List["SuggestedSkill"]] = None,
) -> Tuple[Optional[EmployeeConfigV2], str]:
    ctx_parts = [
        f"角色：{intent.role}",
        f"场景：{intent.scenario}",
        f"行业：{intent.industry}",
        f"复杂度：{intent.complexity}",
    ]
    if workflow_choice and workflow_choice.workflow_id:
        ctx_parts.append(f"已绑定工作流：{workflow_choice.workflow_name}")
        ctx_parts.append(
            "工作流使用要求：system_prompt 中必须说明该工作流是员工的执行主路径，"
            "回答前要判断是否需要进入工作流，失败时说明失败节点和下一步。"
        )
    if suggested_skills:
        ctx_parts.append(
            "候选技能：" + json.dumps([asdict(s) for s in suggested_skills[:6]], ensure_ascii=False)
        )
    content = await llm.chat(
        [
            {"role": "system", "content": _SYS_DESIGN_V2},
            {"role": "user", "content": "\n".join(ctx_parts)},
        ],
        max_tokens=4096,
    )
    data, err = _parse_json(content)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "LLM 须返回 JSON 对象"

    # Parse actions first so we know handlers before building the system prompt.
    actions = data.get("actions") or {"handlers": ["llm_md"]}
    if not isinstance(actions, dict):
        actions = {"handlers": ["llm_md"]}
    raw_handlers = actions.get("handlers")
    if not isinstance(raw_handlers, list) or not raw_handlers:
        actions["handlers"] = ["llm_md", "echo"]
    elif (
        "echo" in raw_handlers
        and "llm_md" not in raw_handlers
        and "agent" not in raw_handlers
        and "direct_python" not in raw_handlers
    ):
        # Silently upgrade hollow "echo" to "llm_md"; keep "agent"/"direct_python" if already declared.
        actions["handlers"] = ["llm_md" if h == "echo" else h for h in raw_handlers]
    if (
        "llm_md" in actions.get("handlers", [])
        and "echo" not in actions.get("handlers", [])
        and "direct_python" not in actions.get("handlers", [])
    ):
        actions["handlers"] = list(actions.get("handlers") or []) + ["echo"]

    # Project-analysis employees must run as agents to have access to file tools.
    if _is_project_analysis_intent(intent) and "agent" not in actions.get("handlers", []):
        actions["handlers"] = ["agent"]
        # Inject workspace config so the executor knows to provide file tools.
        if not isinstance(actions.get("agent"), dict):
            actions["agent"] = {}
        actions["agent"].setdefault(
            "workspace",
            {
                "mode": "user_project",
                "requires_project_root": True,
                "read_only": True,
            },
        )

    declared_handlers = list(actions.get("handlers") or [])

    # Adjust model max_tokens for agent mode (each tool-call round needs fewer tokens).
    is_agent = "agent" in declared_handlers

    default_prompt = _build_employee_runtime_prompt(
        intent, workflow_choice, suggested_skills or [], handlers=declared_handlers
    )
    cog_raw = data.get("cognition") or {}
    if not isinstance(cog_raw, dict):
        cog_raw = {}
    agent_raw = cog_raw.get("agent") or {}
    if not isinstance(agent_raw, dict):
        agent_raw = {}
    agent_raw["system_prompt"] = _quality_gate_system_prompt(
        str(agent_raw.get("system_prompt") or ""),
        fallback=default_prompt,
        intent=intent,
        workflow_choice=workflow_choice,
        suggested_skills=suggested_skills or [],
        handlers=declared_handlers,
    )
    role_raw = agent_raw.get("role") or {}
    if not isinstance(role_raw, dict):
        role_raw = {}
    role_raw.setdefault("name", intent.name)
    role_raw.setdefault("persona", intent.scenario)
    role_raw.setdefault("tone", "professional")
    role_raw.setdefault("expertise", [intent.role, intent.industry])
    agent_raw["role"] = role_raw
    agent_raw["behavior_rules"] = _normalize_behavior_rules(
        agent_raw.get("behavior_rules"),
        label=intent.name,
        description=intent.scenario,
    )
    agent_raw.setdefault("few_shot_examples", [])
    if not agent_raw.get("model"):
        agent_raw["model"] = {
            "provider": "auto",
            "model_name": "auto",
            "temperature": 0.2,
            # Agent mode: 2048/turn (multi-turn); llm_md: 4000 (single-turn).
            "max_tokens": 2048 if is_agent else 4000,
        }
    elif is_agent:
        # Ensure per-round token budget isn't too large for tool-calling.
        existing = agent_raw["model"]
        if isinstance(existing, dict) and int(existing.get("max_tokens") or 4000) > 4096:
            existing["max_tokens"] = 2048
    cog_raw["agent"] = agent_raw

    return (
        EmployeeConfigV2(
            perception=data.get("perception") or {"type": "text"},
            memory=data.get("memory") or {"type": "session"},
            cognition=cog_raw,
            actions=actions,
        ),
        "",
    )


def _build_employee_runtime_prompt(
    intent: Intent,
    workflow_choice: Optional[WorkflowChoice],
    suggested_skills: List["SuggestedSkill"],
    *,
    handlers: Optional[List[str]] = None,
) -> str:
    is_agent = bool(handlers and "agent" in handlers)

    if is_agent:
        is_proj = _is_project_analysis_intent(intent)
        if is_proj:
            tools_line = (
                "你可以使用以下工具（通过 ReAct 循环逐步执行）：\n"
                '  scan_project_tree(path=".",max_files=200)   — 递归扫描目录，返回带文件类型统计的树\n'
                '  analyze_project_summary(path=".")           — 读取并摘要项目结构（manifests/技术栈/入口/README）\n'
                '  identify_file_types(path=".")               — 按扩展名统计文件类型分布\n'
                "  read_workspace_file(path)                    — 读取单个文件（最多 8000 字符）\n"
                "  list_workspace_dir(path)                     — 列出目录条目\n"
                "  write_workspace_file(path,content)           — 写入文件（输出文档/报告时使用）\n"
                "  run_sandboxed_python(code)                   — 在沙盒里运行纯 Python（标准库）\n"
            )
            steps_line = (
                "工作步骤（必须按顺序执行，不得跳过读取步骤直接生成结论）：\n"
                "1. 调用 analyze_project_summary 获取项目概览（技术栈、入口、配置文件）\n"
                "2. 调用 scan_project_tree 获取完整目录结构\n"
                "3. 按需用 read_workspace_file 读取 README、package.json、pyproject.toml、主配置文件等\n"
                "4. 综合真实读取到的信息分析，不允许在没有读取依据时生成任何技术描述\n"
                "5. 生成结构化输出（Markdown 文档/JSON 报告），写入工作区或直接返回\n"
                "6. 汇总：列出读取了哪些文件、得到哪些关键信息、生成了什么输出\n"
            )
        else:
            tools_line = (
                "你可以使用以下工具（通过 ReAct 循环逐步执行）：\n"
                "  read_workspace_file(path)          — 读取工作区文件\n"
                "  write_workspace_file(path,content) — 写入文件\n"
                "  list_workspace_dir(path)           — 列出目录\n"
                "  run_sandboxed_python(code)         — 在沙盒里运行纯 Python\n"
                "  http_get(url)/http_post(url,body)  — 发起 HTTP 请求\n"
            )
            steps_line = (
                "工作步骤：\n"
                "1. 识别用户意图与必要输入信息\n"
                "2. 按需调用工具（读文件/扫目录/运行代码/联网）逐步收集信息\n"
                "3. 分析收集到的真实数据，不捏造任何结果\n"
                "4. 生成结构化输出（文件/报告/代码/JSON）并写入工作区或直接返回\n"
                "5. 汇总结论：执行了哪些步骤、得到什么结果、有哪些警告\n"
            )
        wf_line = (
            f"你也绑定了工作流「{workflow_choice.workflow_name}」用于复杂编排场景；"
            "优先用工具自主完成任务，编排任务才进入工作流。"
            if workflow_choice and workflow_choice.workflow_id
            else "当前无绑定工作流；使用上方工具自主完成任务。"
        )
        return (
            f"你是{intent.name}，职责是{intent.role}，服务场景是：{intent.scenario}。\n"
            f"行业：{intent.industry}，复杂度：{intent.complexity}。\n\n"
            f"{steps_line}\n"
            f"{tools_line}\n{wf_line}\n\n"
            "禁止：捏造工具结果、访问工作区外的文件、在 answer 里声称做了实际未做的操作。\n"
            "若信息不足或工具失败，如实说明失败原因和建议的下一步。"
        )

    workflow_line = (
        f"你已绑定工作流「{workflow_choice.workflow_name}」，它是处理该员工核心任务的主路径；"
        "遇到可执行任务时优先判断是否进入该工作流，并在结果中说明关键节点结论。"
        if workflow_choice and workflow_choice.workflow_id
        else "当前未绑定专属工作流；需要执行复杂任务时先拆解步骤，并明确哪些步骤需要后续配置工作流或工具。"
    )
    skill_line = (
        "可用候选技能包括：" + "、".join(f"{s.name}（{s.brief}）" for s in suggested_skills[:6])
        if suggested_skills
        else "暂无已验证技能；不要声称已经调用外部工具或系统。"
    )
    return (
        f"你是{intent.name}，职责是{intent.role}，服务场景是：{intent.scenario}。"
        f"你的行业语境是{intent.industry}，任务复杂度为{intent.complexity}。\n"
        f"{workflow_line}\n{skill_line}\n"
        "处理请求时先识别用户目标、输入材料和缺失信息；能直接回答时给出结论，"
        "需要执行时列出执行步骤、使用的工作流或技能、关键依据和最终结果。"
        "如果信息不足、工作流失败或技能不可用，必须明确说明不确定点、失败位置和建议的下一步。"
        "不得编造订单、文件、网页、数据库、工具调用结果或不存在的系统能力。"
        "输出保持结构化：先给结论/处理结果，再给依据、步骤、风险或待补充信息。"
    )


def _quality_gate_system_prompt(
    prompt: str,
    *,
    fallback: str,
    intent: Intent,
    workflow_choice: Optional[WorkflowChoice],
    suggested_skills: List["SuggestedSkill"],
    handlers: Optional[List[str]] = None,
) -> str:
    text = _normalize_employee_system_prompt(
        prompt,
        label=intent.name,
        description=intent.scenario,
    )
    bad_markers = ("## 用途", "## 输入", "## 输出", "## 示例")
    too_short = len(text) < 120
    templated = sum(1 for marker in bad_markers if marker in text) >= 3
    if too_short or templated:
        return fallback

    is_agent = bool(handlers and "agent" in handlers)
    is_direct_python = bool(handlers and "direct_python" in handlers)
    if is_direct_python:
        # direct_python employees run pure code without LLM; a concise
        # input/output contract prompt is sufficient, no workflow/skill markers needed.
        if len(text) < 40:
            return fallback
        return text
    if is_agent:
        # Agent employees must reference tools and execution steps; the old
        # workflow/skill requirements don't apply to standalone agents.
        agent_markers = ("工作步骤", "工具", "禁止")
        if not any(m in text for m in agent_markers):
            return fallback
    else:
        # Non-agent employees must reference their workflow / skills / no-fabricate rule.
        required_markers = ("工作流", "技能", "不得编造")
        if any(marker not in text for marker in required_markers):
            return fallback
        if (
            workflow_choice
            and workflow_choice.workflow_id
            and workflow_choice.workflow_name not in text
        ):
            return fallback
        if suggested_skills and not any(s.name in text for s in suggested_skills[:3]):
            return fallback

    return text


# ── stage 4: suggest skills ───────────────────────────────────────────────────


async def stage_suggest_skills(intent: Intent, llm: LlmClient) -> Tuple[List[SuggestedSkill], str]:
    ctx = f"角色：{intent.role}\n场景：{intent.scenario}\n行业：{intent.industry}"
    content = await llm.chat(
        [{"role": "system", "content": _SYS_SUGGEST_SKILLS}, {"role": "user", "content": ctx}],
        max_tokens=2048,
    )
    data, err = _parse_json(content)
    if err:
        return [], err
    if not isinstance(data, list):
        return [], "须返回 JSON 数组"
    skills: List[SuggestedSkill] = []
    for item in data[:8]:
        if isinstance(item, dict) and item.get("name"):
            skills.append(
                SuggestedSkill(
                    name=str(item["name"])[:32],
                    brief=str(item.get("brief") or "")[:80],
                    kind=str(item.get("kind") or "")[:64],
                )
            )
    return skills, ""


# ── stage 5: suggest pricing ──────────────────────────────────────────────────


async def stage_suggest_pricing(
    intent: Intent,
    v2: EmployeeConfigV2,
    skills: List[SuggestedSkill],
    llm: LlmClient,
) -> Tuple[Optional[PricingHint], str]:
    handlers = list(v2.actions.get("handlers") or [])
    ctx = (
        f"角色：{intent.role}\n行业：{intent.industry}\n复杂度：{intent.complexity}\n"
        f"技能数：{len(skills)}\n已启用功能：{', '.join(handlers)}"
    )
    content = await llm.chat(
        [{"role": "system", "content": _SYS_SUGGEST_PRICING}, {"role": "user", "content": ctx}],
        max_tokens=1024,
    )
    data, err = _parse_json(content)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "须返回 JSON 对象"
    return (
        PricingHint(
            tier=str(data.get("tier") or "free"),
            cny=float(data.get("cny") or 0),
            period=str(data.get("period") or "month"),
            reasoning=str(data.get("reasoning") or "")[:120],
        ),
        "",
    )


# ── stage 6: assemble manifest ────────────────────────────────────────────────


def stage_assemble(
    intent: Intent,
    workflow_choice: Optional[WorkflowChoice],
    v2: EmployeeConfigV2,
    skills: List[SuggestedSkill],
    pricing: Optional[PricingHint],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    from modman.manifest_util import validate_manifest_dict
    from modstore_server.xcagi_host_profile import (
        merge_workflow_employee_for_manifest,
        normalize_xcagi_host_profile,
    )

    eid = intent.id
    hp_norm, _ = normalize_xcagi_host_profile({"panel_kind": "mod_http"})
    wf_row = merge_workflow_employee_for_manifest(
        employee_id=eid,
        label=intent.name,
        panel_summary=intent.scenario,
        host_profile=hp_norm,
    )
    if workflow_choice and workflow_choice.workflow_id:
        wf_row["workflow_id"] = workflow_choice.workflow_id

    metadata: Dict[str, Any] = {
        "framework_version": "2.0.0",
        "created_by": "employee_ai_pipeline",
    }
    if skills:
        metadata["suggested_skills"] = [asdict(s) for s in skills]
    if pricing:
        metadata["suggested_pricing"] = asdict(pricing)
    # Flag if the chosen workflow hasn't passed sandbox testing yet.
    # The frontend shows a warning so the user can run sandbox before publishing.
    if workflow_choice and workflow_choice.workflow_id and not workflow_choice.sandbox_passed:
        metadata["workflow_needs_sandbox"] = True

    v2_dict = asdict(v2)
    v2_dict.setdefault(
        "identity",
        {
            "id": intent.id,
            "version": "1.0.0",
            "artifact": "employee_pack",
            "name": intent.name,
            "description": intent.scenario,
        },
    )
    cognition = v2_dict.get("cognition") if isinstance(v2_dict.get("cognition"), dict) else {}
    caps = _default_capabilities(
        pid=intent.id,
        name=intent.name,
        description=intent.scenario,
        employee_id=eid,
        label=intent.name,
        capabilities=[s.name for s in skills],
    )

    if skills:
        cognition["skills"] = [asdict(s) for s in skills]
    else:
        cognition["skills"] = _default_skill_entries(
            caps, label=intent.name, description=intent.scenario
        )
    v2_dict["cognition"] = cognition
    collab = v2_dict.get("collaboration") if isinstance(v2_dict.get("collaboration"), dict) else {}
    workflow = collab.get("workflow") if isinstance(collab.get("workflow"), dict) else {}
    workflow["workflow_id"] = (
        workflow_choice.workflow_id if workflow_choice and workflow_choice.workflow_id else 0
    )
    workflow["name"] = (
        workflow_choice.workflow_name
        if workflow_choice and workflow_choice.workflow_name
        else f"{intent.name}工作流"
    )
    collab["workflow"] = workflow
    v2_dict["collaboration"] = collab
    v2_dict["metadata"] = metadata

    # Propagate project-analysis workspace config into the assembled actions so
    # the executor can detect it even without re-running the pipeline.
    if _is_project_analysis_intent(intent):
        actions_in_v2 = v2_dict.get("actions")
        if isinstance(actions_in_v2, dict):
            if "agent" not in (actions_in_v2.get("handlers") or []):
                actions_in_v2["handlers"] = ["agent"]
            if not isinstance(actions_in_v2.get("agent"), dict):
                actions_in_v2["agent"] = {}
            actions_in_v2["agent"].setdefault(
                "workspace",
                {
                    "mode": "user_project",
                    "requires_project_root": True,
                    "read_only": True,
                },
            )
        v2_dict["actions"] = actions_in_v2

    manifest: Dict[str, Any] = {
        "id": intent.id,
        "name": intent.name,
        "version": "1.0.0",
        "author": "",
        "description": intent.scenario,
        "artifact": "employee_pack",
        "scope": "global",
        "industry": intent.industry,
        "dependencies": {"xcagi": ">=1.0.0"},
        "employee": {
            "id": eid,
            "label": intent.name,
            "capabilities": caps,
        },
        "employee_config_v2": v2_dict,
        "xcagi_host_profile": hp_norm or {"panel_kind": "mod_http"},
        "workflow_employees": [wf_row],
        "backend": {"entry": "blueprints", "init": "mod_init"},
    }

    # Write pricing into the top-level commerce block so catalog upload forms
    # can read it directly via manifest.commerce.price without extra fallback logic.
    if pricing and (pricing.cny > 0 or pricing.tier != "free"):
        manifest["commerce"] = {
            "price": pricing.cny,
            "currency": "CNY",
            "tier": pricing.tier,
            "period": pricing.period,
        }

    errs = validate_manifest_dict(manifest)
    return manifest, errs


# ── stage 7: generate runtime code ────────────────────────────────────────────


def _build_vibe_coding_prompt(runtime_kind: str, rule_spec: Dict[str, Any]) -> str:
    """Build a domain-specific system prompt for vibe coding convert.py.

    Includes a few-shot example from the built-in runtime so the LLM can
    learn the expected code structure, naming conventions, and output schema.
    """
    from modstore_server.csv_tabular_runtime import render_csv_read_convert_module
    from modstore_server.excel_tabular_runtime import render_excel_read_convert_module
    from modstore_server.pdf_extract_runtime import render_pdf_read_convert_module
    from modstore_server.ppt_extract_runtime import render_ppt_read_convert_module
    from modstore_server.txt_extract_runtime import render_txt_read_convert_module
    from modstore_server.word_extract_runtime import render_word_fallback_convert_module

    _FEW_SHOT_MAP = {
        "word_full_extract": render_word_fallback_convert_module,
        "excel_full_read": render_excel_read_convert_module,
        "csv_full_read": render_csv_read_convert_module,
        "pdf_full_read": render_pdf_read_convert_module,
        "ppt_full_read": render_ppt_read_convert_module,
        "txt_full_read": render_txt_read_convert_module,
    }

    few_shot_code = ""
    if runtime_kind in _FEW_SHOT_MAP:
        few_shot_code = _FEW_SHOT_MAP[runtime_kind]()
    if len(few_shot_code) > 8000:
        few_shot_code = few_shot_code[:8000] + "\n# ... (truncated for brevity)\n"

    output_schema = rule_spec.get("output_schema") or []
    schema_str = (
        json.dumps(output_schema, ensure_ascii=False) if output_schema else "(see rule_spec)"
    )

    prompt = (
        "你是工作台 vibecoding 的 Python 实现器。你的任务是生成 convert.py —— "
        "一个完整的、可直接运行的 Python 文件，用于处理特定文件格式。\n\n"
        "## 核心要求\n\n"
        "1. 必须定义 `convert_file(src_path: Path, output_path: Path, *, "
        "template_path: Optional[Path], payload: Dict[str, Any], "
        "ctx: Dict[str, Any], rule_spec: Dict[str, Any]) -> Dict[str, Any]` 函数\n"
        "2. 必须真实读取输入文件、按规则写出 output_path，不能写伪结果或占位符\n"
        "3. 输出 JSON 必须包含以下顶层字段: " + schema_str + "\n"
        "4. 同时输出纯文本文件 (document_full.txt)\n\n"
        "## 安全约束\n\n"
        "- 禁止使用: eval/exec/compile/__import__/subprocess/os.system/ctypes/multiprocessing\n"
        "- 允许使用: pathlib, json, datetime, re, typing, io, copy, collections, "
        "zipfile, xml.etree.ElementTree, openpyxl, pandas\n"
        "- 对于 .docx 文件，必须用 zipfile + ElementTree 直接解析 OOXML，不要依赖 python-docx\n\n"
        "## 输出格式\n\n"
        "只输出一个完整的 Python 文件（不要 Markdown 围栏、不要解释、不要注释说明这是生成的代码）\n\n"
    )

    if few_shot_code:
        prompt += (
            "## 参考实现 (few-shot example)\n\n"
            "以下是一个类似任务的参考实现，你可以学习其代码结构、命名规范和解析策略，"
            "但需要根据当前 brief 和 rule_spec 生成你自己的实现：\n\n"
            "```python\n" + few_shot_code + "\n```\n\n"
        )

    prompt += (
        "## 当前任务\n\n"
        f"runtime_kind: {runtime_kind}\n"
        "请根据下方 user message 中的 brief 和 rule_spec 生成 convert.py。"
    )

    return prompt


@dataclass
class GeneratedCode:
    employee_py: str = ""
    vendor_modules: Dict[str, str] = field(default_factory=dict)
    rule_spec: Dict[str, Any] = field(default_factory=dict)
    asset_manifest: Dict[str, Any] = field(default_factory=dict)
    runtime_kind: str = ""
    code_source: str = ""
    warnings: List[str] = field(default_factory=list)


async def stage_generate_code(
    brief: str,
    manifest: Dict[str, Any],
    llm: LlmClient,
) -> GeneratedCode:
    """S7: Generate runtime implementation code for the employee pack.

    For direct_python employees:
      - Known file formats (Word/Excel/CSV/PDF/PPT/TXT) use built-in runtime modules
      - Unknown formats use LLM to generate convert.py (vibe coding)

    For agent employees:
      - Use LLM to generate the employee run() implementation
    """
    from modstore_server.employee_asset_pipeline import (
        _infer_asset_runtime_kind,
        _runtime_package_name,
        build_rule_spec,
        is_csv_full_read,
        is_csv_generate,
        is_excel_full_read,
        is_excel_generate,
        is_pdf_full_read,
        is_pdf_generate,
        is_ppt_full_read,
        is_ppt_generate,
        is_txt_full_read,
        is_txt_generate,
        is_word_full_extract,
        is_word_generate,
        render_direct_python_asset_worker,
        render_runtime_modules,
    )
    from modstore_server.mod_employee_impl_scaffold import (
        SYSTEM_PROMPT_EMPLOYEE_IMPL,
        _behavior_check,
        _compile_check,
        _security_check,
        _strip_code_fence,
        sanitize_employee_stem,
    )
    from modstore_server.script_agent.llm_output_sanitize import finalize_extracted_python

    result = GeneratedCode()
    handlers = list(manifest.get("employee_config_v2", {}).get("actions", {}).get("handlers", []))
    pack_id = manifest.get("id", "unknown")
    employee_id = pack_id
    emp = manifest.get("employee", {}) or {}
    label = emp.get("label") or manifest.get("name") or employee_id
    stem = sanitize_employee_stem(employee_id)
    runtime_mod = _runtime_package_name(pack_id, employee_id)

    # Auto-correct handler: if brief matches a known file-format pipeline,
    # override "agent" → "direct_python" because the asset pipeline has
    # built-in runtime modules for these formats.
    if "direct_python" not in handlers:
        _dp_triggers = (
            is_word_full_extract,
            is_word_generate,
            is_excel_full_read,
            is_excel_generate,
            is_csv_full_read,
            is_csv_generate,
            is_txt_full_read,
            is_txt_generate,
            is_pdf_full_read,
            is_pdf_generate,
            is_ppt_full_read,
            is_ppt_generate,
        )
        if any(fn(brief) for fn in _dp_triggers):
            handlers = ["direct_python"]
            v2 = manifest.get("employee_config_v2", {})
            actions = v2.get("actions", {}) if isinstance(v2.get("actions"), dict) else {}
            actions["handlers"] = handlers
            actions.pop("agent", None)
            actions["direct_python"] = {
                "module": stem,
                "action": "convert",
            }
            result.warnings.append(
                "S4 选择了 agent handler，但 brief 匹配已知文件格式管线，已自动修正为 direct_python"
            )

    asset_manifest: Dict[str, Any] = {
        "session_id": "pipeline",
        "user_id": 0,
        "root": "",
        "assets": [],
        "templates": [],
        "example_inputs": [],
        "expected_outputs": [],
        "rules": [],
    }
    result.asset_manifest = asset_manifest

    if "direct_python" in handlers:
        # Use format-specific rule_spec builders when the brief clearly
        # indicates a known format, bypassing build_rule_spec's ambiguous
        # keyword matching (e.g. "表格数据" in a Word brief triggers CSV).
        from modstore_server.csv_tabular_runtime import (
            build_csv_generate_rule_spec,
            build_csv_read_rule_spec,
        )
        from modstore_server.excel_tabular_runtime import (
            build_excel_generate_rule_spec,
            build_excel_read_rule_spec,
        )
        from modstore_server.pdf_extract_runtime import (
            build_pdf_generate_rule_spec,
            build_pdf_read_rule_spec,
        )
        from modstore_server.ppt_extract_runtime import (
            build_ppt_generate_rule_spec,
            build_ppt_read_rule_spec,
        )
        from modstore_server.txt_extract_runtime import (
            build_txt_generate_rule_spec,
            build_txt_read_rule_spec,
        )
        from modstore_server.word_extract_runtime import build_word_extract_rule_spec
        from modstore_server.word_generate_runtime import build_word_generate_rule_spec

        _brief_lower = (brief or "").lower()
        _has_word_signal = any(k in _brief_lower for k in ("word", "docx", ".doc", "文档"))
        _has_excel_signal = any(k in _brief_lower for k in ("excel", "xlsx", ".xls", "电子表格"))
        _has_pdf_signal = any(k in _brief_lower for k in ("pdf", ".pdf"))
        _has_ppt_signal = any(k in _brief_lower for k in ("ppt", "pptx", "演示"))
        _has_txt_signal = any(k in _brief_lower for k in ("txt", ".txt", "纯文本"))
        _has_csv_signal = any(k in _brief_lower for k in ("csv", ".csv", "逗号分隔"))
        _has_read_signal = any(
            k in _brief_lower for k in ("读取", "提取", "解析", "read", "extract", "全量")
        )
        _has_write_signal = any(
            k in _brief_lower for k in ("生成", "写入", "write", "generate", "重建", "render")
        )

        if _has_word_signal:
            if _has_write_signal and not _has_read_signal:
                rule_spec = build_word_generate_rule_spec(brief)
            else:
                rule_spec = build_word_extract_rule_spec(brief)
        elif _has_pdf_signal:
            if _has_write_signal and not _has_read_signal:
                rule_spec = build_pdf_generate_rule_spec(brief)
            else:
                rule_spec = build_pdf_read_rule_spec(brief)
        elif _has_excel_signal:
            if _has_write_signal and not _has_read_signal:
                rule_spec = build_excel_generate_rule_spec(brief)
            else:
                rule_spec = build_excel_read_rule_spec(brief)
        elif _has_ppt_signal:
            if _has_write_signal and not _has_read_signal:
                rule_spec = build_ppt_generate_rule_spec(brief)
            else:
                rule_spec = build_ppt_read_rule_spec(brief)
        elif _has_txt_signal:
            if _has_write_signal and not _has_read_signal:
                rule_spec = build_txt_generate_rule_spec(brief)
            else:
                rule_spec = build_txt_read_rule_spec(brief)
        elif _has_csv_signal:
            if _has_write_signal and not _has_read_signal:
                rule_spec = build_csv_generate_rule_spec(brief)
            else:
                rule_spec = build_csv_read_rule_spec(brief)
        elif is_word_full_extract(brief):
            rule_spec = build_word_extract_rule_spec(brief)
        elif is_word_generate(brief):
            rule_spec = build_word_generate_rule_spec(brief)
        elif is_pdf_full_read(brief):
            rule_spec = build_pdf_read_rule_spec(brief)
        elif is_pdf_generate(brief):
            rule_spec = build_pdf_generate_rule_spec(brief)
        elif is_excel_full_read(brief):
            rule_spec = build_excel_read_rule_spec(brief)
        elif is_excel_generate(brief):
            rule_spec = build_excel_generate_rule_spec(brief)
        elif is_ppt_full_read(brief):
            rule_spec = build_ppt_read_rule_spec(brief)
        elif is_ppt_generate(brief):
            rule_spec = build_ppt_generate_rule_spec(brief)
        elif is_txt_full_read(brief):
            rule_spec = build_txt_read_rule_spec(brief)
        elif is_txt_generate(brief):
            rule_spec = build_txt_generate_rule_spec(brief)
        elif is_csv_full_read(brief):
            rule_spec = build_csv_read_rule_spec(brief)
        elif is_csv_generate(brief):
            rule_spec = build_csv_generate_rule_spec(brief)
        else:
            rule_spec = build_rule_spec(brief, asset_manifest)
        result.rule_spec = rule_spec
        runtime_kind = rule_spec.get("runtime_kind", "")
        result.runtime_kind = runtime_kind

        result.employee_py = render_direct_python_asset_worker(
            employee_id=employee_id,
            label=label,
            runtime_module=runtime_mod,
            rule_spec=rule_spec,
        )

        # ── LLM vibe coding: primary path ────────────────────────────────
        # Always ask the LLM to generate convert.py.  Only fall back to the
        # built-in template when LLM output fails compile / security checks.
        result.code_source = "asset_pipeline_llm"
        try:
            from modstore_server.llm_chat_proxy import chat_dispatch
            from modstore_server.llm_key_resolver import platform_api_key, platform_base_url

            prov = "xiaomi"
            api_key = platform_api_key(prov)
            base_url = platform_base_url(prov)
            if api_key:
                system = _build_vibe_coding_prompt(runtime_kind, rule_spec)
                user_msg = json.dumps(
                    {"brief": brief, "rule_spec": rule_spec},
                    ensure_ascii=False,
                )[:12000]
                res = await chat_dispatch(
                    prov,
                    api_key=api_key,
                    base_url=base_url,
                    model="mimo-v2.5-pro",
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=16000,
                )
                if res.get("ok"):
                    code = _strip_code_fence(str(res.get("content") or ""))
                    code = finalize_extracted_python(code)[0]
                    compile_err = _compile_check(code)
                    if compile_err:
                        repair_res = await chat_dispatch(
                            prov,
                            api_key=api_key,
                            base_url=base_url,
                            model="mimo-v2.5-pro",
                            messages=[
                                {
                                    "role": "system",
                                    "content": "你是 Python 语法修复器。只输出修复后的完整 Python 文件（UTF-8，不要 Markdown 围栏、不要解释）。保留原有函数签名与业务逻辑，仅修正语法与引号/缩进问题。",
                                },
                                {
                                    "role": "user",
                                    "content": f"py_compile 报错：\n{compile_err}\n\n原始代码：\n{code[:12000]}",
                                },
                            ],
                            max_tokens=16000,
                            forbid_reasoning_fallback=True,
                        )
                        if repair_res.get("ok"):
                            code = _strip_code_fence(str(repair_res.get("content") or ""))
                            code = finalize_extracted_python(code)[0]
                    if _compile_check(code) is None:
                        sec_err = _security_check(code)
                        if sec_err:
                            result.warnings.append(f"安全校验: {sec_err}")
                        else:
                            result.vendor_modules = {
                                "__init__.py": '"""Generated runtime modules."""\n',
                                "convert.py": code,
                                "parser.py": '"""Parser extension point."""\n',
                                "mapper.py": '"""Mapper extension point."""\n',
                                "rules.py": '"""Rules extension point."""\n',
                                "paths.py": '"""Path helpers."""\n',
                                "mapping.py": '"""Mapping helpers."""\n',
                                "header_resolver.py": '"""Header resolver."""\n',
                            }
                            result.code_source = "vibe_coding_validated"
                    else:
                        result.warnings.append("LLM 生成的 convert.py 编译失败，降级到内置模板")
                else:
                    result.warnings.append(
                        f"LLM 调用失败: {res.get('error', '')[:100]}，降级到内置模板"
                    )
            else:
                result.warnings.append("无可用 LLM API Key，降级到内置模板")
        except Exception as e:
            import traceback

            result.warnings.append(f"LLM 代码生成异常: {type(e).__name__}: {e}，降级到内置模板")
            result.warnings.append(traceback.format_exc()[-500:])

        # ── fallback: built-in template ───────────────────────────────────
        if result.code_source != "vibe_coding_validated":
            runtime_modules = render_runtime_modules(rule_spec)
            result.vendor_modules = runtime_modules
            result.code_source = "asset_pipeline_builtin_fallback"

    elif "agent" in handlers:
        result.code_source = "agent_llm_impl"
        try:
            from modstore_server.llm_chat_proxy import chat_dispatch
            from modstore_server.llm_key_resolver import platform_api_key, platform_base_url

            prov = "xiaomi"
            api_key = platform_api_key(prov)
            base_url = platform_base_url(prov)
            if api_key:
                emp_brief = (
                    f"员工 id: {employee_id}\n"
                    f"员工显示名: {label}\n"
                    f"职责摘要: {manifest.get('description', '')[:400]}\n"
                    f"能力: {', '.join(emp.get('capabilities', []))}\n\n"
                    f"请你基于以上画像实现 async def run(payload, ctx)。"
                )
                res = await chat_dispatch(
                    prov,
                    api_key=api_key,
                    base_url=base_url,
                    model="mimo-v2.5-pro",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT_EMPLOYEE_IMPL},
                        {"role": "user", "content": emp_brief},
                    ],
                    max_tokens=6000,
                    forbid_reasoning_fallback=True,
                )
                if res.get("ok"):
                    code = _strip_code_fence(str(res.get("content") or ""))
                    code = finalize_extracted_python(code)[0]
                    compile_err = _compile_check(code)
                    if compile_err:
                        repair_res = await chat_dispatch(
                            prov,
                            api_key=api_key,
                            base_url=base_url,
                            model="mimo-v2.5-pro",
                            messages=[
                                {
                                    "role": "system",
                                    "content": "你是 Python 语法修复器。只输出修复后的完整 Python 文件（UTF-8，不要 Markdown 围栏、不要解释）。保留原有 async def run(payload, ctx) 签名与业务逻辑，仅修正语法与引号/缩进问题。",
                                },
                                {
                                    "role": "user",
                                    "content": f"py_compile 报错：\n{compile_err}\n\n原始代码：\n{code[:8000]}",
                                },
                            ],
                            max_tokens=6000,
                            forbid_reasoning_fallback=True,
                        )
                        if repair_res.get("ok"):
                            code = _strip_code_fence(str(repair_res.get("content") or ""))
                            code = finalize_extracted_python(code)[0]
                    if _compile_check(code) is None:
                        sec_err = _security_check(code)
                        beh_err = _behavior_check(code)
                        if sec_err:
                            result.warnings.append(f"安全校验: {sec_err}")
                        if beh_err:
                            result.warnings.append(f"行为校验: {beh_err}")
                        if not sec_err and not beh_err:
                            result.employee_py = code
                            result.code_source = "agent_llm_impl_validated"
                        else:
                            result.warnings.append(
                                "LLM 生成的 agent 实现未通过安全/行为校验，使用兜底实现"
                            )
                    else:
                        result.warnings.append("LLM 生成的 agent 实现编译失败，使用兜底实现")
        except Exception as e:
            result.warnings.append(f"Agent 代码生成降级: {e}")

        if not result.employee_py:
            from modstore_server.mod_employee_impl_scaffold import _fallback_employee_py

            result.employee_py = _fallback_employee_py(
                employee_id, label, manifest.get("description", "")
            )
            result.code_source = "agent_fallback"

    return result


# ── refine prompt helper ──────────────────────────────────────────────────────


async def refine_system_prompt(
    current_prompt: str,
    instruction: str,
    role_context: str,
    llm: LlmClient,
) -> Tuple[Optional[Dict[str, str]], str]:
    """LLM-improve a system prompt and explain the changes."""
    ctx = (
        f"角色背景：{role_context}\n\n"
        f"当前 system prompt：\n{current_prompt}\n\n"
        f"优化指令：{instruction}"
    )
    content = await llm.chat(
        [{"role": "system", "content": _SYS_REFINE_PROMPT}, {"role": "user", "content": ctx}],
        max_tokens=2048,
    )
    data, err = _parse_json(content)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "须返回 JSON 对象"
    improved = str(data.get("improved_prompt") or "").strip()
    if not improved:
        return None, "LLM 未返回优化后的 prompt"
    return {
        "improved_prompt": improved,
        "diff_explanation": str(data.get("diff_explanation") or "")[:160],
    }, ""


# ── orchestrator ──────────────────────────────────────────────────────────────


async def run_pipeline(
    brief: str,
    *,
    llm: LlmClient,
    on_event: Callable[[Dict[str, Any]], Awaitable[None]],
    eligible_workflows: Optional[List[Dict[str, Any]]] = None,
    generate_workflow_fallback: Optional[Callable[[], Awaitable[Dict[str, Any]]]] = None,
) -> Optional[Dict[str, Any]]:
    """Run the 6-stage pipeline pushing SSE events via on_event.

    Returns the assembled manifest dict on success, None on fatal failure.
    Stages 4 (skills) and 5 (pricing) are non-fatal: errors produce empty/null
    results but do not abort the pipeline.
    """

    async def _emit(event: str, stage: str, **kw: Any) -> None:
        await on_event({"event": event, "stage": stage, **kw})

    # ── S1 parse intent ───────────────────────────────────────────────────────
    await _emit("stage_start", "parse_intent")
    intent, err = await stage_parse_intent(brief, llm)
    if err or intent is None:
        await _emit("stage_error", "parse_intent", error=err or "意图解析失败", retryable=True)
        return None
    await _emit("stage_done", "parse_intent", data=asdict(intent))

    # ── S2 resolve workflow ───────────────────────────────────────────────────
    await _emit("stage_start", "resolve_workflow")

    async def _on_wf_progress(msg: str) -> None:
        await _emit("stage_progress", "resolve_workflow", message=msg)

    wf_choice, err = await stage_resolve_workflow(
        intent,
        eligible_workflows or [],
        llm,
        generate_fallback=generate_workflow_fallback,
        on_progress=_on_wf_progress,
    )
    if err:
        await _emit("stage_error", "resolve_workflow", error=err, retryable=True)
        return None
    await _emit("stage_done", "resolve_workflow", data=asdict(wf_choice) if wf_choice else None)

    # ── S3 suggest skills (non-fatal, feeds system_prompt design) ─────────────
    await _emit("stage_start", "suggest_skills")
    skills, err = await stage_suggest_skills(intent, llm)
    if err:
        await _emit("stage_error", "suggest_skills", error=err, retryable=False)
        skills = []
    await _emit("stage_done", "suggest_skills", data=[asdict(s) for s in skills])

    # ── S4 design config v2 ───────────────────────────────────────────────────
    await _emit("stage_start", "design_v2")
    v2, err = await stage_design_v2(intent, wf_choice, llm, suggested_skills=skills)
    if err or v2 is None:
        await _emit("stage_error", "design_v2", error=err or "配置设计失败", retryable=True)
        return None
    await _emit("stage_done", "design_v2", data=asdict(v2))

    # ── S5 suggest pricing (non-fatal) ────────────────────────────────────────
    await _emit("stage_start", "suggest_pricing")
    pricing, err = await stage_suggest_pricing(intent, v2, skills, llm)
    if err:
        await _emit("stage_error", "suggest_pricing", error=err, retryable=False)
        pricing = None
    await _emit("stage_done", "suggest_pricing", data=asdict(pricing) if pricing else None)

    # ── S6 assemble manifest ──────────────────────────────────────────────────
    await _emit("stage_start", "assemble")
    manifest, errs = stage_assemble(intent, wf_choice, v2, skills, pricing)
    if manifest is None:
        await _emit(
            "stage_error",
            "assemble",
            error="; ".join(errs) if errs else "装配失败",
            retryable=False,
        )
        return None
    if errs:
        await _emit("stage_done", "assemble", data=manifest, warnings=errs)
    else:
        await _emit("stage_done", "assemble", data=manifest)

    # ── S7 generate runtime code ────────────────────────────────────────────
    await _emit("stage_start", "generate_code")
    generated = await stage_generate_code(brief, manifest, llm)
    if generated.warnings:
        await _emit(
            "stage_done",
            "generate_code",
            data={
                "code_source": generated.code_source,
                "runtime_kind": generated.runtime_kind,
                "vendor_module_count": len(generated.vendor_modules),
                "employee_py_lines": len(generated.employee_py.splitlines()),
            },
            warnings=generated.warnings,
        )
    else:
        await _emit(
            "stage_done",
            "generate_code",
            data={
                "code_source": generated.code_source,
                "runtime_kind": generated.runtime_kind,
                "vendor_module_count": len(generated.vendor_modules),
                "employee_py_lines": len(generated.employee_py.splitlines()),
            },
        )

    await _emit("pipeline_done", "pipeline", manifest=manifest, generated_code=asdict(generated))
    return manifest
