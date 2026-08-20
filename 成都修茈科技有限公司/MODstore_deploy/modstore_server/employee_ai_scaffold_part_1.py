# mypy: disable-error-code="attr-defined, index, no-any-return, operator, union-attr, valid-type"
"""Employee scaffold helpers split by generation responsibility."""

from __future__ import annotations

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
