# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_pipeline")


@_facade().dataclass
class Intent:
    id: str
    name: str
    role: str
    scenario: str
    industry: str
    complexity: str


@_facade().dataclass
class WorkflowChoice:
    workflow_id: _facade().Optional[int]
    workflow_name: str
    match_score: float
    generated: bool
    sandbox_passed: bool = False


@_facade().dataclass
class EmployeeConfigV2:
    perception: _facade().Dict[str, _facade().Any]
    memory: _facade().Dict[str, _facade().Any]
    cognition: _facade().Dict[str, _facade().Any]
    actions: _facade().Dict[str, _facade().Any]


@_facade().dataclass
class SuggestedSkill:
    name: str
    brief: str
    unverified: bool = True
    kind: str = ""


def _is_project_analysis_intent(intent: Intent) -> bool:
    """Return True when the intent describes a project-analysis / doc-gen employee."""
    text = f"{intent.role} {intent.scenario}".lower()
    return any((kw in text for kw in _facade()._PROJECT_ANALYSIS_KEYWORDS))


@_facade().dataclass
class PricingHint:
    tier: str
    cny: float
    period: str
    reasoning: str


def _parse_json(text: str) -> _facade().Tuple[_facade().Optional[_facade().Any], str]:
    raw = _facade()._strip_json_fence(text)
    try:
        return (_facade().json.loads(raw), "")
    except _facade().json.JSONDecodeError as e:
        return (None, f"JSON 解析失败: {e}")


async def stage_parse_intent(
    brief: str, llm: _facade().LlmClient
) -> _facade().Tuple[_facade().Optional[Intent], str]:
    content = await llm.chat(
        [
            {"role": "system", "content": _facade()._SYS_PARSE_INTENT},
            {"role": "user", "content": brief},
        ],
        max_tokens=2048,
    )
    (data, err) = _facade()._parse_json(content)
    if err:
        return (None, err)
    if not isinstance(data, dict):
        return (None, "LLM 须返回 JSON 对象")
    raw_id = (
        _facade().re.sub("[^a-z0-9\\-_]", "-", str(data.get("id") or "").lower().strip()).strip("-")
    )
    safe_id = raw_id[:32] or "my-employee"
    return (
        _facade().Intent(
            id=safe_id,
            name=str(data.get("name") or safe_id)[:24],
            role=str(data.get("role") or "")[:40],
            scenario=str(data.get("scenario") or "")[:120],
            industry=str(data.get("industry") or "通用")[:20],
            complexity=str(data.get("complexity") or "medium").lower(),
        ),
        "",
    )


async def stage_resolve_workflow(
    intent: Intent,
    eligible_workflows: _facade().List[_facade().Dict[str, _facade().Any]],
    llm: _facade().LlmClient,
    *,
    generate_fallback: _facade().Optional[
        _facade().Callable[[], _facade().Awaitable[_facade().Dict[str, _facade().Any]]]
    ] = None,
    score_threshold: float = 0.55,
    on_progress: _facade().Optional[_facade().Callable[[str], _facade().Awaitable[None]]] = None,
) -> _facade().Tuple[_facade().Optional[WorkflowChoice], str]:
    """LLM-rank eligible workflows; fall back to generation if score is below threshold."""
    if not eligible_workflows:
        if generate_fallback is None:
            return (
                _facade().WorkflowChoice(
                    workflow_id=None, workflow_name="", match_score=0.0, generated=False
                ),
                "",
            )
        if on_progress:
            await on_progress("未找到已通过沙箱的工作流，正在为您生成新工作流…")
        res = await generate_fallback()
        if not res.get("ok"):
            return (None, f"工作流兜底生成失败: {res.get('error') or '未知错误'}")
        return (
            _facade().WorkflowChoice(
                workflow_id=int(res["workflow_id"]),
                workflow_name=str(res.get("name") or ""),
                match_score=0.0,
                generated=True,
            ),
            "",
        )
    cands = [
        {"index": i, "name": w.get("name", ""), "description": str(w.get("description", ""))[:120]}
        for (i, w) in enumerate(eligible_workflows)
    ]
    msg = f"员工意图：{intent.role}（{intent.scenario}）\n候选工作流：{_facade().json.dumps(cands, ensure_ascii=False)}"
    content = await llm.chat(
        [
            {"role": "system", "content": _facade()._SYS_RANK_WORKFLOW},
            {"role": "user", "content": msg},
        ],
        max_tokens=1024,
    )
    (data, err) = _facade()._parse_json(content)
    if err:
        return (None, err)
    best_idx = int(data.get("best_index", -1))
    score = float(data.get("score", 0.0))
    if 0 <= best_idx < len(eligible_workflows) and score >= score_threshold:
        wf = eligible_workflows[best_idx]
        return (
            _facade().WorkflowChoice(
                workflow_id=int(wf["id"]),
                workflow_name=str(wf.get("name", "")),
                match_score=score,
                generated=False,
                sandbox_passed=bool(wf.get("sandbox_passed", False)),
            ),
            "",
        )
    if generate_fallback is None:
        return (
            _facade().WorkflowChoice(
                workflow_id=None, workflow_name="", match_score=score, generated=False
            ),
            "",
        )
    if on_progress:
        await on_progress(f"现有工作流匹配度（{score:.0%}）不足，正在生成专属工作流…")
    res = await generate_fallback()
    if not res.get("ok"):
        return (None, f"工作流兜底生成失败: {res.get('error') or '未知错误'}")
    return (
        _facade().WorkflowChoice(
            workflow_id=int(res["workflow_id"]),
            workflow_name=str(res.get("name") or ""),
            match_score=0.0,
            generated=True,
        ),
        "",
    )


async def stage_design_v2(
    intent: Intent,
    workflow_choice: _facade().Optional[WorkflowChoice],
    llm: _facade().LlmClient,
    *,
    suggested_skills: _facade().Optional[_facade().List["SuggestedSkill"]] = None,
) -> _facade().Tuple[_facade().Optional[EmployeeConfigV2], str]:
    ctx_parts = [
        f"角色：{intent.role}",
        f"场景：{intent.scenario}",
        f"行业：{intent.industry}",
        f"复杂度：{intent.complexity}",
    ]
    if workflow_choice and workflow_choice.workflow_id:
        ctx_parts.append(f"已绑定工作流：{workflow_choice.workflow_name}")
        ctx_parts.append(
            "工作流使用要求：system_prompt 中必须说明该工作流是员工的执行主路径，回答前要判断是否需要进入工作流，失败时说明失败节点和下一步。"
        )
    if suggested_skills:
        ctx_parts.append(
            "候选技能："
            + _facade().json.dumps(
                [_facade().asdict(s) for s in suggested_skills[:6]], ensure_ascii=False
            )
        )
    content = await llm.chat(
        [
            {"role": "system", "content": _facade()._SYS_DESIGN_V2},
            {"role": "user", "content": "\n".join(ctx_parts)},
        ],
        max_tokens=4096,
    )
    (data, err) = _facade()._parse_json(content)
    if err:
        return (None, err)
    if not isinstance(data, dict):
        return (None, "LLM 须返回 JSON 对象")
    actions = data.get("actions") or {"handlers": ["llm_md"]}
    if not isinstance(actions, dict):
        actions = {"handlers": ["llm_md"]}
    raw_handlers = actions.get("handlers")
    if not isinstance(raw_handlers, list) or not raw_handlers:
        actions["handlers"] = ["llm_md", "echo"]
    elif (
        "echo" in raw_handlers
        and "llm_md" not in raw_handlers
        and ("agent" not in raw_handlers)
        and ("direct_python" not in raw_handlers)
    ):
        actions["handlers"] = ["llm_md" if h == "echo" else h for h in raw_handlers]
    if (
        "llm_md" in actions.get("handlers", [])
        and "echo" not in actions.get("handlers", [])
        and ("direct_python" not in actions.get("handlers", []))
    ):
        actions["handlers"] = list(actions.get("handlers") or []) + ["echo"]
    if _facade()._is_project_analysis_intent(intent) and "agent" not in actions.get("handlers", []):
        actions["handlers"] = ["agent"]
        if not isinstance(actions.get("agent"), dict):
            actions["agent"] = {}
        actions["agent"].setdefault(
            "workspace", {"mode": "user_project", "requires_project_root": True, "read_only": True}
        )
    declared_handlers = list(actions.get("handlers") or [])
    is_agent = "agent" in declared_handlers
    default_prompt = _facade()._build_employee_runtime_prompt(
        intent, workflow_choice, suggested_skills or [], handlers=declared_handlers
    )
    cog_raw = data.get("cognition") or {}
    if not isinstance(cog_raw, dict):
        cog_raw = {}
    agent_raw = cog_raw.get("agent") or {}
    if not isinstance(agent_raw, dict):
        agent_raw = {}
    agent_raw["system_prompt"] = _facade()._quality_gate_system_prompt(
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
    agent_raw["behavior_rules"] = _facade()._normalize_behavior_rules(
        agent_raw.get("behavior_rules"), label=intent.name, description=intent.scenario
    )
    agent_raw.setdefault("few_shot_examples", [])
    if not agent_raw.get("model"):
        agent_raw["model"] = {
            "provider": "auto",
            "model_name": "auto",
            "temperature": 0.2,
            "max_tokens": 2048 if is_agent else 4000,
        }
    elif is_agent:
        existing = agent_raw["model"]
        if isinstance(existing, dict) and int(existing.get("max_tokens") or 4000) > 4096:
            existing["max_tokens"] = 2048
    cog_raw["agent"] = agent_raw
    return (
        _facade().EmployeeConfigV2(
            perception=data.get("perception") or {"type": "text"},
            memory=data.get("memory") or {"type": "session"},
            cognition=cog_raw,
            actions=actions,
        ),
        "",
    )


def _build_employee_runtime_prompt(
    intent: Intent,
    workflow_choice: _facade().Optional[WorkflowChoice],
    suggested_skills: _facade().List["SuggestedSkill"],
    *,
    handlers: _facade().Optional[_facade().List[str]] = None,
) -> str:
    is_agent = bool(handlers and "agent" in handlers)
    if is_agent:
        is_proj = _facade()._is_project_analysis_intent(intent)
        if is_proj:
            tools_line = '你可以使用以下工具（通过 ReAct 循环逐步执行）：\n  scan_project_tree(path=".",max_files=200)   — 递归扫描目录，返回带文件类型统计的树\n  analyze_project_summary(path=".")           — 读取并摘要项目结构（manifests/技术栈/入口/README）\n  identify_file_types(path=".")               — 按扩展名统计文件类型分布\n  read_workspace_file(path)                    — 读取单个文件（最多 8000 字符）\n  list_workspace_dir(path)                     — 列出目录条目\n  write_workspace_file(path,content)           — 写入文件（输出文档/报告时使用）\n  run_sandboxed_python(code)                   — 在沙盒里运行纯 Python（标准库）\n'
            steps_line = "工作步骤（必须按顺序执行，不得跳过读取步骤直接生成结论）：\n1. 调用 analyze_project_summary 获取项目概览（技术栈、入口、配置文件）\n2. 调用 scan_project_tree 获取完整目录结构\n3. 按需用 read_workspace_file 读取 README、package.json、pyproject.toml、主配置文件等\n4. 综合真实读取到的信息分析，不允许在没有读取依据时生成任何技术描述\n5. 生成结构化输出（Markdown 文档/JSON 报告），写入工作区或直接返回\n6. 汇总：列出读取了哪些文件、得到哪些关键信息、生成了什么输出\n"
        else:
            tools_line = "你可以使用以下工具（通过 ReAct 循环逐步执行）：\n  read_workspace_file(path)          — 读取工作区文件\n  write_workspace_file(path,content) — 写入文件\n  list_workspace_dir(path)           — 列出目录\n  run_sandboxed_python(code)         — 在沙盒里运行纯 Python\n  http_get(url)/http_post(url,body)  — 发起 HTTP 请求\n"
            steps_line = "工作步骤：\n1. 识别用户意图与必要输入信息\n2. 按需调用工具（读文件/扫目录/运行代码/联网）逐步收集信息\n3. 分析收集到的真实数据，不捏造任何结果\n4. 生成结构化输出（文件/报告/代码/JSON）并写入工作区或直接返回\n5. 汇总结论：执行了哪些步骤、得到什么结果、有哪些警告\n"
        wf_line = (
            f"你也绑定了工作流「{workflow_choice.workflow_name}」用于复杂编排场景；优先用工具自主完成任务，编排任务才进入工作流。"
            if workflow_choice and workflow_choice.workflow_id
            else "当前无绑定工作流；使用上方工具自主完成任务。"
        )
        return f"你是{intent.name}，职责是{intent.role}，服务场景是：{intent.scenario}。\n行业：{intent.industry}，复杂度：{intent.complexity}。\n\n{steps_line}\n{tools_line}\n{wf_line}\n\n禁止：捏造工具结果、访问工作区外的文件、在 answer 里声称做了实际未做的操作。\n若信息不足或工具失败，如实说明失败原因和建议的下一步。"
    workflow_line = (
        f"你已绑定工作流「{workflow_choice.workflow_name}」，它是处理该员工核心任务的主路径；遇到可执行任务时优先判断是否进入该工作流，并在结果中说明关键节点结论。"
        if workflow_choice and workflow_choice.workflow_id
        else "当前未绑定专属工作流；需要执行复杂任务时先拆解步骤，并明确哪些步骤需要后续配置工作流或工具。"
    )
    skill_line = (
        "可用候选技能包括：" + "、".join((f"{s.name}（{s.brief}）" for s in suggested_skills[:6]))
        if suggested_skills
        else "暂无已验证技能；不要声称已经调用外部工具或系统。"
    )
    return f"你是{intent.name}，职责是{intent.role}，服务场景是：{intent.scenario}。你的行业语境是{intent.industry}，任务复杂度为{intent.complexity}。\n{workflow_line}\n{skill_line}\n处理请求时先识别用户目标、输入材料和缺失信息；能直接回答时给出结论，需要执行时列出执行步骤、使用的工作流或技能、关键依据和最终结果。如果信息不足、工作流失败或技能不可用，必须明确说明不确定点、失败位置和建议的下一步。不得编造订单、文件、网页、数据库、工具调用结果或不存在的系统能力。输出保持结构化：先给结论/处理结果，再给依据、步骤、风险或待补充信息。"


def _quality_gate_system_prompt(
    prompt: str,
    *,
    fallback: str,
    intent: Intent,
    workflow_choice: _facade().Optional[WorkflowChoice],
    suggested_skills: _facade().List["SuggestedSkill"],
    handlers: _facade().Optional[_facade().List[str]] = None,
) -> str:
    text = _facade()._normalize_employee_system_prompt(
        prompt, label=intent.name, description=intent.scenario
    )
    bad_markers = ("## 用途", "## 输入", "## 输出", "## 示例")
    too_short = len(text) < 120
    templated = sum((1 for marker in bad_markers if marker in text)) >= 3
    if too_short or templated:
        return fallback
    is_agent = bool(handlers and "agent" in handlers)
    is_direct_python = bool(handlers and "direct_python" in handlers)
    if is_direct_python:
        if len(text) < 40:
            return fallback
        return text
    if is_agent:
        agent_markers = ("工作步骤", "工具", "禁止")
        if not any((m in text for m in agent_markers)):
            return fallback
    else:
        required_markers = ("工作流", "技能", "不得编造")
        if any((marker not in text for marker in required_markers)):
            return fallback
        if (
            workflow_choice
            and workflow_choice.workflow_id
            and (workflow_choice.workflow_name not in text)
        ):
            return fallback
        if suggested_skills and (not any((s.name in text for s in suggested_skills[:3]))):
            return fallback
    return text


async def stage_suggest_skills(
    intent: Intent, llm: _facade().LlmClient
) -> _facade().Tuple[_facade().List[SuggestedSkill], str]:
    ctx = f"角色：{intent.role}\n场景：{intent.scenario}\n行业：{intent.industry}"
    content = await llm.chat(
        [
            {"role": "system", "content": _facade()._SYS_SUGGEST_SKILLS},
            {"role": "user", "content": ctx},
        ],
        max_tokens=2048,
    )
    (data, err) = _facade()._parse_json(content)
    if err:
        return ([], err)
    if not isinstance(data, list):
        return ([], "须返回 JSON 数组")
    skills: _facade().List[SuggestedSkill] = []
    for item in data[:8]:
        if isinstance(item, dict) and item.get("name"):
            skills.append(
                _facade().SuggestedSkill(
                    name=str(item["name"])[:32],
                    brief=str(item.get("brief") or "")[:80],
                    kind=str(item.get("kind") or "")[:64],
                )
            )
    return (skills, "")


async def stage_suggest_pricing(
    intent: Intent,
    v2: EmployeeConfigV2,
    skills: _facade().List[SuggestedSkill],
    llm: _facade().LlmClient,
) -> _facade().Tuple[_facade().Optional[PricingHint], str]:
    handlers = list(v2.actions.get("handlers") or [])
    ctx = f"角色：{intent.role}\n行业：{intent.industry}\n复杂度：{intent.complexity}\n技能数：{len(skills)}\n已启用功能：{', '.join(handlers)}"
    content = await llm.chat(
        [
            {"role": "system", "content": _facade()._SYS_SUGGEST_PRICING},
            {"role": "user", "content": ctx},
        ],
        max_tokens=1024,
    )
    (data, err) = _facade()._parse_json(content)
    if err:
        return (None, err)
    if not isinstance(data, dict):
        return (None, "须返回 JSON 对象")
    return (
        _facade().PricingHint(
            tier=str(data.get("tier") or "free"),
            cny=float(data.get("cny") or 0),
            period=str(data.get("period") or "month"),
            reasoning=str(data.get("reasoning") or "")[:120],
        ),
        "",
    )


def stage_assemble(
    intent: Intent,
    workflow_choice: _facade().Optional[WorkflowChoice],
    v2: EmployeeConfigV2,
    skills: _facade().List[SuggestedSkill],
    pricing: _facade().Optional[PricingHint],
) -> _facade().Tuple[_facade().Optional[_facade().Dict[str, _facade().Any]], _facade().List[str]]:
    from modman.manifest_util import validate_manifest_dict
    from modstore_server.xcagi_host_profile import (
        merge_workflow_employee_for_manifest,
        normalize_xcagi_host_profile,
    )

    eid = intent.id
    (hp_norm, _) = normalize_xcagi_host_profile({"panel_kind": "mod_http"})
    wf_row = merge_workflow_employee_for_manifest(
        employee_id=eid, label=intent.name, panel_summary=intent.scenario, host_profile=hp_norm
    )
    if workflow_choice and workflow_choice.workflow_id:
        wf_row["workflow_id"] = workflow_choice.workflow_id
    metadata: _facade().Dict[str, _facade().Any] = {
        "framework_version": "2.0.0",
        "created_by": "employee_ai_pipeline",
    }
    if skills:
        metadata["suggested_skills"] = [_facade().asdict(s) for s in skills]
    if pricing:
        metadata["suggested_pricing"] = _facade().asdict(pricing)
    if workflow_choice and workflow_choice.workflow_id and (not workflow_choice.sandbox_passed):
        metadata["workflow_needs_sandbox"] = True
    v2_dict = _facade().asdict(v2)
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
    caps = _facade()._default_capabilities(
        pid=intent.id,
        name=intent.name,
        description=intent.scenario,
        employee_id=eid,
        label=intent.name,
        capabilities=[s.name for s in skills],
    )
    if skills:
        cognition["skills"] = [_facade().asdict(s) for s in skills]
    else:
        cognition["skills"] = _facade()._default_skill_entries(
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
    if _facade()._is_project_analysis_intent(intent):
        actions_in_v2 = v2_dict.get("actions")
        if isinstance(actions_in_v2, dict):
            if "agent" not in (actions_in_v2.get("handlers") or []):
                actions_in_v2["handlers"] = ["agent"]
            if not isinstance(actions_in_v2.get("agent"), dict):
                actions_in_v2["agent"] = {}
            actions_in_v2["agent"].setdefault(
                "workspace",
                {"mode": "user_project", "requires_project_root": True, "read_only": True},
            )
        v2_dict["actions"] = actions_in_v2
    manifest: _facade().Dict[str, _facade().Any] = {
        "id": intent.id,
        "name": intent.name,
        "version": "1.0.0",
        "author": "",
        "description": intent.scenario,
        "artifact": "employee_pack",
        "scope": "global",
        "industry": intent.industry,
        "dependencies": {"xcagi": ">=1.0.0"},
        "employee": {"id": eid, "label": intent.name, "capabilities": caps},
        "employee_config_v2": v2_dict,
        "xcagi_host_profile": hp_norm or {"panel_kind": "mod_http"},
        "workflow_employees": [wf_row],
        "backend": {"entry": "blueprints", "init": "mod_init"},
    }
    if pricing and (pricing.cny > 0 or pricing.tier != "free"):
        manifest["commerce"] = {
            "price": pricing.cny,
            "currency": "CNY",
            "tier": pricing.tier,
            "period": pricing.period,
        }
    errs = validate_manifest_dict(manifest)
    return (manifest, errs)


def _build_vibe_coding_prompt(
    runtime_kind: str, rule_spec: _facade().Dict[str, _facade().Any]
) -> str:
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
        _facade().json.dumps(output_schema, ensure_ascii=False)
        if output_schema
        else "(see rule_spec)"
    )
    prompt = (
        "你是工作台 vibecoding 的 Python 实现器。你的任务是生成 convert.py —— 一个完整的、可直接运行的 Python 文件，用于处理特定文件格式。\n\n## 核心要求\n\n1. 必须定义 `convert_file(src_path: Path, output_path: Path, *, template_path: Optional[Path], payload: Dict[str, Any], ctx: Dict[str, Any], rule_spec: Dict[str, Any]) -> Dict[str, Any]` 函数\n2. 必须真实读取输入文件、按规则写出 output_path，不能写伪结果或占位符\n3. 输出 JSON 必须包含以下顶层字段: "
        + schema_str
        + "\n4. 同时输出纯文本文件 (document_full.txt)\n\n## 安全约束\n\n- 禁止使用: eval/exec/compile/__import__/subprocess/os.system/ctypes/multiprocessing\n- 允许使用: pathlib, json, datetime, re, typing, io, copy, collections, zipfile, xml.etree.ElementTree, openpyxl, pandas\n- 对于 .docx 文件，必须用 zipfile + ElementTree 直接解析 OOXML，不要依赖 python-docx\n\n## 输出格式\n\n只输出一个完整的 Python 文件（不要 Markdown 围栏、不要解释、不要注释说明这是生成的代码）\n\n"
    )
    if few_shot_code:
        prompt += (
            "## 参考实现 (few-shot example)\n\n以下是一个类似任务的参考实现，你可以学习其代码结构、命名规范和解析策略，但需要根据当前 brief 和 rule_spec 生成你自己的实现：\n\n```python\n"
            + few_shot_code
            + "\n```\n\n"
        )
    prompt += f"## 当前任务\n\nruntime_kind: {runtime_kind}\n请根据下方 user message 中的 brief 和 rule_spec 生成 convert.py。"
    return prompt


@_facade().dataclass
class GeneratedCode:
    employee_py: str = ""
    vendor_modules: _facade().Dict[str, str] = _facade().field(default_factory=dict)
    rule_spec: _facade().Dict[str, _facade().Any] = _facade().field(default_factory=dict)
    asset_manifest: _facade().Dict[str, _facade().Any] = _facade().field(default_factory=dict)
    runtime_kind: str = ""
    code_source: str = ""
    warnings: _facade().List[str] = _facade().field(default_factory=list)
