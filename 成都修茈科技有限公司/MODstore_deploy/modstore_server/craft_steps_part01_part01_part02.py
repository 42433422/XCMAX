# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.craft_steps")


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
        return {
            "validate_warnings": validate_warnings,
            "validate_errors": validate_errors,
        }
    if _pack.is_dir():
        from modman.manifest_util import read_manifest
        from modstore_server.mod_scaffold_runner import (
            employee_pack_consistency_warnings,
            mod_compileall_warnings,
        )

        mf, mf_err = read_manifest(_pack)
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
            except RECOVERABLE_ERRORS:
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
            cg_errs, cg_warns = validate_csv_generate_backend(_pack)
            if cg_errs:
                validate_errors.extend(cg_errs[:5])
            validate_warnings.extend(cg_warns[:5])
        elif excel_gen_runtime:
            eg_errs, eg_warns = validate_excel_generate_backend(_pack)
            if eg_errs:
                validate_errors.extend(eg_errs[:5])
            validate_warnings.extend(eg_warns[:5])
        elif excel_read_runtime:
            er_errs, er_warns = validate_excel_read_backend(_pack)
            if er_errs:
                validate_errors.extend(er_errs[:5])
            validate_warnings.extend(er_warns[:5])
        elif csv_read_runtime:
            cr_errs, cr_warns = validate_csv_read_backend(_pack)
            if cr_errs:
                validate_errors.extend(cr_errs[:5])
            validate_warnings.extend(cr_warns[:5])
        elif txt_gen_runtime:
            tg_errs, tg_warns = validate_txt_generate_backend(_pack)
            if tg_errs:
                validate_errors.extend(tg_errs[:5])
            validate_warnings.extend(tg_warns[:5])
        elif txt_read_runtime:
            tr_errs, tr_warns = validate_txt_read_backend(_pack)
            if tr_errs:
                validate_errors.extend(tr_errs[:5])
            validate_warnings.extend(tr_warns[:5])
        elif word_gen_runtime:
            wg_errs, wg_warns = validate_word_generate_backend(_pack)
            if wg_errs:
                validate_errors.extend(wg_errs[:5])
            validate_warnings.extend(wg_warns[:5])
        elif word_runtime:
            wx_errs, wx_warns = validate_word_extract_backend(_pack)
            validate_errors.extend(wx_errs)
            validate_warnings.extend(wx_warns)
            handlers_ok, handlers_msg = (True, "")
            try:
                from modstore_server.workbench_api import _employee_handlers_contract_ok

                handlers_ok, handlers_msg = _employee_handlers_contract_ok(_pack)
            except RECOVERABLE_ERRORS:
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
                    except RECOVERABLE_ERRORS:
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
    from modstore_server.mod_scaffold_runner import (
        attach_nl_workflow_to_employee_pack_dir,
    )
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
    from modstore_server.pack_registration_guards import (
        workflow_automation_block_reason,
    )

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
    *,
    workflow_id: int,
    brief: str,
    user_id: int,
    db: _facade().Any,
    **_kw: _facade().Any,
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
        return {
            "report": report,
            "ok": False,
            "status": "fail",
            "summary": report["summary"],
        }
    report = run_workflow_sandbox(wid, {}, mock_employees=True, validate_only=True, user_id=user_id)
    return {"report": report}
