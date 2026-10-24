"""Auto-merged part* modules (debt24)."""

from __future__ import annotations

import importlib

# --- from employee_ai_scaffold_part_1.py ---
"""Employee scaffold helpers split by generation responsibility."""


import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_scaffold")


def _is_template_brief(brief: str) -> bool:
    if not brief or len(brief) < 8:
        return True
    _hit = sum((1 for p in _facade()._TEMPLATE_BRIEF_PATTERNS if p in brief))
    return _hit >= 2


def _validate_skill_quality(
    skills: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    label: str,
    description: str,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    for sk in skills:
        if not isinstance(sk, dict):
            continue
        brief = str(sk.get("brief") or "").strip()
        cap_name = str(sk.get("name") or sk.get("skill_id") or "").strip()
        if _facade()._is_template_brief(brief):
            sk["brief"] = _facade()._default_skill_brief(
                cap_name, label=label, description=description
            )
        if not sk.get("name") and (not sk.get("skill_id")):
            sk["name"] = "task.analyze"
    return skills


def _default_capabilities(
    *,
    pid: str,
    name: str,
    description: str,
    employee_id: str,
    label: str,
    capabilities: _facade().List[str],
    department_preset: _facade().Optional[str] = None,
) -> _facade().List[str]:
    caps = [str(x).strip()[:128] for x in capabilities if str(x).strip()]
    if caps:
        return caps[:8]
    preset_caps, _preset_meta = _facade().resolve_preset_capabilities(department_preset)
    if preset_caps:
        return preset_caps[:8]
    text = " ".join([pid, name, description, employee_id, label]).lower()
    if any((k in text for k in ("seo", "sitemap", "站点地图", "robots", "百度", "baidu", "push"))):
        return ["seo.sitemap", "seo.robots", "seo.baidu_push", "seo.verification_files"]
    if any((k in text for k in ("退款", "refund", "售后"))):
        return ["refund.review", "order.check", "customer.reply"]
    if any((k in text for k in ("文档", "readme", "docs", "documentation"))):
        return ["docs.readme", "project.analyze", "docs.summary"]
    return ["task.analyze", "llm.markdown", "workflow.assist"]


def _default_skill_entries(
    caps: _facade().List[str], *, label: str, description: str
) -> _facade().List[_facade().Dict[str, str]]:
    if not caps:
        caps = _facade()._default_capabilities(
            pid="",
            name=label,
            description=description,
            employee_id="",
            label=label,
            capabilities=[],
        )
    entries: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for cap in caps[:6]:
        entry: _facade().Dict[str, _facade().Any] = {
            "name": cap,
            "brief": _facade()._default_skill_brief(cap, label=label, description=description),
        }
        if cap.startswith("seo."):
            entry.update(_facade()._seo_skill_structure(cap))
        entries.append(entry)
    return entries


def _default_skill_brief(cap: str, *, label: str, description: str) -> str:
    seo_briefs = {
        "seo.sitemap": "检查 sitemap.xml / sitemap_index.xml 路径、URL、lastmod 与提交清单",
        "seo.robots": "检查 robots.txt 允许/禁止规则与 Sitemap 指向是否正确",
        "seo.baidu_push": "生成 baidu_urls.txt / 百度主动推送清单与执行说明",
        "seo.verification_files": "核对 BingSiteAuth.xml 与 baidu_verify_*.html 等站点验证文件",
    }
    if cap in seo_briefs:
        return seo_briefs[cap]
    _semantic_briefs = {
        "task.analyze": "分析用户任务意图，拆解为可执行步骤，输出结构化任务清单与依赖关系",
        "llm.markdown": "调用大语言模型生成结构化 Markdown 文档，包含用途、输入、输出、示例与异常处理章节",
        "workflow.assist": "辅助工作流编排，根据用户需求推荐节点组合与执行顺序，输出可执行的流程方案",
        "invoice.parse": "解析发票 PDF/图片，提取金额、日期、税号等关键字段，输出结构化 JSON",
        "report.monthly": "汇总月度数据，生成统计报表与趋势分析，输出 Markdown 或 Excel 格式报告",
        "chat.summarize": "对长对话或文档进行摘要提取，保留关键决策与行动项，输出精简摘要",
        "refund.review": "审核退款申请，校验订单状态与退款规则，输出审核结论与处理建议",
        "order.check": "检查订单状态与履约进度，标记异常订单，输出待处理清单",
        "customer.reply": "根据客户问题生成专业回复，引用知识库或政策文档，输出可发送的回复内容",
        "docs.readme": "生成或更新项目 README 文档，包含安装、使用、配置与常见问题章节",
        "project.analyze": "分析项目结构与代码质量，输出架构概览、依赖关系与改进建议",
        "docs.summary": "对技术文档进行摘要与索引，提取核心概念与 API 说明，输出可检索的知识条目",
    }
    if cap in _semantic_briefs:
        return _semantic_briefs[cap]
    _cap_parts = cap.split(".") if "." in cap else [cap]
    _domain = _cap_parts[0] if len(_cap_parts) > 1 else ""
    _action = _cap_parts[-1] if len(_cap_parts) > 1 else cap
    _action_verbs = {
        "analyze": "分析",
        "parse": "解析",
        "generate": "生成",
        "check": "检查",
        "review": "审核",
        "summarize": "摘要",
        "assist": "辅助",
        "convert": "转换",
        "extract": "提取",
        "validate": "校验",
        "monitor": "监控",
        "export": "导出",
        "import": "导入",
        "sync": "同步",
        "notify": "通知",
        "reply": "回复",
    }
    _domain_names = {
        "seo": "SEO 站点资产",
        "invoice": "发票",
        "order": "订单",
        "refund": "退款",
        "customer": "客户",
        "docs": "文档",
        "project": "项目",
        "chat": "对话",
        "report": "报表",
        "data": "数据",
        "task": "任务",
        "workflow": "工作流",
        "llm": "大语言模型",
        "payment": "支付",
        "contract": "合同",
        "asset": "资产",
    }
    _verb_cn = _action_verbs.get(_action, _action)
    _domain_cn = _domain_names.get(_domain, _domain or label or "业务")
    _desc_hint = ""
    if description and len(description) > 2:
        _desc_hint = f"，服务于：{description[:80]}"
    return f"{_verb_cn}{_domain_cn}相关内容，输出结构化结果{_desc_hint}"


def _seo_skill_structure(cap: str) -> _facade().Dict[str, _facade().Any]:
    focus_by_cap = {
        "seo.sitemap": ["sitemap.xml", "sitemap_index.xml"],
        "seo.robots": ["robots.txt"],
        "seo.baidu_push": ["baidu_urls.txt"],
        "seo.verification_files": ["BingSiteAuth.xml", "baidu_verify_*.html"],
    }
    logic_by_cap = {
        "seo.sitemap": "读取 sitemap 文件，校验 XML 结构、URL、lastmod 与索引关系，输出修复 diff。",
        "seo.robots": "读取 robots.txt，校验 Allow/Disallow 与 Sitemap 指向，输出最小修复 diff。",
        "seo.baidu_push": "读取或生成 baidu_urls.txt，校验 URL 去重、协议和提交批次，输出推送清单。",
        "seo.verification_files": "核对 BingSiteAuth.xml 与 baidu_verify_*.html 是否存在且 token 来源明确，缺失时输出待人工确认的文件片段。",
    }
    focus_paths = focus_by_cap.get(cap, _facade()._seo_focus_paths())
    return {
        "skill_id": f"skill-{cap.replace('.', '-').replace('_', '-')}",
        "domain": "seo-static-files",
        "version": "1.0.0",
        "lifecycle": "static_dynamic_solidify",
        "static_phase": {
            "trigger_conditions": [
                "输入包含 SEO 静态文件维护任务",
                "目标文件位于 focus_paths 白名单内",
                "未出现未知验证码 token 或越权路径",
            ],
            "execution_graph": [
                "读取 focus_paths",
                "校验文件结构与业务规则",
                "生成 Markdown 摘要和 unified diff",
                "输出质量门禁结果",
            ],
            "output_schema": {
                "status": "ok | error",
                "result": {"summary": "str", "diff": "str", "warnings": "list[str]"},
                "metrics": {"quality_score": "float", "files_checked": "int"},
            },
            "tools": ["read_workspace_file", "vibe_edit", "python.ElementTree"],
            "focus_paths": focus_paths,
            "logic": logic_by_cap.get(cap, "执行 SEO 静态文件检查并输出修复 diff。"),
        },
        "trigger_rules": [
            {
                "type": "execution_error",
                "rule": "读取/解析文件失败",
                "threshold": "immediate",
            },
            {
                "type": "quality_gate",
                "rule": "quality_score < 0.85",
                "threshold": "0.85",
            },
            {
                "type": "special_case",
                "rule": "发现未确认的验证 token 或未知 SEO 文件",
                "threshold": "manual_review",
            },
        ],
        "dynamic_phase": {
            "budget": {"max_tokens": 4000, "max_steps": 5},
            "allowed_patch_scope": focus_paths,
            "patch_format": {
                "patch_id": "<uuid>",
                "base_version": "1.0.0",
                "proposals": [
                    {
                        "target_step": "读取/校验/输出",
                        "change_type": "add_branch | modify_param | add_exception_handler",
                        "description": "...",
                        "code_diff": "...",
                    }
                ],
            },
        },
        "solidify": {
            "acceptance": [
                "动态路径任务执行成功",
                "输出 status == ok",
                "quality_score >= 0.85",
                "未越出 focus_paths 白名单",
            ],
            "actions": [
                "写入 skills/skill-<功能名>-v<N+1>.md",
                "递增 employee.yaml 版本",
                "旧版本标记 deprecated 供回滚",
            ],
        },
        "metrics": {
            "static_success_rate_target": ">=95%",
            "dynamic_trigger_rate_target": "<=10%",
            "solidify_frequency": "monthly_when_used",
            "avg_latency_static": "<10s",
            "avg_token_static": "<500",
        },
    }


def _is_seo_context(*parts: str) -> bool:
    text = " ".join((str(p or "") for p in parts)).lower()
    return any(
        (
            k in text
            for k in (
                "seo",
                "sitemap",
                "站点地图",
                "robots",
                "百度",
                "baidu",
                "bing",
                "push",
            )
        )
    )


def _seo_few_shot_examples() -> _facade().List[_facade().Dict[str, _facade().Any]]:
    return [
        {
            "input": {
                "task": "检查并修复 sitemap 与 robots",
                "files": ["sitemap.xml", "robots.txt", "baidu_urls.txt"],
            },
            "output": {
                "mode": "patch",
                "summary": "生成 sitemap.xml / robots.txt / baidu_urls.txt 的建议 diff；未声明 file.write 时不直接落盘。",
                "diff": {
                    "robots.txt": "Sitemap: https://example.com/sitemap.xml",
                    "baidu_urls.txt": "https://example.com/page-a",
                },
            },
        },
        {
            "input": {
                "task": "补齐搜索引擎验证文件",
                "assets": ["BingSiteAuth.xml", "baidu_verify_xxx.html"],
            },
            "output": {
                "mode": "checklist",
                "required_assets": ["BingSiteAuth.xml", "baidu_verify_*.html"],
                "warning": "无法确认真实 token 时只输出待替换占位，不编造验证码。",
            },
        },
    ]


def _seo_focus_paths() -> _facade().List[str]:
    return [
        "sitemap.xml",
        "sitemap_index.xml",
        "robots.txt",
        "baidu_urls.txt",
        "BingSiteAuth.xml",
        "baidu_verify_*.html",
    ]


def _seo_prompt_suffix(write_mode: str) -> str:
    return (
        "\n\nSEO 维护资产范围："
        + "、".join(_facade()._seo_focus_paths())
        + f"""。\nXML 校验优先使用 xmllint；若运行环境没有 xmllint（Windows 常见），必须使用 python -c "import xml.etree.ElementTree as ET; ET.parse('sitemap.xml')" 或等价的 Python ElementTree 校验，不得因为 xmllint 缺失而停止。\n默认执行模式：{write_mode}。当前未声明 file.write/sandbox/git 等可写工具时，只能输出可审阅的 Markdown 方案、文件片段和 unified diff，不得声称已经写入仓库。只有 manifest.actions 明确配置可写 workspace 或脚本工作流执行环境后，才允许描述自动落盘。"""
    )


def _ensure_seo_runtime_details(
    out: _facade().Dict[str, _facade().Any],
    *,
    pid: str,
    name: str,
    description: str,
    label: str,
) -> None:
    if not _facade()._is_seo_context(pid, name, description, label):
        return
    cognition = out.get("cognition") if isinstance(out.get("cognition"), dict) else {}
    agent = cognition.get("agent") if isinstance(cognition.get("agent"), dict) else {}
    model = agent.get("model") if isinstance(agent.get("model"), dict) else {}
    model["temperature"] = min(float(model.get("temperature", 0.2) or 0.2), 0.3)
    model.setdefault("max_tokens", 4000)
    agent["model"] = model
    actions = out.get("actions") if isinstance(out.get("actions"), dict) else {}
    handlers = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    can_write = any(
        (
            h in handlers
            for h in (
                "agent",
                "vibe_edit",
                "vibe_heal",
                "vibe_code",
                "file.write",
                "sandbox",
                "git",
            )
        )
    )
    focus_paths = _facade()._seo_focus_paths()
    vibe_edit = actions.get("vibe_edit") if isinstance(actions.get("vibe_edit"), dict) else {}
    if "vibe_edit" in handlers:
        vibe_edit.setdefault("root", ".")
        existing_focus = (
            vibe_edit.get("focus_paths") if isinstance(vibe_edit.get("focus_paths"), list) else []
        )
        merged_focus = [str(x).strip() for x in existing_focus if str(x).strip()]
        for path in focus_paths:
            if path not in merged_focus:
                merged_focus.append(path)
        vibe_edit["focus_paths"] = merged_focus
        vibe_edit.setdefault(
            "brief",
            "根据用户任务维护 SEO 静态文件。只编辑 focus_paths 中列出的文件；核对 sitemap.xml、sitemap_index.xml、robots.txt、baidu_urls.txt、BingSiteAuth.xml、baidu_verify_*.html，并输出修改摘要。",
        )
        actions["vibe_edit"] = vibe_edit
    else:
        actions["vibe_edit_ready"] = {
            "root": ".",
            "focus_paths": focus_paths,
            "brief": "启用 actions.handlers += ['vibe_edit'] 后，按这些路径自动维护 SEO 静态文件。",
        }
    out["actions"] = actions
    write_mode = "自动写入文件" if can_write else "仅生成补丁与人工落盘方案"
    prompt = str(agent.get("system_prompt") or "").strip()
    if "BingSiteAuth.xml" not in prompt:
        prompt += _facade()._seo_prompt_suffix(write_mode)
    agent["system_prompt"] = prompt
    if not agent.get("few_shot_examples"):
        agent["few_shot_examples"] = _facade()._seo_few_shot_examples()
    cognition["agent"] = agent
    out["cognition"] = cognition
    metadata = out.get("metadata") if isinstance(out.get("metadata"), dict) else {}
    metadata["package_id"] = pid
    metadata["recommended_filename"] = f"{pid}.xcemp"
    metadata["id_alignment_note"] = (
        "package filename, manifest.id, employee.id, workflow_employees.id and api_base_path should use the same id stem."
    )
    metadata["workflow_runtime_check"] = (
        "Before publishing, verify workflow_id/script_workflow_id exist in the target online database."
    )
    out["metadata"] = metadata


def _normalize_action_handlers(raw_handlers: _facade().Any) -> _facade().List[str]:
    allowed = {
        "echo",
        "llm_md",
        "http_request",
        "webhook",
        "data_sync",
        "direct_python",
        "wechat_notify",
        "openapi_tool",
        "fhd_business",
        "voice_output",
        "agent",
        "para_delegate",
        "cursor_delegate",
        "vibe_edit",
        "vibe_heal",
        "vibe_code",
        "doc_sync",
        "shell_exec",
        "ssh_exec",
        "specialized",
    }
    handlers: _facade().List[str] = []
    if isinstance(raw_handlers, list):
        for h in raw_handlers:
            hs = str(h).strip()
            if hs in allowed and hs not in handlers:
                handlers.append(hs)
    if not handlers:
        return ["llm_md", "echo"]
    if "llm_md" in handlers and "echo" not in handlers:
        handlers.append("echo")
    return handlers


# --- from employee_ai_scaffold_part_2_part01.py ---
"""Implementation extracted from the public facade module."""


import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_scaffold")


def _strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = _facade().re.sub("^```(?:json)?\\s*", "", t, flags=_facade().re.I)
        t = _facade().re.sub("\\s*```\\s*$", "", t)
    return t.strip()


def parse_employee_pack_llm_json(
    content: str,
) -> _facade().Tuple[_facade().Optional[_facade().Dict[str, _facade().Any]], str]:
    raw = _facade()._strip_json_fence(content)
    try:
        data = _facade().json.loads(raw)
    except _facade().json.JSONDecodeError as e:
        return (None, f"模型返回非合法 JSON: {e}")
    if not isinstance(data, dict):
        return (None, "JSON 根须为对象")
    pid = str(data.get("id") or "").strip().lower()
    if not pid or not _facade()._ID_RE.match(pid):
        return (None, "id 无效：须匹配小写字母/数字/._- 且不以连字符开头")
    name = str(data.get("name") or pid).strip() or pid
    ver = str(data.get("version") or "1.0.0").strip() or "1.0.0"
    desc = str(data.get("description") or "").strip()
    emp_in = data.get("employee")
    if not isinstance(emp_in, dict):
        return (None, "须包含 employee 对象")
    eid = pid
    label = str(emp_in.get("label") or name).strip() or name
    caps_in = emp_in.get("capabilities")
    caps: _facade().List[str] = []
    if isinstance(caps_in, list):
        for x in caps_in:
            if isinstance(x, str) and x.strip():
                caps.append(x.strip())
    dept_preset = str(data.get("department_preset") or "").strip().lower() or None
    caps = _facade()._default_capabilities(
        pid=pid,
        name=name,
        description=desc,
        employee_id=eid,
        label=label,
        capabilities=caps,
        department_preset=dept_preset,
    )
    manifest: _facade().Dict[str, _facade().Any] = {
        "id": pid,
        "name": name,
        "version": ver,
        "author": "",
        "description": desc,
        "artifact": "employee_pack",
        "scope": "global",
        "dependencies": {"xcagi": ">=1.0.0"},
        "employee": {"id": eid, "label": label, "capabilities": caps},
    }
    v2_in = data.get("employee_config_v2")
    if isinstance(v2_in, dict):
        manifest["employee_config_v2"] = _facade()._normalize_employee_config_v2_for_canvas(
            v2_in,
            pid=pid,
            name=name,
            description=desc,
            employee_id=eid,
            label=label,
            capabilities=caps,
        )
    else:
        manifest["employee_config_v2"] = _facade()._default_employee_config_v2(
            pid=pid, name=name, description=desc, employee_id=eid, label=label, capabilities=caps
        )
    hp_raw = data.get("xcagi_host_profile")
    hp_norm, hp_errs = _facade().normalize_xcagi_host_profile(hp_raw)
    if hp_errs:
        return (None, "xcagi_host_profile: " + "; ".join(hp_errs))
    if hp_norm:
        manifest["xcagi_host_profile"] = hp_norm
    wf_row = _facade().merge_workflow_employee_for_manifest(
        employee_id=eid, label=label, panel_summary=desc, host_profile=hp_norm
    )
    wf_row["api_base_path"] = f"employees/{eid}"
    manifest["workflow_employees"] = [wf_row]
    manifest["backend"] = {"entry": "blueprints", "init": "mod_init"}
    ve = _facade().validate_manifest_dict(manifest)
    if ve:
        return (None, "manifest 校验: " + "; ".join(ve))
    return (manifest, "")


def _normalize_employee_config_v2_for_canvas(
    v2: _facade().Dict[str, _facade().Any],
    *,
    pid: str,
    name: str,
    description: str,
    employee_id: str,
    label: str,
    capabilities: _facade().List[str],
) -> _facade().Dict[str, _facade().Any]:
    """Guarantee the employee canvas modules have concrete editable fields.

    The LLM may return a sparse ``employee_config_v2``.  The workbench canvas,
    however, edits fixed module slices (identity, cognition.agent,
    cognition.skills, collaboration.workflow).  Fill those slices at generation
    time so the generated package itself is complete instead of relying on
    frontend recovery heuristics.
    """
    out = dict(v2 or {})
    identity = dict(out.get("identity") if isinstance(out.get("identity"), dict) else {})
    identity.update(
        {
            "id": pid,
            "version": str(identity.get("version") or "1.0.0").strip() or "1.0.0",
            "artifact": str(identity.get("artifact") or "employee_pack").strip() or "employee_pack",
            "name": str(identity.get("name") or name or label or employee_id).strip() or pid,
            "description": str(identity.get("description") or description).strip(),
        }
    )
    out["identity"] = identity
    cognition = dict(out.get("cognition") if isinstance(out.get("cognition"), dict) else {})
    agent = dict(cognition.get("agent") if isinstance(cognition.get("agent"), dict) else {})
    role = dict(agent.get("role") if isinstance(agent.get("role"), dict) else {})
    role.update(
        {
            "name": str(role.get("name") or label or name).strip() or pid,
            "persona": str(role.get("persona") or description or "专业、高效、亲切").strip(),
            "tone": str(role.get("tone") or "professional").strip() or "professional",
            "expertise": (
                role.get("expertise") if isinstance(role.get("expertise"), list) else capabilities
            ),
        }
    )
    model = dict(agent.get("model") if isinstance(agent.get("model"), dict) else {})
    model.update(
        {
            "provider": str(model.get("provider") or "auto").strip() or "auto",
            "model_name": str(model.get("model_name") or "auto").strip() or "auto",
            "temperature": model.get("temperature", 0.7),
            "max_tokens": model.get("max_tokens", 4000),
            "top_p": model.get("top_p", 0.9),
        }
    )
    agent.update(
        {
            "system_prompt": _facade()._normalize_employee_system_prompt(
                str(
                    agent.get("system_prompt")
                    or description
                    or f"你是员工助手：{label or name}。请根据用户输入完成任务，并输出结构化结果。"
                ).strip(),
                label=label or name,
                description=description,
            ),
            "role": role,
            "behavior_rules": _facade()._normalize_behavior_rules(
                agent.get("behavior_rules"), label=label or name, description=description
            ),
            "few_shot_examples": (
                agent.get("few_shot_examples")
                if isinstance(agent.get("few_shot_examples"), list)
                else []
            ),
            "model": model,
        }
    )
    cognition["agent"] = agent
    caps_norm = _facade()._default_capabilities(
        pid=pid,
        name=name,
        description=description,
        employee_id=employee_id,
        label=label,
        capabilities=capabilities,
    )
    if not isinstance(cognition.get("skills"), list) or not cognition.get("skills"):
        cognition["skills"] = _facade()._default_skill_entries(
            caps_norm, label=label or name, description=description
        )
    else:
        cognition["skills"] = _facade()._validate_skill_quality(
            cognition["skills"], label=label or name, description=description
        )
    out["cognition"] = cognition
    collaboration = dict(
        out.get("collaboration") if isinstance(out.get("collaboration"), dict) else {}
    )
    workflow = dict(
        collaboration.get("workflow") if isinstance(collaboration.get("workflow"), dict) else {}
    )
    workflow.setdefault("workflow_id", 0)
    workflow["name"] = str(workflow.get("name") or label or name or pid).strip() or pid
    collaboration["workflow"] = workflow
    out["collaboration"] = collaboration
    actions = dict(out.get("actions") if isinstance(out.get("actions"), dict) else {})
    raw_handlers = actions.get("handlers")
    actions["handlers"] = _facade()._normalize_action_handlers(raw_handlers)
    out["actions"] = actions
    out.setdefault("metadata", {"framework_version": "2.0.0", "created_by": "employee_ai_scaffold"})
    _facade()._ensure_seo_runtime_details(
        out, pid=pid, name=name, description=description, label=label or name
    )
    return out


def _normalize_employee_system_prompt(prompt: str, *, label: str, description: str) -> str:
    text = str(prompt or "").strip()
    banned_template = ("## 用途", "## 输入", "## 输出", "## 示例")
    if not text or all((marker in text for marker in banned_template)):
        role = str(label or "员工助手").strip() or "员工助手"
        desc = str(description or "根据用户输入完成任务").strip()
        return f"你是{role}。你的职责是：{desc}。\n工作时先判断用户目标和可用上下文，只使用输入中给出的事实与工具结果；信息不足时先说明缺口并给出可继续推进的最小问题。\n输出应直接服务任务：先给结论或执行结果，再给必要依据、步骤和下一步建议。不得编造来源、数据、执行结果或不存在的系统能力。"
    return text


def _normalize_behavior_rules(
    raw: _facade().Any, *, label: str, description: str
) -> _facade().List[str]:
    if isinstance(raw, list):
        rules = [str(x).strip() for x in raw if str(x).strip()]
        if rules:
            cleaned: _facade().List[str] = []
            for rule in rules:
                if len(rule) > 120:
                    rule = rule[:117].rstrip() + "…"
                cleaned.append(rule)
            return cleaned[:8]
    role = str(label or "当前员工").strip()
    task = str(description or "用户任务").strip()
    if len(task) > 72:
        task = task[:69].rstrip() + "…"
    return [
        f"始终围绕{role}的职责范围处理请求。",
        "优先使用 input 中提供的 manifest_signals / role_context / yuangon 节选作答；缺口用「待确认」标注，不要补造缺失事实。",
        "当输入不足、工具失败或结论不确定时，明确说明原因和需要补充的信息。",
        "输出保持结构化、可执行，避免泛泛而谈。",
    ]


def _default_employee_config_v2(
    *,
    pid: str,
    name: str,
    description: str,
    employee_id: str,
    label: str,
    capabilities: _facade().List[str],
) -> _facade().Dict[str, _facade().Any]:
    text = " ".join([pid, name, description, employee_id, label, " ".join(capabilities)]).lower()
    wants_rankings = any(
        (k in text for k in ("排行", "rank", "leaderboard", "模型", "model", "上网", "联网"))
    )
    perception: _facade().Dict[str, _facade().Any] = {
        "type": "web_rankings" if wants_rankings else "text"
    }
    prompt = (
        "你是 AI 模型排行榜统计员工。请基于输入中的网页抓取片段，整理主流 AI 模型的排名、模型名称、来源网站和简短结论；如果某来源抓取失败，要明确列出失败来源，不要编造未出现在片段中的排名。"
        if wants_rankings
        else _facade()._normalize_employee_system_prompt(
            "", label=label or name, description=description
        )
    )
    return {
        "identity": {
            "id": pid,
            "version": "1.0.0",
            "artifact": "employee_pack",
            "name": name,
            "description": description,
        },
        "perception": perception,
        "memory": {"type": "session"},
        "cognition": {
            "agent": {
                "system_prompt": prompt,
                "role": {
                    "name": label or name,
                    "persona": description or "专业、高效、亲切",
                    "tone": "professional",
                    "expertise": capabilities,
                },
                "behavior_rules": _facade()._normalize_behavior_rules(
                    [], label=label or name, description=description
                ),
                "few_shot_examples": [],
                "model": {
                    "provider": "auto",
                    "model_name": "auto",
                    "temperature": 0.2,
                    "max_tokens": 4000,
                    "top_p": 0.9,
                },
            },
            "skills": _facade()._default_skill_entries(
                capabilities, label=label or name, description=description
            ),
        },
        "collaboration": {"workflow": {"workflow_id": 0, "name": label or name or pid}},
        "actions": {
            "handlers": ["direct_python"],
            "direct_python": {
                "module": _facade().sanitize_employee_stem(employee_id),
                "action": "convert",
                "default_output_relpath": "outputs/employee_output.xlsx",
                "default_template_relpath": "",
                "default_use_personnel_roster": True,
            },
        },
        "metadata": {"framework_version": "2.0.0", "created_by": "employee_ai_scaffold"},
    }


def append_employee_stub_files_to_zip(
    zf: _facade().zipfile.ZipFile, pack_id: str, manifest: _facade().Dict[str, _facade().Any]
) -> None:
    """写入 ``backend/employee_stubs`` 占位模块（与 workflow 脚手架一致，供安装包浏览 / XCAGI 对齐）。"""
    emp_id = pack_id
    safe = _facade().safe_stub_module_name(emp_id)
    base = f"{pack_id}/backend/employee_stubs".replace("\\", "/")
    zf.writestr(f"{base}/__init__.py", '"""Packaged employee route stubs."""\n')
    zf.writestr(f"{base}/{safe}.py", _facade().stub_module_body(emp_id, safe))


# --- from employee_ai_scaffold_part_2_part02.py ---
"""Implementation extracted from the public facade module."""


import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_scaffold")


def build_employee_pack_zip(
    pack_id: str, manifest: _facade().Dict[str, _facade().Any], *, include_runtime: bool = True
) -> bytes:
    """manifest.zip：含 manifest.json；可选 ``backend/blueprints.py`` + ``backend/employees`` 运行时（与 FHD 挂载契约对齐）。"""
    import copy

    mf = copy.deepcopy(manifest)
    mf["id"] = pack_id
    if isinstance(mf.get("employee"), dict):
        mf["employee"]["id"] = pack_id
    for _row in mf.get("workflow_employees") or []:
        if isinstance(_row, dict):
            _row["id"] = pack_id
    body = _facade().json.dumps(mf, ensure_ascii=False, indent=2) + "\n"
    buf = _facade().io.BytesIO()
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    eid = pack_id
    stem = _facade().sanitize_employee_stem(eid)
    label = str(emp.get("label") or eid).strip()
    with _facade().zipfile.ZipFile(buf, "w", _facade().zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{pack_id}/manifest.json", body)
        if include_runtime:
            bp = _facade().render_employee_pack_blueprints_py(
                pack_id=pack_id, employee_id=eid, stem=stem, label=label
            )
            zf.writestr(f"{pack_id}/backend/blueprints.py", bp)
            emp_py = _facade().render_employee_pack_employee_py(
                employee_id=eid, stem=stem, label=label
            )
            zf.writestr(f"{pack_id}/backend/employees/{stem}.py", emp_py)
            zf.writestr(
                f"{pack_id}/backend/employees/__init__.py",
                '"""Generated employee implementations (employee_pack)."""\n',
            )
        else:
            _facade().append_employee_stub_files_to_zip(zf, pack_id, manifest)
    return buf.getvalue()


def normalize_editor_manifest_for_registry(
    mf: _facade().Dict[str, _facade().Any], pack_id: str
) -> _facade().Tuple[_facade().Dict[str, _facade().Any], _facade().List[str]]:
    """画布形态 manifest → 登记级 manifest（补顶层字段、employee 对象、backend）。

    工作台编辑器把 ``identity``/``cognition``/… 放在根上（画布形态），
    而 ``validate_manifest_dict`` 要求顶层有 ``artifact``/``name``/``version``/
    ``employee`` 等字段（登记形态）。本函数做单向提升，**不修改**原对象，
    返回 (规范化后 manifest, 校验错误列表)。
    """
    import copy

    out = copy.deepcopy(mf)
    ident = out.get("identity") if isinstance(out.get("identity"), dict) else {}
    if not isinstance(out.get("artifact"), str) or not out["artifact"].strip():
        out["artifact"] = str(ident.get("artifact") or "employee_pack").strip() or "employee_pack"
    out["id"] = pack_id
    if isinstance(ident, dict):
        ident["id"] = pack_id
        out["identity"] = ident
    if not str(out.get("name") or "").strip():
        out["name"] = str(ident.get("name") or out["id"]).strip() or out["id"]
    if not str(out.get("version") or "").strip():
        out["version"] = str(ident.get("version") or "1.0.0").strip() or "1.0.0"
    if not str(out.get("description") or "").strip():
        out["description"] = str(ident.get("description") or "").strip()
    out.setdefault("scope", "global")
    out.setdefault("backend", {"entry": "blueprints", "init": "mod_init"})
    if not isinstance(out.get("employee"), dict):
        eid = pack_id
        label = str(ident.get("name") or out.get("name") or eid).strip() or eid
        cognition = out.get("cognition") if isinstance(out.get("cognition"), dict) else {}
        caps: _facade().List[str] = []
        for sk in cognition.get("skills") or []:
            if isinstance(sk, dict):
                n = str(sk.get("name") or sk.get("skill_id") or "").strip()
                if n:
                    caps.append(n)
        caps = _facade()._default_capabilities(
            pid=str(out.get("id") or pack_id),
            name=str(out.get("name") or ""),
            description=str(out.get("description") or ""),
            employee_id=eid,
            label=label,
            capabilities=caps,
        )
        out["employee"] = {"id": eid, "label": label, "capabilities": caps}
    else:
        emp_obj = out["employee"]
        emp_obj["id"] = pack_id
        emp_obj.setdefault("label", str(out.get("name") or pack_id))
        emp_caps = (
            emp_obj.get("capabilities") if isinstance(emp_obj.get("capabilities"), list) else []
        )
        emp_obj["capabilities"] = _facade()._default_capabilities(
            pid=str(out.get("id") or pack_id),
            name=str(out.get("name") or ""),
            description=str(out.get("description") or ""),
            employee_id=pack_id,
            label=str(emp_obj.get("label") or out.get("name") or ""),
            capabilities=emp_caps,
        )
    if not isinstance(out.get("employee_config_v2"), dict):
        v2: _facade().Dict[str, _facade().Any] = {}
        for slice_key in (
            "identity",
            "cognition",
            "perception",
            "memory",
            "actions",
            "collaboration",
            "management",
            "metadata",
        ):
            if isinstance(out.get(slice_key), dict):
                v2[slice_key] = copy.deepcopy(out[slice_key])
        if v2:
            out["employee_config_v2"] = _facade()._normalize_employee_config_v2_for_canvas(
                v2,
                pid=out["id"],
                name=out["name"],
                description=out.get("description") or "",
                employee_id=pack_id,
                label=str((out.get("employee") or {}).get("label") or out["name"]),
                capabilities=(out.get("employee") or {}).get("capabilities") or [],
            )
    elif isinstance(out.get("employee_config_v2"), dict):
        emp_obj = out.get("employee") if isinstance(out.get("employee"), dict) else {}
        out["employee_config_v2"] = _facade()._normalize_employee_config_v2_for_canvas(
            out["employee_config_v2"],
            pid=str(out.get("id") or pack_id),
            name=str(out.get("name") or pack_id),
            description=str(out.get("description") or ""),
            employee_id=pack_id,
            label=str(emp_obj.get("label") or out.get("name") or pack_id),
            capabilities=(
                emp_obj.get("capabilities") if isinstance(emp_obj.get("capabilities"), list) else []
            ),
        )
    if not out.get("workflow_employees"):
        wf_row = _facade().merge_workflow_employee_for_manifest(
            employee_id=str(out.get("id") or pack_id),
            label=str((out.get("employee") or {}).get("label") or out["name"]),
            panel_summary=out.get("description") or "",
            host_profile=None,
        )
        out["workflow_employees"] = [wf_row]
    elif isinstance(out.get("workflow_employees"), list):
        emp_obj = out.get("employee") if isinstance(out.get("employee"), dict) else {}
        eid = str(out.get("id") or pack_id).strip() or pack_id
        for row in out["workflow_employees"]:
            if not isinstance(row, dict):
                continue
            row["id"] = eid
            row.setdefault("label", str(emp_obj.get("label") or out.get("name") or eid))
            row.setdefault(
                "panel_title",
                row.get("label") or str(emp_obj.get("label") or out.get("name") or eid),
            )
            row["api_base_path"] = f"employees/{eid}"
    errs = _facade().validate_manifest_dict(out)
    return (out, errs)
