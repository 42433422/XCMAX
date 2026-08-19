# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_pipeline")


async def stage_generate_code(
    brief: str, manifest: _facade().Dict[str, _facade().Any], llm: _facade().LlmClient
) -> _facade().GeneratedCode:
    """S7: Generate runtime implementation code for the employee pack.

    For direct_python employees:
      - Known file formats (Word/Excel/CSV/PDF/PPT/TXT) use built-in runtime modules
      - Unknown formats use LLM to generate convert.py (vibe coding)

    For agent employees:
      - Use LLM to generate the employee run() implementation
    """
    from modstore_server.employee_asset_pipeline import (
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

    result = _facade().GeneratedCode()
    handlers = list(manifest.get("employee_config_v2", {}).get("actions", {}).get("handlers", []))
    pack_id = manifest.get("id", "unknown")
    employee_id = pack_id
    emp = manifest.get("employee", {}) or {}
    label = emp.get("label") or manifest.get("name") or employee_id
    stem = sanitize_employee_stem(employee_id)
    runtime_mod = _runtime_package_name(pack_id, employee_id)
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
        if any((fn(brief) for fn in _dp_triggers)):
            handlers = ["direct_python"]
            v2 = manifest.get("employee_config_v2", {})
            actions = v2.get("actions", {}) if isinstance(v2.get("actions"), dict) else {}
            actions["handlers"] = handlers
            actions.pop("agent", None)
            actions["direct_python"] = {"module": stem, "action": "convert"}
            result.warnings.append(
                "S4 选择了 agent handler，但 brief 匹配已知文件格式管线，已自动修正为 direct_python"
            )
    asset_manifest: _facade().Dict[str, _facade().Any] = {
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
        _has_word_signal = any((k in _brief_lower for k in ("word", "docx", ".doc", "文档")))
        _has_excel_signal = any((k in _brief_lower for k in ("excel", "xlsx", ".xls", "电子表格")))
        _has_pdf_signal = any((k in _brief_lower for k in ("pdf", ".pdf")))
        _has_ppt_signal = any((k in _brief_lower for k in ("ppt", "pptx", "演示")))
        _has_txt_signal = any((k in _brief_lower for k in ("txt", ".txt", "纯文本")))
        _has_csv_signal = any((k in _brief_lower for k in ("csv", ".csv", "逗号分隔")))
        _has_read_signal = any(
            (k in _brief_lower for k in ("读取", "提取", "解析", "read", "extract", "全量"))
        )
        _has_write_signal = any(
            (k in _brief_lower for k in ("生成", "写入", "write", "generate", "重建", "render"))
        )
        if _has_word_signal:
            if _has_write_signal and (not _has_read_signal):
                rule_spec = build_word_generate_rule_spec(brief)
            else:
                rule_spec = build_word_extract_rule_spec(brief)
        elif _has_pdf_signal:
            if _has_write_signal and (not _has_read_signal):
                rule_spec = build_pdf_generate_rule_spec(brief)
            else:
                rule_spec = build_pdf_read_rule_spec(brief)
        elif _has_excel_signal:
            if _has_write_signal and (not _has_read_signal):
                rule_spec = build_excel_generate_rule_spec(brief)
            else:
                rule_spec = build_excel_read_rule_spec(brief)
        elif _has_ppt_signal:
            if _has_write_signal and (not _has_read_signal):
                rule_spec = build_ppt_generate_rule_spec(brief)
            else:
                rule_spec = build_ppt_read_rule_spec(brief)
        elif _has_txt_signal:
            if _has_write_signal and (not _has_read_signal):
                rule_spec = build_txt_generate_rule_spec(brief)
            else:
                rule_spec = build_txt_read_rule_spec(brief)
        elif _has_csv_signal:
            if _has_write_signal and (not _has_read_signal):
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
            employee_id=employee_id, label=label, runtime_module=runtime_mod, rule_spec=rule_spec
        )
        result.code_source = "asset_pipeline_llm"
        try:
            from modstore_server.llm_chat_proxy import chat_dispatch
            from modstore_server.llm_key_resolver import platform_api_key, platform_base_url

            prov = "xiaomi"
            api_key = platform_api_key(prov)
            base_url = platform_base_url(prov)
            if api_key:
                system = _facade()._build_vibe_coding_prompt(runtime_kind, rule_spec)
                user_msg = _facade().json.dumps(
                    {"brief": brief, "rule_spec": rule_spec}, ensure_ascii=False
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
                emp_brief = f"员工 id: {employee_id}\n员工显示名: {label}\n职责摘要: {manifest.get('description', '')[:400]}\n能力: {', '.join(emp.get('capabilities', []))}\n\n请你基于以上画像实现 async def run(payload, ctx)。"
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
                        if not sec_err and (not beh_err):
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


async def refine_system_prompt(
    current_prompt: str, instruction: str, role_context: str, llm: _facade().LlmClient
) -> _facade().Tuple[_facade().Optional[_facade().Dict[str, str]], str]:
    """LLM-improve a system prompt and explain the changes."""
    ctx = f"角色背景：{role_context}\n\n当前 system prompt：\n{current_prompt}\n\n优化指令：{instruction}"
    content = await llm.chat(
        [
            {"role": "system", "content": _facade()._SYS_REFINE_PROMPT},
            {"role": "user", "content": ctx},
        ],
        max_tokens=2048,
    )
    (data, err) = _facade()._parse_json(content)
    if err:
        return (None, err)
    if not isinstance(data, dict):
        return (None, "须返回 JSON 对象")
    improved = str(data.get("improved_prompt") or "").strip()
    if not improved:
        return (None, "LLM 未返回优化后的 prompt")
    return (
        {
            "improved_prompt": improved,
            "diff_explanation": str(data.get("diff_explanation") or "")[:160],
        },
        "",
    )


async def run_pipeline(
    brief: str,
    *,
    llm: _facade().LlmClient,
    on_event: _facade().Callable[[_facade().Dict[str, _facade().Any]], _facade().Awaitable[None]],
    eligible_workflows: _facade().Optional[
        _facade().List[_facade().Dict[str, _facade().Any]]
    ] = None,
    generate_workflow_fallback: _facade().Optional[
        _facade().Callable[[], _facade().Awaitable[_facade().Dict[str, _facade().Any]]]
    ] = None,
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """Run the 6-stage pipeline pushing SSE events via on_event.

    Returns the assembled manifest dict on success, None on fatal failure.
    Stages 4 (skills) and 5 (pricing) are non-fatal: errors produce empty/null
    results but do not abort the pipeline.
    """

    async def _emit(event: str, stage: str, **kw: _facade().Any) -> None:
        await on_event({"event": event, "stage": stage, **kw})

    await _emit("stage_start", "parse_intent")
    (intent, err) = await _facade().stage_parse_intent(brief, llm)
    if err or intent is None:
        await _emit("stage_error", "parse_intent", error=err or "意图解析失败", retryable=True)
        return None
    await _emit("stage_done", "parse_intent", data=_facade().asdict(intent))
    await _emit("stage_start", "resolve_workflow")

    async def _on_wf_progress(msg: str) -> None:
        await _emit("stage_progress", "resolve_workflow", message=msg)

    (wf_choice, err) = await _facade().stage_resolve_workflow(
        intent,
        eligible_workflows or [],
        llm,
        generate_fallback=generate_workflow_fallback,
        on_progress=_on_wf_progress,
    )
    if err:
        await _emit("stage_error", "resolve_workflow", error=err, retryable=True)
        return None
    await _emit(
        "stage_done", "resolve_workflow", data=_facade().asdict(wf_choice) if wf_choice else None
    )
    await _emit("stage_start", "suggest_skills")
    (skills, err) = await _facade().stage_suggest_skills(intent, llm)
    if err:
        await _emit("stage_error", "suggest_skills", error=err, retryable=False)
        skills = []
    await _emit("stage_done", "suggest_skills", data=[_facade().asdict(s) for s in skills])
    await _emit("stage_start", "design_v2")
    (v2, err) = await _facade().stage_design_v2(intent, wf_choice, llm, suggested_skills=skills)
    if err or v2 is None:
        await _emit("stage_error", "design_v2", error=err or "配置设计失败", retryable=True)
        return None
    await _emit("stage_done", "design_v2", data=_facade().asdict(v2))
    await _emit("stage_start", "suggest_pricing")
    (pricing, err) = await _facade().stage_suggest_pricing(intent, v2, skills, llm)
    if err:
        await _emit("stage_error", "suggest_pricing", error=err, retryable=False)
        pricing = None
    await _emit(
        "stage_done", "suggest_pricing", data=_facade().asdict(pricing) if pricing else None
    )
    await _emit("stage_start", "assemble")
    (manifest, errs) = _facade().stage_assemble(intent, wf_choice, v2, skills, pricing)
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
    await _emit("stage_start", "generate_code")
    generated = await _facade().stage_generate_code(brief, manifest, llm)
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
    await _emit(
        "pipeline_done", "pipeline", manifest=manifest, generated_code=_facade().asdict(generated)
    )
    return manifest
