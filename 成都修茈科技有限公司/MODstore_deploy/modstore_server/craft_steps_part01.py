# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.craft_steps")


async def _craft_spec(
    *,
    db: _facade().Any,
    user_id: int,
    payload: _facade().Any,
    brief: str,
    prov: _facade().Optional[str],
    mdl: _facade().Optional[str],
    routing_brief: _facade().Optional[str] = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.csv_tabular_runtime import (
        csv_generate_structured_spec,
        csv_read_structured_spec,
        is_csv_full_read,
        is_csv_generate,
    )
    from modstore_server.employee_brief_utils import extract_routing_brief
    from modstore_server.excel_tabular_runtime import (
        excel_generate_structured_spec,
        excel_read_structured_spec,
        is_excel_full_read,
        is_excel_generate,
    )
    from modstore_server.llm_chat_proxy import chat_dispatch
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        resolve_api_key,
        resolve_base_url,
    )
    from modstore_server.pdf_extract_runtime import (
        is_pdf_full_read,
        is_pdf_generate,
        pdf_generate_structured_spec,
        pdf_read_structured_spec,
    )
    from modstore_server.txt_extract_runtime import (
        is_txt_full_read,
        is_txt_generate,
        txt_generate_structured_spec,
        txt_read_structured_spec,
    )
    from modstore_server.word_extract_runtime import (
        is_word_full_extract,
        word_extract_structured_spec,
    )
    from modstore_server.word_generate_runtime import (
        is_word_generate,
        word_generate_structured_spec,
    )

    spec_warnings: _facade().List[str] = []
    brief_domain_hints: _facade().List[str] = []
    structured_requirement: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    rb = (routing_brief or "").strip()
    if not rb:
        rb = extract_routing_brief(
            payload if isinstance(payload, dict) else {"brief": brief}, fallback=brief
        )
    if not rb:
        spec_warnings.append(
            "需求描述为空，将使用默认配置生成员工；建议补充描述以获得更精准的员工能力"
        )
    elif len(rb) < 10:
        spec_warnings.append(
            f"需求描述仅 {len(rb)} 字，信息可能不足；建议补充员工的目标、输入输出和业务场景"
        )
    elif len(rb) > 2000:
        spec_warnings.append(f"需求描述 {len(rb)} 字较长，LLM 可能截断；建议精简到 500 字以内")
    _brief_lower = rb.lower() if rb else ""
    for _kw, _domain in _facade()._SPEC_DOMAIN_KEYWORDS.items():
        if _kw.lower() in _brief_lower and _domain not in brief_domain_hints:
            brief_domain_hints.append(_domain)
    if is_csv_generate(rb):
        structured_requirement = csv_generate_structured_spec(rb)
        if "数据处理" not in brief_domain_hints:
            brief_domain_hints.append("数据处理")
        spec_warnings.append(
            "CSV 生成：runtime_kind=csv_generate；handlers=direct_python；JSON 中介 → outputs/output.csv"
        )
    elif is_csv_full_read(rb):
        structured_requirement = csv_read_structured_spec(rb)
        if "数据处理" not in brief_domain_hints:
            brief_domain_hints.append("数据处理")
        spec_warnings.append(
            "CSV 全量读取：runtime_kind=csv_full_read；handlers=direct_python；输出 outputs/data.json"
        )
    elif is_excel_generate(rb):
        structured_requirement = excel_generate_structured_spec(rb)
        if "数据处理" not in brief_domain_hints:
            brief_domain_hints.append("数据处理")
        spec_warnings.append(
            "Excel 生成：runtime_kind=excel_generate；handlers=direct_python；JSON 中介 → outputs/output.xlsx"
        )
    elif is_excel_full_read(rb):
        structured_requirement = excel_read_structured_spec(rb)
        if "数据处理" not in brief_domain_hints:
            brief_domain_hints.append("数据处理")
        spec_warnings.append(
            "Excel 全量读取：runtime_kind=excel_full_read；handlers=direct_python；输出 outputs/workbook.json"
        )
    elif is_txt_generate(rb):
        structured_requirement = txt_generate_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "TXT 生成：runtime_kind=txt_generate；handlers=direct_python+agent；输出 document_parsed.json + generated_document.txt"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join((str(c) for c in _caps[:4]))}")
    elif is_txt_full_read(rb):
        structured_requirement = txt_read_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "TXT 全量读取：runtime_kind=txt_full_read；handlers=direct_python；输出 document_full.txt + document_meta.json"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join((str(c) for c in _caps[:4]))}")
    elif is_pdf_generate(rb):
        structured_requirement = pdf_generate_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "PDF 生成：runtime_kind=pdf_generate；handlers=direct_python+agent；JSON 中介 → outputs/generated_document.pdf"
        )
    elif is_pdf_full_read(rb):
        structured_requirement = pdf_read_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "PDF 全量读取：runtime_kind=pdf_full_read；handlers=direct_python；原生文字 + 图片分类 + VLM sidecar"
        )
    elif is_word_full_extract(rb):
        structured_requirement = word_extract_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "Word 全量提取：runtime_kind=word_full_extract；handlers=direct_python；输出 document_full.json + document_full.txt + images/"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join((str(c) for c in _caps[:4]))}")
    elif is_word_generate(rb):
        structured_requirement = word_generate_structured_spec(rb)
        if "文档/知识" not in brief_domain_hints:
            brief_domain_hints.append("文档/知识")
        spec_warnings.append(
            "Word 生成：runtime_kind=word_generate；handlers=direct_python（+可选 agent）；JSON 中介 + 可选 template.docx → generated_document.docx"
        )
        _caps = structured_requirement.get("suggested_capabilities")
        if isinstance(_caps, list) and _caps:
            spec_warnings.append(f"建议能力：{'、'.join((str(c) for c in _caps[:4]))}")
    elif rb and len(rb) >= 10 and prov and mdl:
        from modstore_server.employee_pipeline_routing import is_ambiguous_employee_brief

        if is_ambiguous_employee_brief(rb):
            try:
                (_req_api_key, _) = resolve_api_key(db, user_id, prov)
                _req_prompt = f'请从以下用户需求中提取结构化信息，只输出 JSON，不要 markdown 围栏：\n{{"domain":"业务领域","goal":"员工要达成的目标","input":"员工接收什么输入","output":"员工输出什么","constraints":["约束1","约束2"],"suggested_capabilities":["cap1","cap2"],"suggested_handlers":["llm_md"]}}\n\n用户需求：{rb}'
                _req_result = await chat_dispatch(
                    prov,
                    api_key=_req_api_key,
                    base_url=(
                        resolve_base_url(db, user_id, prov)
                        if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
                        else None
                    ),
                    model=mdl,
                    messages=[{"role": "user", "content": _req_prompt}],
                    max_tokens=1500,
                )
                if _req_result.get("ok"):
                    _req_raw = _facade().re.sub(
                        "^```(?:json)?\\s*",
                        "",
                        (_req_result.get("content") or "").strip(),
                        flags=_facade().re.I,
                    )
                    _req_raw = _facade().re.sub("\\s*```\\s*$", "", _req_raw).strip()
                    _parsed_req = _facade().json.loads(_req_raw)
                    if isinstance(_parsed_req, dict):
                        structured_requirement = _parsed_req
                        _extracted_domain = str(_parsed_req.get("domain") or "").strip()
                        if _extracted_domain and _extracted_domain not in brief_domain_hints:
                            brief_domain_hints.append(_extracted_domain)
                        _extracted_caps = _parsed_req.get("suggested_capabilities")
                        if isinstance(_extracted_caps, list) and _extracted_caps:
                            spec_warnings.append(
                                f"LLM 建议能力：{'、'.join((str(c) for c in _extracted_caps[:4]))}"
                            )
            except Exception:
                _facade().logger.debug(
                    "LLM structured requirement extraction failed", exc_info=True
                )
    if not structured_requirement and rb:
        bl = rb.lower()
        structured_requirement = {
            "domain": brief_domain_hints[0] if brief_domain_hints else "通用",
            "goal": rb.strip().splitlines()[0][:200],
            "input": (
                "Word/文档" if any((k in bl for k in ("word", "docx", "文档"))) else "用户输入"
            ),
            "output": "txt 文本" if "txt" in bl or "文本" in bl else "结构化结果",
            "constraints": [],
            "suggested_handlers": ["llm_md"],
        }
    return {
        "spec_warnings": spec_warnings,
        "brief_domain_hints": brief_domain_hints,
        "structured_requirement": structured_requirement,
        "routing_brief": rb,
    }


async def _craft_employee_plan(
    *,
    db: _facade().Any,
    user_id: int,
    payload: _facade().Any,
    prov: _facade().Optional[str],
    mdl: _facade().Optional[str],
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.workbench_api import _build_employee_orchestration_plan

    employee_plan = await _build_employee_orchestration_plan(
        db=db, user_id=user_id, payload=payload, provider=prov, model=mdl
    )
    return {"employee_plan": employee_plan}


async def _craft_generate(
    *,
    db: _facade().Any,
    user: _facade().Any,
    session_id: str,
    brief: str,
    raw_files: _facade().Any,
    replace: bool,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    use_word_extract: bool = False,
    payload: _facade().Any = None,
    employee_plan: _facade().Any = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.artifact_generator_blueprint import artifact_generator_preflight
    from modstore_server.employee_asset_pipeline import (
        run_asset_employee_scaffold_async,
        run_word_extract_employee_scaffold_async,
    )

    _payload = dict(payload) if isinstance(payload, dict) else {}
    if isinstance(employee_plan, dict) and employee_plan:
        _payload.setdefault("employee_plan", employee_plan)
    _bp = artifact_generator_preflight(payload=_payload, brief=brief)
    if _bp.get("status") == "error":
        return {
            "res": {
                "ok": False,
                "status": "error",
                "error": _bp.get("error"),
                "generation_mode": _bp.get("generation_mode"),
                "artifact_paths": [],
                "validation_result": _bp.get("validation_result"),
                "warnings": [],
                "missing_fields": _bp.get("missing_fields") or [],
            }
        }
    _scaffold_kw = dict(
        session_id=session_id,
        brief=brief,
        raw_files=raw_files,
        replace=replace,
        provider=provider,
        model=model,
        publish_to_catalog=False,
        force_llm_codegen=True,
        payload=_payload,
    )
    if use_word_extract:
        res = await run_word_extract_employee_scaffold_async(db=db, user=user, **_scaffold_kw)
    else:
        res = await run_asset_employee_scaffold_async(db=db, user=user, **_scaffold_kw)
    return {"res": res}


async def _craft_validate(
    *,
    res: _facade().Dict[str, _facade().Any],
    brief: str = "",
    pack_dir: _facade().Any = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    validate_warnings: _facade().List[str] = []
    validate_errors: _facade().List[str] = []
    if isinstance(res.get("validate_warnings"), list):
        validate_warnings.extend((str(x) for x in res["validate_warnings"] if x))
    if isinstance(res.get("validate_errors"), list):
        validate_errors.extend((str(x) for x in res["validate_errors"] if x))
    from modstore_server.vibecoding_convert_loop import is_llm_codegen_source

    _rt = res.get("runtime_generation") if isinstance(res.get("runtime_generation"), dict) else {}
    if _rt and (not is_llm_codegen_source(_rt)):
        validate_errors.append(f"convert 非 LLM 生成：source={_rt.get('source')}")
    _ds = res.get("domain_smoke") if isinstance(res.get("domain_smoke"), dict) else {}
    if _ds.get("ok") is False:
        validate_errors.append(f"领域冒烟失败：{_ds.get('error') or 'failed'}"[:200])
    _gc = res.get("golden_comparison") if isinstance(res.get("golden_comparison"), dict) else {}
    if _gc.get("golden_pack_id") and (not _gc.get("passed")):
        validate_errors.append(
            f"黄金对比未达标：parity={_gc.get('parity_score')} diffs={len(_gc.get('diff_items') or [])}"
        )
    _pack = _facade().Path(str(pack_dir or res.get("path") or ""))
    if not res.get("ok") and (not _pack.is_dir()):
        validate_errors.append(str(res.get("error") or "生成产物无效或缺少包目录"))
        return {"validate_warnings": validate_warnings, "validate_errors": validate_errors}
    if _pack.is_dir():
        from modman.manifest_util import read_manifest
        from modstore_server.mod_scaffold_runner import (
            employee_pack_consistency_warnings,
            mod_compileall_warnings,
        )

        (mf, mf_err) = read_manifest(_pack)
        if mf_err:
            validate_errors.append(f"manifest 不可读：{mf_err}")
        elif isinstance(mf, dict):
            if not str(mf.get("id") or "").strip():
                validate_errors.append("manifest 缺少 id")
            ec2 = mf.get("employee_config_v2")
            if isinstance(ec2, dict):
                actions = ec2.get("actions")
                if isinstance(actions, dict):
                    handlers = actions.get("handlers")
                    if not isinstance(handlers, list) or not handlers:
                        validate_warnings.append("employee_config_v2.actions.handlers 为空")
            emp = mf.get("employee")
            if not isinstance(emp, dict) or not str(emp.get("id") or "").strip():
                validate_warnings.append("manifest.employee.id 缺失")
        py_warns = mod_compileall_warnings(_pack)
        if py_warns:
            validate_errors.extend((f"Python 编译：{w}" for w in py_warns[:8]))
        cons_warns = employee_pack_consistency_warnings(_pack)
        if cons_warns:
            validate_errors.extend((f"一致性：{w}" for w in cons_warns[:5]))
        from modstore_server.csv_tabular_runtime import (
            is_csv_full_read,
            is_csv_generate,
            validate_csv_generate_backend,
            validate_csv_read_backend,
        )
        from modstore_server.employee_brief_utils import extract_routing_brief
        from modstore_server.excel_tabular_runtime import (
            is_excel_full_read,
            is_excel_generate,
            validate_excel_generate_backend,
            validate_excel_read_backend,
        )
        from modstore_server.txt_extract_runtime import (
            is_txt_full_read,
            is_txt_generate,
            validate_txt_generate_backend,
            validate_txt_read_backend,
        )
        from modstore_server.word_extract_runtime import (
            is_word_full_extract,
            validate_word_extract_backend,
        )
        from modstore_server.word_generate_runtime import (
            is_word_generate,
            validate_word_generate_backend,
        )

        rule_spec_path = _pack / "rule_spec.json"
        rule_kind = ""
        if rule_spec_path.is_file():
            try:
                import json as _json

                rs = _json.loads(rule_spec_path.read_text(encoding="utf-8"))
                if isinstance(rs, dict):
                    rule_kind = str(rs.get("runtime_kind") or "")
            except Exception:
                pass
        routing_brief = extract_routing_brief({"brief": brief}, fallback=brief)
        bl = routing_brief.lower()
        csv_gen_runtime = rule_kind == "csv_generate" or is_csv_generate(routing_brief)
        csv_read_runtime = rule_kind == "csv_full_read" or is_csv_full_read(routing_brief)
        excel_gen_runtime = rule_kind == "excel_generate" or is_excel_generate(routing_brief)
        excel_read_runtime = rule_kind == "excel_full_read" or is_excel_full_read(routing_brief)
        word_runtime = rule_kind == "word_full_extract" or is_word_full_extract(routing_brief)
        word_gen_runtime = rule_kind == "word_generate" or is_word_generate(routing_brief)
        txt_read_runtime = rule_kind == "txt_full_read" or is_txt_full_read(routing_brief)
        txt_gen_runtime = rule_kind == "txt_generate" or is_txt_generate(routing_brief)
        if csv_gen_runtime:
            (cg_errs, cg_warns) = validate_csv_generate_backend(_pack)
            if cg_errs:
                validate_errors.extend(cg_errs[:5])
            validate_warnings.extend(cg_warns[:5])
        elif excel_gen_runtime:
            (eg_errs, eg_warns) = validate_excel_generate_backend(_pack)
            if eg_errs:
                validate_errors.extend(eg_errs[:5])
            validate_warnings.extend(eg_warns[:5])
        elif excel_read_runtime:
            (er_errs, er_warns) = validate_excel_read_backend(_pack)
            if er_errs:
                validate_errors.extend(er_errs[:5])
            validate_warnings.extend(er_warns[:5])
        elif csv_read_runtime:
            (cr_errs, cr_warns) = validate_csv_read_backend(_pack)
            if cr_errs:
                validate_errors.extend(cr_errs[:5])
            validate_warnings.extend(cr_warns[:5])
        elif txt_gen_runtime:
            (tg_errs, tg_warns) = validate_txt_generate_backend(_pack)
            if tg_errs:
                validate_errors.extend(tg_errs[:5])
            validate_warnings.extend(tg_warns[:5])
        elif txt_read_runtime:
            (tr_errs, tr_warns) = validate_txt_read_backend(_pack)
            if tr_errs:
                validate_errors.extend(tr_errs[:5])
            validate_warnings.extend(tr_warns[:5])
        elif word_gen_runtime:
            (wg_errs, wg_warns) = validate_word_generate_backend(_pack)
            if wg_errs:
                validate_errors.extend(wg_errs[:5])
            validate_warnings.extend(wg_warns[:5])
        elif word_runtime:
            (wx_errs, wx_warns) = validate_word_extract_backend(_pack)
            validate_errors.extend(wx_errs)
            validate_warnings.extend(wx_warns)
            (handlers_ok, handlers_msg) = (True, "")
            try:
                from modstore_server.workbench_api import _employee_handlers_contract_ok

                (handlers_ok, handlers_msg) = _employee_handlers_contract_ok(_pack)
            except Exception:
                pass
            if not handlers_ok and handlers_msg:
                validate_errors.append(handlers_msg)
        elif any((k in bl for k in ("word", "docx", ".doc", "txt", "文本", "文档"))):
            backend = _pack / "backend"
            py_blob = ""
            if backend.is_dir():
                for py_path in backend.rglob("*.py"):
                    try:
                        py_blob += py_path.read_text(encoding="utf-8", errors="ignore").lower()
                    except Exception:
                        pass
            if not any(
                (tok in py_blob for tok in ("docx", "document", "python-docx", "word", "zipfile"))
            ):
                validate_warnings.append(
                    "Word/文档提取类任务：backend 中未发现 docx/文档解析相关实现，请确认生成逻辑"
                )
    return {"validate_warnings": validate_warnings, "validate_errors": validate_errors}


async def _craft_script_workflow(
    *,
    db: _facade().Any,
    user_id: int,
    session_id: str,
    brief: str,
    files: _facade().Any,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    system_hint: _facade().Optional[str] = None,
    payload: _facade().Any = None,
    status_hook: _facade().Optional[
        _facade().Callable[..., _facade().Coroutine[_facade().Any, _facade().Any, _facade().Any]]
    ] = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.workbench_api import _commit_script_workflow_from_result
    from modstore_server.workbench_script_runner import run_script_agent_job

    script_result = await run_script_agent_job(
        db=db,
        user_id=user_id,
        session_id=session_id,
        brief=brief,
        files=files,
        provider=provider,
        model=model,
        system_hint=system_hint,
        status_hook=status_hook,
    )
    script_wf = None
    if script_result.get("ok"):
        script_wf = _commit_script_workflow_from_result(
            db=db,
            user_id=user_id,
            session_id=session_id,
            payload=payload,
            files=files,
            result=script_result,
        )
        if script_wf is None:
            _facade().logger.warning(
                "craft_script_workflow: ok=True but commit returned None — script_len=%d errors=%s session=%s",
                len(str(script_result.get("script") or "")),
                script_result.get("errors"),
                session_id,
            )
    else:
        _facade().logger.warning(
            "craft_script_workflow: ok=False — errors=%s session=%s",
            script_result.get("errors"),
            session_id,
        )
    return {"script_result": script_result, "script_wf": script_wf}


async def _craft_embed_script(
    *,
    pack_dir: _facade().Any,
    script_wf: _facade().Any,
    brief: str,
    db: _facade().Any,
    published_to_catalog: bool = False,
    user: _facade().Any = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.workbench_api import (
        _embed_script_workflow_in_employee_pack,
        _refresh_employee_pack_catalog_zip,
    )

    script_attachment = _embed_script_workflow_in_employee_pack(
        pack_dir=pack_dir, script_workflow=script_wf, brief=brief, db=db
    )
    saved_package = None
    if published_to_catalog and user:
        saved_package = _refresh_employee_pack_catalog_zip(db=db, user=user, pack_dir=pack_dir)
    return {"script_attachment": script_attachment, "saved_package": saved_package}


async def _craft_workflow(
    *,
    db: _facade().Any,
    user: _facade().Any,
    pack_dir: _facade().Any,
    brief: str,
    workflow_name: str,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    published_to_catalog: bool = False,
    status_hook: _facade().Optional[
        _facade().Callable[..., _facade().Coroutine[_facade().Any, _facade().Any, _facade().Any]]
    ] = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.mod_scaffold_runner import attach_nl_workflow_to_employee_pack_dir
    from modstore_server.workbench_api import _refresh_employee_pack_catalog_zip

    wf_attach = await attach_nl_workflow_to_employee_pack_dir(
        db=db,
        user=user,
        pack_dir=pack_dir,
        brief=brief,
        workflow_name=workflow_name,
        provider=provider,
        model=model,
        status_hook=status_hook,
    )
    saved_package = None
    if published_to_catalog:
        saved_package = _refresh_employee_pack_catalog_zip(db=db, user=user, pack_dir=pack_dir)
    return {"wf_attach": wf_attach, "saved_package": saved_package}


async def _craft_register_pack(
    *,
    db: _facade().Any,
    user: _facade().Any,
    mod_dir: _facade().Any,
    workflow_results: _facade().Any = None,
    wf_attach: _facade().Any = None,
    status_hook: _facade().Optional[
        _facade().Callable[..., _facade().Coroutine[_facade().Any, _facade().Any, _facade().Any]]
    ] = None,
    industry: str = "通用",
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.mod_scaffold_runner import register_mod_employee_packs_async
    from modstore_server.pack_registration_guards import workflow_automation_block_reason

    _wf_results = workflow_results if isinstance(workflow_results, list) else []
    _wf_attach = wf_attach if isinstance(wf_attach, dict) else None
    block = workflow_automation_block_reason(
        _wf_results, wf_attach=_wf_attach, require_workflow_automation=True
    )
    if block:
        return {
            "ok": False,
            "status": "fail",
            "summary": block[:400],
            "error": block,
            "rejected_upstream": "workflow-automator",
            "_emp_reg_result": {
                "ok": False,
                "registered": [],
                "errors": [{"stage": "upstream", "error": block}],
            },
        }
    _emp_reg_result = await register_mod_employee_packs_async(
        db=db,
        user=user,
        mod_dir=mod_dir,
        workflow_results=_wf_results,
        status_hook=status_hook,
        industry=industry,
        wf_attach=_wf_attach,
    )
    reg_ok = bool(_emp_reg_result.get("ok")) and (not (_emp_reg_result.get("errors") or []))
    return {
        "ok": reg_ok,
        "status": "ok" if reg_ok else "fail",
        "summary": (
            f"已登记 {len(_emp_reg_result.get('registered') or [])} 个员工包"
            if reg_ok
            else (_emp_reg_result.get("errors") or [{}])[0].get("error", "登记失败")[:400]
        ),
        "_emp_reg_result": _emp_reg_result,
    }


async def _craft_workflow_sandbox(
    *, workflow_id: int, brief: str, user_id: int, db: _facade().Any, **_kw: _facade().Any
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.craft_failure_signals import (
        emit_craft_step_failure,
        invalid_workflow_sandbox_report,
    )
    from modstore_server.workflow_engine import run_workflow_sandbox

    try:
        wid = int(workflow_id)
    except (TypeError, ValueError):
        wid = 0
    if wid <= 0:
        report = invalid_workflow_sandbox_report(workflow_id)
        emit_craft_step_failure(
            step_id="workflow_sandbox",
            error=str(report["errors"][0]),
            user_id=int(user_id or 0),
            extra={"workflow_id": workflow_id, "sandbox_report": report},
        )
        return {"report": report, "ok": False, "status": "fail", "summary": report["summary"]}
    report = run_workflow_sandbox(wid, {}, mock_employees=True, validate_only=True, user_id=user_id)
    return {"report": report}


async def _craft_mod_sandbox(
    *,
    pack_dir: _facade().Any,
    wf_attach: _facade().Any = None,
    user_id: int = 0,
    db: _facade().Any = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.mod_scaffold_runner import (
        employee_pack_consistency_warnings,
        run_employee_pack_code_validation_report,
    )

    mod_checks: _facade().List[_facade().Dict[str, _facade().Any]] = []
    _pack = _facade().Path(str(pack_dir)) if not isinstance(pack_dir, _facade().Path) else pack_dir
    validation_report = await run_employee_pack_code_validation_report(
        _pack, db=db, xcemp_timeout_seconds=20.0
    )
    mv = (
        validation_report.get("manifest_validation")
        if isinstance(validation_report.get("manifest_validation"), dict)
        else {}
    )
    pc = (
        validation_report.get("python_compile")
        if isinstance(validation_report.get("python_compile"), dict)
        else {}
    )
    cc = (
        validation_report.get("consistency_check")
        if isinstance(validation_report.get("consistency_check"), dict)
        else {}
    )
    xv = (
        validation_report.get("xcemp_validation")
        if isinstance(validation_report.get("xcemp_validation"), dict)
        else {}
    )
    mod_checks.append(
        {
            "id": "manifest_validation",
            "ok": mv.get("status") == "ok",
            "message": "；".join(mv.get("errors") or [])[:800] or "manifest 校验通过",
        }
    )
    mod_checks.append(
        {
            "id": "python_compile",
            "ok": pc.get("status") in ("ok", "skipped"),
            "message": "；".join(pc.get("errors") or [])[:800]
            or (
                "；".join(pc.get("warnings") or [])[:400]
                if pc.get("warnings")
                else "Python 编译通过"
            ),
        }
    )
    _cc_msg_parts: _facade().List[str] = []
    if cc.get("missing_depends"):
        _cc_msg_parts.append("depends_on 未注册: " + ", ".join(cc["missing_depends"][:6]))
    if cc.get("missing_skills"):
        _cc_msg_parts.append("skills 缺失: " + ", ".join(cc["missing_skills"][:6]))
    if cc.get("warnings"):
        _cc_msg_parts.append("；".join((str(w) for w in cc["warnings"][:4]))[:400])
    mod_checks.append(
        {
            "id": "consistency_check",
            "ok": cc.get("status") in ("ok", "skipped"),
            "message": "；".join(_cc_msg_parts)[:1200] if _cc_msg_parts else "一致性校验通过",
        }
    )
    mod_checks.append(
        {
            "id": "xcemp_validation",
            "ok": xv.get("status") in ("ok", "skipped"),
            "message": "；".join(xv.get("errors") or [])[:800] or "xcemp validate 通过",
        }
    )
    if _pack.is_dir():
        cons_warns = employee_pack_consistency_warnings(_pack)
        if cons_warns and cc.get("status") == "ok":
            mod_checks.append(
                {
                    "id": "employee_pack_consistency",
                    "ok": False,
                    "message": "；".join(cons_warns)[:1200],
                }
            )
        try:
            from modstore_server.workbench_api import _check_vibe_coding_capability

            vibe_checks = _check_vibe_coding_capability(_pack, wf_attach or {})
            mod_checks.extend(vibe_checks)
        except Exception as vibe_exc:
            _facade().logger.warning("vibe-coding capability check failed: %s", vibe_exc)
            mod_checks.append(
                {"id": "vibe_check", "ok": False, "message": f"vibe-coding 检查异常: {vibe_exc!s}"}
            )
    core_ok = validation_report.get("status") == "ok"
    emp_mod_sandbox = {
        "ok": core_ok and all((c.get("ok") for c in mod_checks if c.get("id") != "vibe_check")),
        "checks": mod_checks,
        "validation_report": validation_report,
        "note": "员工包四阶段校验（manifest / Python / 一致性 / xcemp）",
    }
    if xv.get("escalate_to_human"):
        from modstore_server.craft_failure_signals import emit_craft_step_failure

        _xv_errs = xv.get("errors") if isinstance(xv.get("errors"), list) else []
        _xv_err = str(
            xv.get("timeout_log") or (_xv_errs[0] if _xv_errs else "xcemp validate 超时")
        )[:500]
        emit_craft_step_failure(
            step_id="mod_sandbox",
            error=_xv_err,
            employee_id="code-validator",
            user_id=int(user_id or 0),
            extra={
                "escalate_to_human": True,
                "package_hash": xv.get("package_hash"),
                "validation_report": validation_report,
            },
        )
    _all_pass = emp_mod_sandbox["ok"]
    _vibe_gaps = [c for c in mod_checks if not c.get("ok") and "vibe" in str(c.get("id") or "")]
    mod_sb_msg = str(validation_report.get("summary") or "")
    if _all_pass:
        mod_sb_msg = mod_sb_msg or "包体四阶段校验通过"
    elif _vibe_gaps and core_ok:
        mod_sb_msg = (
            mod_sb_msg
            + "；vibe-coding 能力存在缺口："
            + "；".join((c.get("message", "") for c in _vibe_gaps))
        )[:480]
    elif not mod_sb_msg:
        mod_sb_msg = "包体校验未通过，见 validation_report"
    return {
        "emp_mod_sandbox": emp_mod_sandbox,
        "mod_sb_msg": mod_sb_msg,
        "report": validation_report,
    }
