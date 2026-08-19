# ruff: noqa
"""Workbench employee pipeline branch."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_workbench_employee_pipeline(
    sid, user_id, payload, intent, brief, prov, mdl, replace, db, user
):
    et = str(payload.get("employee_target") or "pack_only").strip().lower()
    embed_script_workflow = bool(payload.get("embed_script_workflow", True))
    wf_name = (payload.get("employee_workflow_name") or "").strip() or None
    fhd_base = (
        (payload.get("fhd_base_url") or "").strip()
        or (_facade().os.environ.get("FHD_BASE_URL") or "").strip()
        or None
    )
    employee_files = payload.get("_files") or []
    from modstore_server.employee_brief_utils import (
        extract_routing_brief,
        is_contract_doc_review_brief,
    )
    from modstore_server.employee_pipeline_routing import classify_employee_pipeline

    _routing_brief = extract_routing_brief(payload, fallback=brief)
    _emp_brief_lower = (_routing_brief or brief or "").lower()
    _needs_llm_reasoning = is_contract_doc_review_brief(_routing_brief) or any(
        (
            k in _emp_brief_lower
            for k in (
                "合同",
                "法务",
                "合规",
                "审核",
                "条款",
                "法律",
                "评审",
                "分析",
                "建议",
                "contract",
                "legal",
                "compliance",
                "review",
                "analyze",
            )
        )
    )
    (
        _pipeline_label,
        _use_word_extract_pipeline,
        _use_txt_pipeline,
        _use_pdf_pipeline,
        _use_asset_pipeline,
    ) = classify_employee_pipeline(
        _routing_brief, employee_files=employee_files, needs_llm_reasoning=_needs_llm_reasoning
    )
    _uploaded_docx = _facade()._contains_uploaded_docx(employee_files)
    from modstore_server.employee_pipeline_routing import (
        resolve_employee_runtime_kind,
        validate_runtime_pipeline_consistency,
    )

    _expected_runtime_kind = resolve_employee_runtime_kind(_routing_brief)
    (_pipe_ok, _pipe_err) = validate_runtime_pipeline_consistency(
        routing_brief=_routing_brief,
        pipeline_label=_pipeline_label,
        rule_spec={"runtime_kind": _expected_runtime_kind},
    )
    if not _pipe_ok:
        await _facade()._fail_session(sid, "spec", _pipe_err[:1000])
        return
    _resume_cp = None
    async with _facade()._SESSION_LOCK:
        _sess_rc = _facade().WORKBENCH_SESSIONS.get(sid)
        if _sess_rc:
            _resume_cp = _sess_rc.get("_resume_checkpoint")
            if _resume_cp:
                del _sess_rc["_resume_checkpoint"]
                _facade()._persist_workbench_session_unlocked(sid)
    if _resume_cp and _resume_cp.get("res") and _resume_cp.get("pack_dir"):
        res = _resume_cp["res"]
        pack_dir = _facade().Path(_resume_cp["pack_dir"])
        employee_plan = _resume_cp.get("employee_plan")
        script_wf = _resume_cp.get("script_wf")
        script_attachment = _resume_cp.get("script_attachment") or {}
        wf_attach = _resume_cp.get("wf_attach") or {}
        saved_package = _resume_cp.get("saved_package") or {}
        published_to_catalog = _resume_cp.get("published_to_catalog", False)
        et = _resume_cp.get("employee_target") or et
        embed_script_workflow = _resume_cp.get("embed_script_workflow", embed_script_workflow)
        wf_name = _resume_cp.get("wf_name") or wf_name
        fhd_base = _resume_cp.get("fhd_base") or fhd_base
        _resume_from = _resume_cp.get("failed_step", "embed_script")
        _facade()._LOG.info(
            "pipeline resume session=%s from step=%s pack_dir=%s", sid, _resume_from, pack_dir
        )
    else:
        _resume_from = None
    _emp_current_step = "employee_plan"
    _EMP_STEP_ORDER = [
        "spec",
        "employee_plan",
        "generate",
        "validate",
        "script_workflow",
        "embed_script",
        "workflow",
        "register_pack",
        "workflow_sandbox",
        "mod_sandbox",
        "standalone_smoke",
        "host_check",
        "six_dim_gate",
        "complete",
    ]

    def _should_skip(step_id: str) -> bool:
        if not _resume_from or _resume_from not in _EMP_STEP_ORDER:
            return False
        return _EMP_STEP_ORDER.index(step_id) < _EMP_STEP_ORDER.index(_resume_from)

    try:
        _wf_sandbox_biz_ok: _facade().Optional[bool] = None
        _standalone_smoke_ok = True
        if _should_skip("employee_plan"):
            await _facade()._set_step(sid, "employee_plan", "done", "已完成（重试复用）")
        else:
            await _facade()._set_step(
                sid, "employee_plan", "running", "正在拆分员工、脚本工作流与 Skill 组职责"
            )
        _ep_result = await _facade()._dispatch_craft_step(
            "employee_plan", db=db, user_id=user_id, payload=payload, prov=prov, mdl=mdl
        )
        employee_plan = (
            _ep_result["employee_plan"]
            if _ep_result
            else await _facade()._build_employee_orchestration_plan(
                db, user_id, payload=payload, provider=prov, model=mdl
            )
        )
        if _pipeline_label == "txt_full_read":
            _pipeline_label_display = "TXT 全量读取 direct_python"
        elif _pipeline_label == "txt_generate":
            _pipeline_label_display = "TXT 生成 direct_python + 可选 agent"
        elif _pipeline_label == "pdf_full_read":
            _pipeline_label_display = "PDF 全量读取 direct_python（原生文字 + 图片 VLM）"
        elif _pipeline_label == "pdf_generate":
            _pipeline_label_display = "PDF 生成 direct_python + JSON 中介 + 可选 agent"
        elif _pipeline_label == "word_full_extract":
            _pipeline_label_display = "Word 全量提取 direct_python"
        elif _pipeline_label == "asset":
            _pipeline_label_display = (
                "LLM 驱动文档审核（agent）"
                if _needs_llm_reasoning and _uploaded_docx
                else "资产驱动 direct_python"
            )
        else:
            _pipeline_label_display = "LLM 通用脚手架"
        _plan_display_name = str(employee_plan.get("employee_name") or "员工").strip() or "员工"
        await _facade()._set_step(
            sid,
            "employee_plan",
            "done",
            f"已规划：{_plan_display_name} / {_pipeline_label_display}",
        )
        from modstore_server.employee_brief_utils import compact_routing_brief

        if _use_word_extract_pipeline:
            employee_brief = compact_routing_brief(_routing_brief, max_len=500) or _routing_brief
        else:
            employee_brief = (
                str(employee_plan.get("employee_brief") or _routing_brief or brief).strip() or brief
            )
        script_brief = str(employee_plan.get("script_brief") or brief).strip() or brief
        script_hint = str(employee_plan.get("script_runtime_notes") or "").strip()
        workflow_brief = str(employee_plan.get("workflow_brief") or brief).strip() or brief
        planned_workflow_name = str(employee_plan.get("workflow_name") or "").strip() or None
        planned_script_name = str(employee_plan.get("script_workflow_name") or "").strip() or None
        if _should_skip("generate"):
            await _facade()._set_step(sid, "generate", "done", "已完成（重试复用）")
        else:
            _emp_current_step = "generate"
            _gen_running_msg = (
                "正在解析上传资产并生成员工包"
                if _use_asset_pipeline
                else (
                    "正在生成 LLM 驱动文档审核员工包"
                    if _needs_llm_reasoning and _uploaded_docx
                    else None
                )
            )
            await _facade()._set_step(sid, "generate", "running", _gen_running_msg)
            _plan_payload = dict(payload) if isinstance(payload, dict) else {}
            if isinstance(employee_plan, dict) and employee_plan:
                _plan_payload["employee_plan"] = employee_plan
            _scaffold_kw = dict(
                session_id=sid,
                brief=employee_brief,
                raw_files=employee_files,
                replace=replace,
                provider=prov,
                model=mdl,
                publish_to_catalog=False,
                force_llm_codegen=True,
                payload=_plan_payload or None,
            )
            if _use_word_extract_pipeline:
                from modstore_server.employee_asset_pipeline import (
                    run_word_extract_employee_scaffold_async,
                )

                _gen_result = await _facade()._dispatch_craft_step(
                    "generate",
                    db=db,
                    user=user,
                    session_id=sid,
                    brief=employee_brief,
                    raw_files=employee_files,
                    replace=replace,
                    provider=prov,
                    model=mdl,
                    use_word_extract=True,
                    payload=payload,
                )
                res = (
                    _gen_result["res"]
                    if _gen_result
                    else await run_word_extract_employee_scaffold_async(db, user, **_scaffold_kw)
                )
            elif _use_asset_pipeline:
                from modstore_server.employee_asset_pipeline import (
                    run_asset_employee_scaffold_async,
                )

                _gen_result = await _facade()._dispatch_craft_step(
                    "generate",
                    db=db,
                    user=user,
                    session_id=sid,
                    brief=employee_brief,
                    raw_files=employee_files,
                    replace=replace,
                    provider=prov,
                    model=mdl,
                    payload=payload,
                )
                res = (
                    _gen_result["res"]
                    if _gen_result
                    else await run_asset_employee_scaffold_async(db, user, **_scaffold_kw)
                )
            elif _needs_llm_reasoning and _uploaded_docx:
                from modstore_server.employee_asset_pipeline import (
                    run_asset_employee_scaffold_async,
                )

                _gen_result = await _facade()._dispatch_craft_step(
                    "generate",
                    db=db,
                    user=user,
                    session_id=sid,
                    brief=employee_brief,
                    raw_files=employee_files,
                    replace=replace,
                    provider=prov,
                    model=mdl,
                    payload=payload,
                )
                res = (
                    _gen_result["res"]
                    if _gen_result
                    else await run_asset_employee_scaffold_async(db, user, **_scaffold_kw)
                )
            else:
                res = await _facade().run_employee_ai_scaffold_async(
                    db,
                    user,
                    brief=employee_brief,
                    replace=replace,
                    provider=prov,
                    model=mdl,
                    publish_to_catalog=False,
                )
            if not res.get("ok"):
                warns = (
                    res.get("validate_warnings")
                    if isinstance(res.get("validate_warnings"), list)
                    else []
                )
                errs = (
                    res.get("validate_errors")
                    if isinstance(res.get("validate_errors"), list)
                    else []
                )
                if errs or not warns:
                    await _facade()._fail_session(
                        sid, "generate", res.get("error") or "；".join(errs[:3]) or "生成失败"
                    )
                    return
            if _use_word_extract_pipeline or _use_asset_pipeline:
                from modstore_server.vibecoding_convert_loop import is_llm_codegen_source

                _rt_gate = (
                    res.get("runtime_generation")
                    if isinstance(res.get("runtime_generation"), dict)
                    else {}
                )
                _ds_gate = (
                    res.get("domain_smoke") if isinstance(res.get("domain_smoke"), dict) else {}
                )
                _gc_gate = (
                    res.get("golden_comparison")
                    if isinstance(res.get("golden_comparison"), dict)
                    else {}
                )
                if not is_llm_codegen_source(_rt_gate):
                    await _facade()._fail_session(
                        sid,
                        "generate",
                        f"convert 须由 LLM 生成（当前 source={_rt_gate.get('source') or 'unknown'}）",
                    )
                    return
                if _ds_gate.get("ok") is False:
                    await _facade()._fail_session(
                        sid,
                        "generate",
                        f"领域冒烟未通过：{_ds_gate.get('error') or 'failed'}"[:1000],
                    )
                    return
                if _gc_gate and _gc_gate.get("golden_pack_id") and (not _gc_gate.get("passed")):
                    await _facade()._fail_session(
                        sid,
                        "generate",
                        f"黄金对比未达标：parity={_gc_gate.get('parity_score')} diffs={len(_gc_gate.get('diff_items') or [])}"[
                            :1000
                        ],
                    )
                    return
            _gen_pack_dir = _facade().Path(str(res.get("path") or ""))
            if _use_word_extract_pipeline and _gen_pack_dir.is_dir():
                from modstore_server.employee_asset_pipeline import reconcile_employee_pack_manifest
                from modstore_server.word_extract_runtime import validate_word_extract_backend

                reconcile_employee_pack_manifest(_gen_pack_dir, brief=employee_brief)
                (_gx_errs, _) = validate_word_extract_backend(_gen_pack_dir)
                if _gx_errs:
                    await _facade()._fail_session(sid, "generate", "；".join(_gx_errs[:3]))
                    return
            asset_count = (
                len((res.get("asset_manifest") or {}).get("assets") or [])
                if isinstance(res.get("asset_manifest"), dict)
                else 0
            )
            if _use_word_extract_pipeline:
                _rt_meta = (
                    res.get("runtime_generation")
                    if isinstance(res.get("runtime_generation"), dict)
                    else {}
                )
                _gc_meta = (
                    res.get("golden_comparison")
                    if isinstance(res.get("golden_comparison"), dict)
                    else {}
                )
                _round = _rt_meta.get("round")
                _parity = _gc_meta.get("parity_score")
                _gen_done_msg = "已生成 Word 全量提取员工包（LLM convert"
                if _round is not None:
                    _gen_done_msg += f"，repair 轮次 {_round}"
                if _parity is not None:
                    _gen_done_msg += f"，黄金 parity {_parity}"
                _gen_done_msg += "）"
            elif _use_asset_pipeline:
                _gen_done_msg = f"已生成资产驱动员工包；资产 {asset_count} 个"
            elif _needs_llm_reasoning and _uploaded_docx:
                _gen_done_msg = "已生成 LLM 驱动文档审核员工包"
            else:
                _gen_done_msg = None
            await _facade()._set_step(sid, "generate", "done", _gen_done_msg)
        if _should_skip("validate"):
            await _facade()._set_step(sid, "validate", "done", "已完成（重试复用）")
        else:
            _emp_current_step = "validate"
            await _facade()._set_step(sid, "validate", "running")
            _val_result = await _facade()._dispatch_craft_step(
                "validate",
                res=res,
                brief=employee_brief or _routing_brief or brief,
                pack_dir=res.get("path"),
                user_id=user_id,
            )
            validate_warnings = (
                _val_result.get("validate_warnings")
                if _val_result and isinstance(_val_result.get("validate_warnings"), list)
                else (
                    res.get("validate_warnings")
                    if isinstance(res.get("validate_warnings"), list)
                    else []
                )
            )
            validate_errors = (
                _val_result.get("validate_errors")
                if _val_result and isinstance(_val_result.get("validate_errors"), list)
                else []
            )
            async with _facade()._SESSION_LOCK:
                sess = _facade().WORKBENCH_SESSIONS.get(sid)
                if sess:
                    sess["validate_warnings"] = validate_warnings
                    if validate_errors:
                        sess["validate_errors"] = validate_errors
                    _facade()._persist_workbench_session_unlocked(sid)
            if validate_errors:
                msg = "；".join((str(x) for x in validate_errors[:5]))
                await _facade()._set_step(sid, "validate", "error", msg[:480])
                await _facade()._fail_session(sid, "validate", msg[:1000])
                return
            await _facade()._set_step(
                sid,
                "validate",
                "done",
                (
                    "；".join((str(x) for x in validate_warnings[:5]))
                    if validate_warnings
                    else "manifest、Python 与包体校验通过"
                ),
            )
            pack_dir = _facade().Path(str(res.get("path") or ""))
            script_wf: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
            script_attachment: _facade().Dict[str, _facade().Any] = {}
            script_result: _facade().Dict[str, _facade().Any] = {}
        if _should_skip("script_workflow"):
            await _facade()._set_step(sid, "script_workflow", "done", "已完成（重试复用）")
        else:
            _emp_current_step = "script_workflow"
            if _use_asset_pipeline or (_needs_llm_reasoning and _uploaded_docx):
                _asset_names = [
                    str(f.get("filename") or f.get("name") or "")[:60]
                    for f in employee_files
                    if isinstance(f, dict)
                ][:5]
                _asset_hint = f"（资产：{'、'.join(_asset_names)}）" if _asset_names else ""
                if _use_word_extract_pipeline:
                    _skip_reason = (
                        "Word direct_python 模式：员工内置 vendor convert，无需配套小程序"
                    )
                elif _needs_llm_reasoning and _uploaded_docx:
                    _skip_reason = "LLM 驱动文档审核模式"
                else:
                    _skip_reason = "资产驱动模式"
                await _facade()._set_step(
                    sid,
                    "script_workflow",
                    "skipped",
                    f"{_skip_reason}{(_asset_hint if not _use_word_extract_pipeline else '')}",
                )
                embed_script_workflow = False
            elif embed_script_workflow:
                _facade()._LOG.info(
                    "pipeline: script_workflow step — prov=%r mdl=%r db=%s sid=%s",
                    prov,
                    mdl,
                    type(db).__name__ if db else None,
                    sid,
                )
                await _facade()._set_step(
                    sid, "script_workflow", "running", "正在生成员工配套小程序"
                )

                async def _script_progress(msg: str) -> None:
                    await _facade()._set_step(sid, "script_workflow", "running", msg)

                _sw_result = await _facade()._dispatch_craft_step(
                    "script_workflow",
                    db=db,
                    user_id=user_id,
                    session_id=f"{sid}-employee-script",
                    brief=script_brief,
                    files=employee_files,
                    provider=prov,
                    model=mdl,
                    system_hint=script_hint,
                    payload={
                        **payload,
                        "brief": script_brief,
                        "workflow_name": planned_script_name
                        or wf_name
                        or res.get("id")
                        or "员工配套",
                    },
                    status_hook=_script_progress,
                )
                if _sw_result:
                    script_result = _sw_result["script_result"]
                    script_wf = _sw_result["script_wf"]
                else:
                    script_result = await _facade().run_script_agent_job(
                        db=db,
                        user_id=user_id,
                        session_id=f"{sid}-employee-script",
                        brief=script_brief,
                        files=employee_files,
                        provider=prov,
                        model=mdl,
                        system_hint=script_hint,
                        status_hook=_script_progress,
                    )
                    script_wf = None
                    if script_result.get("ok") and (not script_result.get("errors")):
                        script_wf = _facade()._commit_script_workflow_from_result(
                            db,
                            user_id=user_id,
                            session_id=sid,
                            payload={
                                **payload,
                                "brief": script_brief,
                                "workflow_name": planned_script_name
                                or wf_name
                                or res.get("id")
                                or "员工配套",
                            },
                            files=employee_files,
                            result=script_result,
                        )
                if not script_wf:
                    if script_result.get("ok"):
                        _script_err_parts = []
                        if not str(script_result.get("script") or "").strip():
                            _script_err_parts.append("脚本代码为空")
                        if script_result.get("errors"):
                            _script_err_parts.append(
                                "；".join((str(e) for e in script_result["errors"][:3]))
                            )
                        _skip_reason = (
                            "；".join(_script_err_parts)
                            if _script_err_parts
                            else "未能生成可保存的脚本工作流"
                        )
                        await _facade()._set_step(
                            sid, "script_workflow", "skipped", f"已跳过：{_skip_reason}"
                        )
                        _facade()._LOG.warning(
                            "pipeline: script_wf=None but ok=True — skipping, reason=%s session=%s",
                            _skip_reason,
                            sid,
                        )
                    else:
                        _script_err = (
                            "；".join((str(e) for e in (script_result.get("errors") or [])[:3]))
                            or "脚本执行失败"
                        )
                        msg = f"脚本运行失败：{_script_err}"
                        await _facade()._set_step(sid, "script_workflow", "error", msg[:300])
                        await _facade()._fail_session(sid, "script_workflow", msg[:1000])
                        return
                else:
                    await _facade()._set_step(
                        sid, "script_workflow", "done", f"已生成脚本工作流 id={script_wf.get('id')}"
                    )
            else:
                await _facade()._set_step(
                    sid, "script_workflow", "skipped", "已跳过：未开启配套小程序"
                )
        if _should_skip("embed_script"):
            await _facade()._set_step(sid, "embed_script", "done", "已完成（重试复用）")
        else:
            wf_attach: _facade().Dict[str, _facade().Any] = {}
            saved_package: _facade().Dict[str, _facade().Any] = res.get("package") or {}
            published_to_catalog = False
            _emp_current_step = "embed_script"
            if embed_script_workflow and script_wf:
                await _facade()._set_step(
                    sid, "embed_script", "running", "正在把配套小程序绑定到员工能力"
                )
                _es_result = await _facade()._dispatch_craft_step(
                    "embed_script",
                    pack_dir=pack_dir,
                    script_wf=script_wf,
                    brief=script_brief,
                    db=db,
                    published_to_catalog=published_to_catalog,
                    user=user,
                )
                if _es_result:
                    script_attachment = _es_result["script_attachment"]
                    if _es_result.get("saved_package"):
                        saved_package = _es_result["saved_package"]
                else:
                    script_attachment = _facade()._embed_script_workflow_in_employee_pack(
                        pack_dir, script_workflow=script_wf, brief=script_brief, db=db
                    )
                    if published_to_catalog:
                        saved_package = _facade()._refresh_employee_pack_catalog_zip(
                            db, user, pack_dir
                        )
                await _facade()._set_step(
                    sid,
                    "embed_script",
                    "done",
                    f"已写入脚本工作流 id={script_attachment.get('script_workflow_id')}",
                )
            else:
                if _use_word_extract_pipeline:
                    _embed_skip = "Word direct_python 模式：无需脚本工作流绑定"
                elif not script_wf:
                    _embed_skip = "已跳过绑定：未生成配套脚本工作流"
                else:
                    _embed_skip = "已跳过绑定：未开启 embed_script_workflow"
                await _facade()._set_step(sid, "embed_script", "skipped", _embed_skip)
        if _should_skip("workflow"):
            await _facade()._set_step(sid, "workflow", "done", "已完成（重试复用）")
        else:
            _emp_current_step = "workflow"
            await _facade()._set_step(sid, "workflow", "running", "正在创建自动化流程…")

            async def _emp_wf_msg(text: str) -> None:
                await _facade()._set_step(sid, "workflow", "running", text)

            if et == "pack_plus_workflow":
                _wf_result = await _facade()._dispatch_craft_step(
                    "workflow",
                    db=db,
                    user=user,
                    pack_dir=pack_dir,
                    brief=workflow_brief,
                    workflow_name=wf_name or planned_workflow_name,
                    provider=prov,
                    model=mdl,
                    published_to_catalog=published_to_catalog,
                    status_hook=_emp_wf_msg,
                )
                if _wf_result:
                    wf_attach = _wf_result["wf_attach"]
                    if _wf_result.get("saved_package"):
                        saved_package = _wf_result["saved_package"]
                else:
                    wf_attach = await _facade().attach_nl_workflow_to_employee_pack_dir(
                        db,
                        user,
                        pack_dir=pack_dir,
                        brief=workflow_brief,
                        workflow_name=wf_name or planned_workflow_name,
                        provider=prov,
                        model=mdl,
                        status_hook=_emp_wf_msg,
                    )
                    if published_to_catalog:
                        saved_package = _facade()._refresh_employee_pack_catalog_zip(
                            db, user, pack_dir
                        )
                _eskill_n = int(wf_attach.get("eskill_count") or 0)
                _nl_ok = (wf_attach.get("nl") or {}).get("ok")
                if _eskill_n:
                    wmsg = f"已创建工作流 id={wf_attach.get('workflow_id')}；注入 {_eskill_n} 个真脚本 Skill，NL 编排{('成功' if _nl_ok else '有提示')}"
                else:
                    wmsg = f"已创建工作流 id={wf_attach.get('workflow_id')}；NL 生图{('成功' if _nl_ok else '有提示')}"
                await _facade()._set_step(sid, "workflow", "done", wmsg[:480])
            else:
                await _facade()._set_step(
                    sid,
                    "workflow",
                    "skipped",
                    "已跳过：当前为「仅员工包」模式；若需画布请选 pack_plus_workflow 并重新编排",
                )
        if _should_skip("register_pack"):
            await _facade()._set_step(sid, "register_pack", "done", "已完成（重试复用）")
        elif et == "pack_plus_workflow" and (
            not (
                isinstance(wf_attach, dict)
                and (
                    wf_attach.get("automation_complete")
                    or (wf_attach.get("ok") and wf_attach.get("workflow_id"))
                )
            )
        ):
            _reg_upstream = "workflow-automator 未完成（缺少 automation_complete / workflow_id），已拒收登记并退回上游"
            await _facade()._set_step(sid, "register_pack", "error", _reg_upstream[:480])
            await _facade()._fail_session(sid, "register_pack", _reg_upstream[:1000])
        else:
            _emp_current_step = "register_pack"
            await _facade()._set_step(sid, "register_pack", "running", "正在保存员工包到本地库…")
            _emp_reg_zero_warning = False
            try:
                _emp_mf = res.get("manifest") if isinstance(res, dict) else None
                _emp_pack_id = str(res.get("id") or (_emp_mf or {}).get("id") or "").strip()
                if _emp_pack_id and pack_dir.is_dir():
                    from modstore_server.employee_ai_scaffold import (
                        normalize_editor_manifest_for_registry,
                    )
                    from modstore_server.employee_asset_pipeline import (
                        reconcile_employee_pack_manifest,
                    )

                    reconcile_employee_pack_manifest(pack_dir, brief=employee_brief)
                    _raw_mf = _facade().json.loads(
                        (pack_dir / "manifest.json").read_text(encoding="utf-8")
                    )
                    (_aligned_mf, _align_errs) = normalize_editor_manifest_for_registry(
                        _raw_mf, _emp_pack_id
                    )
                    (pack_dir / "manifest.json").write_text(
                        _facade().json.dumps(_aligned_mf, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    reconcile_employee_pack_manifest(pack_dir, brief=employee_brief)
                    if _use_word_extract_pipeline:
                        from modstore_server.word_extract_runtime import (
                            validate_word_extract_backend,
                        )

                        (_reg_wx_errs, _) = validate_word_extract_backend(pack_dir)
                        if _reg_wx_errs:
                            _reg_fail = "登记前 Word runtime 未就绪：" + "；".join(_reg_wx_errs[:3])
                            await _facade()._set_step(
                                sid, "register_pack", "error", _reg_fail[:480]
                            )
                            await _facade()._fail_session(sid, "register_pack", _reg_fail[:1000])
                            return
                    try:
                        saved_package = _facade()._refresh_employee_pack_catalog_zip(
                            db, user, pack_dir
                        )
                        published_to_catalog = True
                        _reg_msg = f"员工包已保存并登记至目录（{_emp_pack_id}）；可在「员工制作」左侧列表查看"
                    except Exception as _cat_exc:
                        _facade()._LOG.warning(
                            "register_pack catalog sync failed session=%s pack=%s: %s",
                            sid,
                            _emp_pack_id,
                            _cat_exc,
                        )
                        _reg_msg = f"目录登记失败：{_cat_exc!s}"[:480]
                        await _facade()._set_step(sid, "register_pack", "error", _reg_msg)
                        await _facade()._fail_session(sid, "register_pack", _reg_msg[:1000])
                        return
                    await _facade()._set_step(sid, "register_pack", "done", _reg_msg[:480])
                else:
                    _emp_reg_zero_warning = True
                    msg = "未找到有效包 ID 或包目录，员工包未保存——请确认 manifest.id"
                    await _facade()._set_step(sid, "register_pack", "error", msg[:480])
                    await _facade()._fail_session(sid, "register_pack", msg[:1000])
                    return
            except Exception as _reg_exc:
                _facade()._LOG.exception(
                    "register_pack failed for employee session=%s: %s", sid, _reg_exc
                )
                _emp_reg_zero_warning = True
                msg = f"保存异常: {_reg_exc!s}"
                await _facade()._set_step(sid, "register_pack", "error", msg[:480])
                await _facade()._fail_session(sid, "register_pack", msg[:1000])
                return
        if _should_skip("workflow_sandbox"):
            await _facade()._set_step(sid, "workflow_sandbox", "done", "已完成（重试复用）")
        else:
            _emp_current_step = "workflow_sandbox"
            await _facade()._set_step(
                sid, "workflow_sandbox", "running", "工作流结构校验（validate_only）"
            )
            workflow_sandbox: _facade().Dict[str, _facade().Any]
            wid_raw = wf_attach.get("workflow_id") if isinstance(wf_attach, dict) else None
            try:
                wid_int = int(wid_raw) if wid_raw is not None else 0
            except (TypeError, ValueError):
                wid_int = 0
            if et == "pack_plus_workflow" and wid_int <= 0:
                from modstore_server.craft_failure_signals import invalid_workflow_sandbox_report

                _wf_invalid_msg = "输入 workflow_id 无效：pack-registrar / workflow-automator 须先创建画布工作流并写入 wf_attach.workflow_id"
                report = invalid_workflow_sandbox_report(wid_raw)
                workflow_sandbox = {
                    "ok": False,
                    "skipped": False,
                    "workflow_id": wid_raw,
                    "reports": [report],
                    "business_tested": False,
                    "summary": report.get("summary") or "输入 workflow_id 无效",
                }
                await _facade()._set_step(sid, "workflow_sandbox", "error", _wf_invalid_msg[:480])
                await _facade()._fail_session(sid, "workflow_sandbox", _wf_invalid_msg[:1000])
                return
            if et == "pack_plus_workflow" and wid_int > 0:
                wid = wid_int
                _ws_result = await _facade()._dispatch_craft_step(
                    "workflow_sandbox",
                    workflow_id=wid,
                    brief=brief or "测试任务",
                    user_id=user.id,
                    db=db,
                )
                if _ws_result and isinstance(_ws_result.get("report"), dict):
                    report = _ws_result["report"]
                elif _ws_result is None:
                    report = _facade().run_workflow_sandbox(
                        wid, {}, mock_employees=True, validate_only=True, user_id=user.id
                    )
                else:
                    report = (
                        _ws_result.get("report")
                        if isinstance(_ws_result.get("report"), dict)
                        else _facade().run_workflow_sandbox(
                            wid, {}, mock_employees=True, validate_only=True, user_id=user.id
                        )
                    )
                _facade().record_workflow_sandbox_run(
                    db,
                    workflow_id=int(wid),
                    user_id=user.id,
                    report=report,
                    validate_only=True,
                    mock_employees=True,
                )
                workflow_sandbox = {
                    "ok": bool(report.get("ok")),
                    "skipped": False,
                    "workflow_id": int(wid),
                    "reports": [report],
                    "business_tested": False,
                    "note": "仅验证了工作流图结构完整性，未执行真实员工业务逻辑",
                }
                if report.get("ok"):
                    await _facade()._set_step(
                        sid,
                        "workflow_sandbox",
                        "running",
                        "结构校验通过，正在执行真实员工调用验证…",
                    )
                    _biz_pack_id = str(
                        res.get("id")
                        or (
                            res.get("manifest") or {}
                            if isinstance(res.get("manifest"), dict)
                            else {}
                        ).get("id")
                        or pack_dir.name
                    ).strip()
                    if not _facade()._assert_employee_catalog_registered(db, _biz_pack_id):
                        try:
                            _facade()._refresh_employee_pack_catalog_zip(db, user, pack_dir)
                            published_to_catalog = True
                        except Exception as _cat_retry_exc:
                            _facade()._LOG.warning(
                                "workflow_sandbox catalog retry failed: %s", _cat_retry_exc
                            )
                    if not _facade()._assert_employee_catalog_registered(db, _biz_pack_id):
                        _wf_sandbox_biz_ok = False
                        _wf_sb_msg = (
                            f"结构校验通过 ✅，真实调用验证失败：员工包未登记（{_biz_pack_id}）"
                        )
                        if _pipeline_label in (
                            "word_full_extract",
                            "txt_full_read",
                            "txt_generate",
                        ):
                            await _facade()._set_step(
                                sid, "workflow_sandbox", "error", _wf_sb_msg[:480]
                            )
                            await _facade()._fail_session(
                                sid, "workflow_sandbox", _wf_sb_msg[:1000]
                            )
                            return
                    else:
                        try:
                            import base64 as _b64mod
                            from modstore_server.txt_extract_runtime import (
                                minimal_txt_fixture_bytes,
                            )
                            from modstore_server.word_extract_runtime import (
                                minimal_docx_fixture_b64,
                            )

                            _biz_input: _facade().Dict[str, _facade().Any] = {
                                "task": _routing_brief or brief or "测试任务"
                            }
                            if _pipeline_label == "word_full_extract":
                                _biz_input["files"] = [
                                    {
                                        "filename": "smoke.docx",
                                        "content_base64": minimal_docx_fixture_b64(),
                                    }
                                ]
                            elif _pipeline_label in ("txt_full_read", "txt_generate"):
                                _biz_input["files"] = [
                                    {
                                        "filename": "smoke.txt",
                                        "content_base64": _b64mod.b64encode(
                                            minimal_txt_fixture_bytes()
                                        ).decode("ascii"),
                                    }
                                ]
                            biz_report = _facade().run_workflow_sandbox(
                                int(wid),
                                _biz_input,
                                mock_employees=False,
                                validate_only=False,
                                user_id=user.id,
                            )
                            _facade().record_workflow_sandbox_run(
                                db,
                                workflow_id=int(wid),
                                user_id=user.id,
                                report=biz_report,
                                validate_only=False,
                                mock_employees=False,
                            )
                            workflow_sandbox["reports"].append(biz_report)
                            workflow_sandbox["business_tested"] = True
                            if biz_report.get("ok"):
                                workflow_sandbox["ok"] = True
                                _wf_sandbox_biz_ok = True
                                _wf_sb_msg = "结构校验通过 ✅ + 真实员工调用验证通过 ✅"
                            else:
                                _wf_sandbox_biz_ok = False
                                _biz_errs = biz_report.get("errors") or []
                                _biz_warns = biz_report.get("warnings") or []
                                _wf_sb_msg = f"结构校验通过 ✅，真实调用验证有提示（{len(_biz_errs)} 错误，{len(_biz_warns)} 警告）"
                                if _biz_errs:
                                    _wf_sb_msg += "；" + "；".join(
                                        (str(e)[:100] for e in _biz_errs[:2])
                                    )
                                if _pipeline_label in (
                                    "word_full_extract",
                                    "txt_full_read",
                                    "txt_generate",
                                ):
                                    await _facade()._set_step(
                                        sid, "workflow_sandbox", "error", _wf_sb_msg[:480]
                                    )
                                    await _facade()._fail_session(
                                        sid, "workflow_sandbox", _wf_sb_msg[:1000]
                                    )
                                    return
                        except Exception as _biz_exc:
                            workflow_sandbox["business_tested"] = True
                            _wf_sandbox_biz_ok = False
                            _wf_sb_msg = f"结构校验通过 ✅，真实调用验证异常：{_biz_exc!s}"[:300]
                            if _pipeline_label in (
                                "word_full_extract",
                                "txt_full_read",
                                "txt_generate",
                            ):
                                await _facade()._set_step(
                                    sid, "workflow_sandbox", "error", _wf_sb_msg[:480]
                                )
                                await _facade()._fail_session(
                                    sid, "workflow_sandbox", _wf_sb_msg[:1000]
                                )
                                return
                else:
                    _wf_sb_msg = "结构校验有提示，请进画布查看"
                await _facade()._set_step(sid, "workflow_sandbox", "done", _wf_sb_msg)
            else:
                wf_skip_msg = "已跳过结构校验：未创建画布工作流或模式为仅员工包。如需工作流结构校验，请选择 pack_plus_workflow 模式。"
                workflow_sandbox = {
                    "ok": True,
                    "skipped": True,
                    "reason": wf_skip_msg,
                    "reports": [],
                    "business_tested": False,
                }
                await _facade()._set_step(sid, "workflow_sandbox", "skipped", wf_skip_msg[:520])
        if _should_skip("mod_sandbox"):
            await _facade()._set_step(sid, "mod_sandbox", "done", "已完成（重试复用）")
        else:
            _emp_current_step = "mod_sandbox"
            await _facade()._set_step(
                sid, "mod_sandbox", "running", "正在校验包体（manifest / Python）"
            )
            _msb_result = await _facade()._dispatch_craft_step(
                "mod_sandbox", pack_dir=pack_dir, wf_attach=wf_attach, user_id=user_id
            )
            if _msb_result:
                emp_mod_sandbox = _msb_result["emp_mod_sandbox"]
                mod_sb_msg = _msb_result["mod_sb_msg"]
                mod_checks = emp_mod_sandbox.get("checks", [])
            else:
                mod_checks: _facade().List[_facade().Dict[str, _facade().Any]] = []
                if pack_dir.is_dir():
                    (_mf, mf_err) = _facade().read_manifest(pack_dir)
                    mod_checks.append(
                        {
                            "id": "manifest",
                            "ok": mf_err is None,
                            "message": mf_err or "manifest 可读取",
                        }
                    )
                    py_warns = _facade().mod_compileall_warnings(pack_dir)
                    mod_checks.append(
                        {
                            "id": "python_compile",
                            "ok": not py_warns,
                            "message": (
                                "；".join(py_warns)
                                if py_warns
                                else "未发现需编译的 Python 或检查通过"
                            ),
                        }
                    )
                    cons_warns = _facade().employee_pack_consistency_warnings(pack_dir)
                    mod_checks.append(
                        {
                            "id": "employee_pack_consistency",
                            "ok": not cons_warns,
                            "message": (
                                "；".join(cons_warns)[:1200]
                                if cons_warns
                                else "manifest ↔ employees 一致性检查通过"
                            ),
                        }
                    )
                    vibe_checks = _facade()._check_vibe_coding_capability(pack_dir, wf_attach)
                    mod_checks.extend(vibe_checks)
                else:
                    mod_checks.append(
                        {"id": "manifest", "ok": False, "message": f"包目录无效: {pack_dir}"}
                    )
                emp_mod_sandbox = {
                    "ok": all((c.get("ok") for c in mod_checks)) if mod_checks else False,
                    "checks": mod_checks,
                    "note": "员工包轻量校验（含 backend/blueprints 运行时与 vibe-coding 能力检查）",
                }
                _all_pass = emp_mod_sandbox["ok"]
                _vibe_gaps = [
                    c for c in mod_checks if not c.get("ok") and "vibe" in c.get("id", "")
                ]
                if _all_pass:
                    mod_sb_msg = "包体轻量校验通过"
                elif _vibe_gaps:
                    mod_sb_msg = "基础校验通过，vibe-coding 能力存在缺口：" + "；".join(
                        (c.get("message", "") for c in _vibe_gaps)
                    )
                else:
                    mod_sb_msg = "包体校验有提示，见会话 artifact.mod_sandbox"
            _prompt_chk = next(
                (c for c in mod_checks if str(c.get("id") or "") == "vibe_system_prompt_quality"),
                None,
            )
            if _prompt_chk is not None and (not _prompt_chk.get("ok")):
                msg = str(_prompt_chk.get("message") or "backend/employees/*.py 缺少 SYSTEM_PROMPT")
                await _facade()._set_step(sid, "mod_sandbox", "error", msg[:480])
                await _facade()._fail_session(sid, "mod_sandbox", msg[:2000])
                return
            _runtime_chk_id = {
                "word_full_extract": "word_extract_runtime",
                "txt_full_read": "txt_read_runtime",
                "txt_generate": "txt_generate_runtime",
            }.get(_pipeline_label, "")
            _wx_runtime_chk = (
                next((c for c in mod_checks if str(c.get("id") or "") == _runtime_chk_id), None)
                if _runtime_chk_id
                else None
            )
            if (
                _pipeline_label in ("word_full_extract", "txt_full_read", "txt_generate")
                and _wx_runtime_chk is not None
                and (not _wx_runtime_chk.get("ok"))
            ):
                msg = str(_wx_runtime_chk.get("message") or f"{_pipeline_label} runtime 校验未通过")
                await _facade()._set_step(sid, "mod_sandbox", "error", msg[:480])
                await _facade()._fail_session(sid, "mod_sandbox", msg[:1000])
                return
            await _facade()._set_step(sid, "mod_sandbox", "done", mod_sb_msg[:480])
        if _should_skip("standalone_smoke"):
            await _facade()._set_step(sid, "standalone_smoke", "done", "已完成（重试复用）")
        else:
            _emp_current_step = "standalone_smoke"
            await _facade()._set_step(
                sid,
                "standalone_smoke",
                "running",
                "正在生成独立包并验证 python xxx.xcemp validate …",
            )
            _ss_result = await _facade()._dispatch_craft_step(
                "standalone_smoke", res=res, pack_dir=pack_dir, user_id=user_id
            )
            if _ss_result:
                _standalone_smoke_ok = _ss_result["standalone_smoke_ok"]
                _standalone_smoke_msg = _ss_result["standalone_smoke_msg"]
                _standalone_smoke_skipped = _ss_result.get("standalone_smoke_skipped", False)
            else:
                _standalone_smoke_ok = False
                _standalone_smoke_skipped = False
                _standalone_smoke_msg = "跳过（未能获取包字节）"
            _standalone_smoke_status = (
                "skipped"
                if _standalone_smoke_skipped
                else "error" if not _standalone_smoke_ok else "done"
            )
            if _standalone_smoke_status == "error" and _pipeline_label not in (
                "word_full_extract",
                "txt_full_read",
                "txt_generate",
            ):
                _standalone_smoke_status = "skipped"
                _standalone_smoke_msg = (
                    f"⚠️ 独立包自检未通过，已跳过继续后续步骤：{_standalone_smoke_msg}"
                )
            elif _standalone_smoke_status == "error":
                await _facade()._set_step(
                    sid, "standalone_smoke", "error", _standalone_smoke_msg[:480]
                )
                await _facade()._fail_session(sid, "standalone_smoke", _standalone_smoke_msg[:1000])
                return
            await _facade()._set_step(
                sid, "standalone_smoke", _standalone_smoke_status, _standalone_smoke_msg[:480]
            )
        if _should_skip("host_check"):
            await _facade()._set_step(sid, "host_check", "done", "已完成（重试复用）")
        else:
            _emp_current_step = "host_check"
            host_probe: _facade().Dict[str, _facade().Any] = {"skipped": True}
            await _facade()._set_step(sid, "host_check", "running", "探测宿主 /api/mods/")
            _hc_result = await _facade()._dispatch_craft_step(
                "host_check", fhd_base=fhd_base or "", user_id=user_id
            )
            if _hc_result:
                host_probe = _hc_result["host_probe"]
                host_check_msg = _hc_result["host_check_msg"]
                if host_probe.get("skipped"):
                    await _facade()._set_step(sid, "host_check", "skipped", host_check_msg[:480])
                elif host_probe.get("ok"):
                    await _facade()._set_step(sid, "host_check", "done", host_check_msg[:480])
                else:
                    await _facade()._set_step(sid, "host_check", "done", host_check_msg[:480])
            elif fhd_base:
                try:
                    from modstore_server.infrastructure.http_clients import get_external_client

                    base = fhd_base.rstrip("/")
                    host_warnings: _facade().List[str] = []
                    client = get_external_client()
                    r = await client.get(f"{base}/api/mods/", timeout=10.0)
                    host_probe = {
                        "skipped": False,
                        "ok": r.status_code < 500,
                        "status_code": r.status_code,
                        "url": f"{base}/api/mods/",
                    }
                    try:
                        lr = await client.get(f"{base}/api/mods/llm-status")
                        if lr.status_code == 200:
                            try:
                                lj = lr.json()
                                if isinstance(lj, dict) and lj.get("api_key_configured") is False:
                                    host_warnings.append(
                                        "宿主返回 llm-status：未配置 LLM API Key，员工运行时可能无法调用模型"
                                    )
                            except Exception:
                                host_warnings.append("llm-status 返回非 JSON，跳过密钥探测")
                        elif lr.status_code == 404:
                            host_warnings.append(
                                "宿主未提供 /api/mods/llm-status（可选），无法在编排阶段探测 LLM 密钥"
                            )
                    except Exception:
                        host_warnings.append("无法请求宿主 /api/mods/llm-status（可选端点）")
                    try:
                        vr = await client.get(f"{base}/api/version")
                        if vr.status_code == 200:
                            try:
                                vj = vr.json()
                                if isinstance(vj, dict) and vj.get("min_mod_sdk_version"):
                                    host_probe["host_min_mod_sdk_version"] = str(
                                        vj.get("min_mod_sdk_version") or ""
                                    )
                            except Exception:
                                pass
                    except Exception:
                        pass
                    msg = (
                        f"HTTP {r.status_code}"
                        if host_probe.get("ok")
                        else f"HTTP {r.status_code}（异常）"
                    )
                    if host_warnings:
                        msg += "；" + "；".join(host_warnings[:3])[:400]
                        host_probe["warnings"] = host_warnings
                    await _facade()._set_step(sid, "host_check", "done", msg[:480])
                except Exception as e:
                    host_probe = {"skipped": False, "ok": False, "error": str(e)[:300]}
                    await _facade()._set_step(sid, "host_check", "done", f"探测失败: {e!s}"[:300])
            else:
                _host_skip = (
                    "文件型 direct_python：本地转换无需宿主；未配置 fhd_base_url 已跳过"
                    if _pipeline_label in ("word_full_extract", "txt_full_read", "txt_generate")
                    else "未配置 fhd_base_url，已跳过；如需部署到宿主，请在环境变量或配置中设置 FHD_BASE_URL 后重新运行连通性检查"
                )
                await _facade()._set_step(sid, "host_check", "skipped", _host_skip)
        _six_dimension_report: _facade().Dict[str, _facade().Any] = {}
        if _should_skip("six_dim_gate"):
            await _facade()._set_step(sid, "six_dim_gate", "done", "已完成（重试复用）")
        else:
            _emp_current_step = "six_dim_gate"
            await _facade()._set_step(sid, "six_dim_gate", "running", "正在汇总六维质量分数…")
            _asset_n = 0
            if isinstance(res.get("asset_manifest"), dict):
                _asset_n = len((res.get("asset_manifest") or {}).get("assets") or [])
            async with _facade()._SESSION_LOCK:
                _sess_sd = _facade().WORKBENCH_SESSIONS.get(sid) or {}
                _spec_warn_sd = (
                    _sess_sd.get("spec_warnings")
                    if isinstance(_sess_sd.get("spec_warnings"), list)
                    else []
                )
                _struct_sd = (
                    _sess_sd.get("structured_requirement")
                    if isinstance(_sess_sd.get("structured_requirement"), dict)
                    else {}
                )
                _val_err_sd = (
                    _sess_sd.get("validate_errors")
                    if isinstance(_sess_sd.get("validate_errors"), list)
                    else []
                )
            _sd_result = await _facade()._dispatch_craft_step(
                "six_dim_gate",
                pack_dir=pack_dir,
                pipeline_label=_pipeline_label,
                routing_brief=_routing_brief,
                structured_requirement=_struct_sd,
                spec_warnings=_spec_warn_sd,
                validate_errors=_val_err_sd,
                mod_sandbox=emp_mod_sandbox if isinstance(emp_mod_sandbox, dict) else {},
                workflow_sandbox=workflow_sandbox if isinstance(workflow_sandbox, dict) else {},
                workflow_biz_ok=_wf_sandbox_biz_ok,
                standalone_smoke_ok=_standalone_smoke_ok,
                catalog_registered=not _emp_reg_zero_warning,
                employee_target=et,
                asset_count=_asset_n,
                domain_smoke=(
                    res.get("domain_smoke") if isinstance(res.get("domain_smoke"), dict) else None
                ),
                golden_comparison=(
                    res.get("golden_comparison")
                    if isinstance(res.get("golden_comparison"), dict)
                    else None
                ),
                runtime_generation=(
                    res.get("runtime_generation")
                    if isinstance(res.get("runtime_generation"), dict)
                    else None
                ),
            )
            if _sd_result and _sd_result.get("six_dimension_report"):
                _six_dimension_report = _sd_result["six_dimension_report"]
            else:
                from modstore_server.employee_six_dimension import compute_six_dimension_report

                _six_dimension_report = compute_six_dimension_report(
                    pack_dir=pack_dir,
                    pipeline_label=_pipeline_label,
                    routing_brief=_routing_brief,
                    structured_requirement=_struct_sd,
                    spec_warnings=_spec_warn_sd,
                    validate_errors=_val_err_sd,
                    mod_sandbox=emp_mod_sandbox if isinstance(emp_mod_sandbox, dict) else {},
                    workflow_sandbox=workflow_sandbox if isinstance(workflow_sandbox, dict) else {},
                    workflow_biz_ok=_wf_sandbox_biz_ok,
                    standalone_smoke_ok=_standalone_smoke_ok,
                    catalog_registered=not _emp_reg_zero_warning,
                    employee_target=et,
                    asset_count=_asset_n,
                    domain_smoke=(
                        res.get("domain_smoke")
                        if isinstance(res.get("domain_smoke"), dict)
                        else None
                    ),
                    golden_comparison=(
                        res.get("golden_comparison")
                        if isinstance(res.get("golden_comparison"), dict)
                        else None
                    ),
                    runtime_generation=(
                        res.get("runtime_generation")
                        if isinstance(res.get("runtime_generation"), dict)
                        else None
                    ),
                )
            _sd_pass = bool(_six_dimension_report.get("passed"))
            _sd_overall = float(_six_dimension_report.get("overall_score") or 0)
            _sd_failed = _six_dimension_report.get("failed_dimensions") or []
            _sd_msg = f"六维评估 {_sd_overall} 分"
            if _sd_pass:
                _sd_msg += "；6/6 维达标，可在完成步查看雷达图"
            else:
                from modstore_server.employee_six_dimension import DIMENSION_LABELS_ZH

                _sd_msg += (
                    "；未通过："
                    + "、".join((DIMENSION_LABELS_ZH.get(k, k) for k in _sd_failed[:4]))
                    if _sd_failed
                    else "综合分未达标"
                )
            await _facade()._set_step(
                sid,
                "six_dim_gate",
                "error" if _six_dimension_report.get("critical_failed") else "done",
                _sd_msg[:480],
            )
            if _six_dimension_report.get("critical_failed"):
                await _facade()._fail_session(sid, "six_dim_gate", _sd_msg[:1000])
                return
        _emp_current_step = "complete"
        _quality_items: _facade().List[_facade().Dict[str, _facade().Any]] = []
        _quality_items.append({"check": "manifest 校验", "ok": bool(emp_mod_sandbox.get("ok"))})
        _quality_items.append({"check": "Python 编译", "ok": emp_mod_sandbox.get("ok", False)})
        _quality_items.append(
            {
                "check": "工作流结构校验",
                "ok": workflow_sandbox.get("ok", False),
                "note": (
                    "仅结构，未测业务" if not workflow_sandbox.get("business_tested", True) else ""
                ),
            }
        )
        if _wf_sandbox_biz_ok is not None:
            _quality_items.append(
                {
                    "check": "工作流真实调用",
                    "ok": bool(_wf_sandbox_biz_ok),
                    "critical": _pipeline_label
                    in ("word_full_extract", "txt_full_read", "txt_generate"),
                }
            )
        _quality_items.append(
            {
                "check": "独立包自检",
                "ok": _standalone_smoke_ok,
                "critical": _pipeline_label
                in ("word_full_extract", "txt_full_read", "txt_generate"),
            }
        )
        _quality_items.append(
            {"check": "员工包登记", "ok": not _emp_reg_zero_warning, "critical": True}
        )
        _host_note = "已跳过"
        if host_probe.get("skipped") and _pipeline_label in (
            "word_full_extract",
            "txt_full_read",
            "txt_generate",
        ):
            _host_note = "本地文件转换无需宿主"
        _quality_items.append(
            {
                "check": "宿主连通性",
                "ok": host_probe.get("ok") if not host_probe.get("skipped") else None,
                "note": _host_note if host_probe.get("skipped") else "",
            }
        )
        _sess_validate_errors: _facade().List[str] = []
        async with _facade()._SESSION_LOCK:
            _sess_q = _facade().WORKBENCH_SESSIONS.get(sid) or {}
            _ve = _sess_q.get("validate_errors")
            if isinstance(_ve, list):
                _sess_validate_errors = [str(x) for x in _ve if x]
        (_extra_items, _runnable, _critical_failed) = _facade()._employee_quality_extras(
            pack_dir,
            pipeline_label=_pipeline_label,
            validate_errors=_sess_validate_errors,
            mod_sandbox=emp_mod_sandbox if isinstance(emp_mod_sandbox, dict) else {},
            runtime_generation=(
                res.get("runtime_generation")
                if isinstance(res.get("runtime_generation"), dict)
                else {}
            ),
            domain_smoke=(
                res.get("domain_smoke") if isinstance(res.get("domain_smoke"), dict) else {}
            ),
            golden_comparison=(
                res.get("golden_comparison")
                if isinstance(res.get("golden_comparison"), dict)
                else {}
            ),
        )
        _quality_items.extend(_extra_items)
        _failed_critical = [
            q["check"] for q in _quality_items if q.get("ok") is False and q.get("critical")
        ]
        if _failed_critical:
            _critical_failed = True
            _runnable = False
        if _six_dimension_report and _six_dimension_report.get("critical_failed"):
            _critical_failed = True
            _runnable = False
        if _emp_reg_zero_warning and res.get("manifest") and isinstance(res.get("manifest"), dict):
            try:
                await _facade()._set_step(
                    sid, "complete", "running", "登记未通过，正在重试 manifest 对齐…"
                )
                from modstore_server.employee_ai_scaffold import (
                    normalize_editor_manifest_for_registry,
                )

                _retry_mf = res["manifest"]
                _retry_pid = str(_retry_mf.get("id") or res.get("id") or "").strip()
                if _retry_pid and pack_dir.is_dir():
                    _raw_mf = _facade().json.loads(
                        (pack_dir / "manifest.json").read_text(encoding="utf-8")
                    )
                    (_aligned_mf, _) = normalize_editor_manifest_for_registry(_raw_mf, _retry_pid)
                    (pack_dir / "manifest.json").write_text(
                        _facade().json.dumps(_aligned_mf, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    _emp_reg_zero_warning = False
                    for qi in _quality_items:
                        if qi["check"] == "员工包登记":
                            qi["ok"] = True
                            qi["note"] = "重试 manifest 对齐成功（未自动上架）"
            except Exception as _retry_exc:
                _facade()._LOG.warning(
                    "register_pack local retry failed session=%s: %s", sid, _retry_exc
                )
                for qi in _quality_items:
                    if qi["check"] == "员工包登记":
                        qi["note"] = f"重试失败: {_retry_exc!s}"[:120]
        _quality_pass = sum((1 for q in _quality_items if q.get("ok") is True))
        _quality_total = sum((1 for q in _quality_items if q.get("ok") is not None))
        _quality_warn = sum((1 for q in _quality_items if q.get("ok") is False))
        _quality_skip = sum((1 for q in _quality_items if q.get("ok") is None))
        _quality_score = round(_quality_pass / _quality_total * 100, 1) if _quality_total else 0.0
        _complete_msg_parts = [
            f"质量报告：{_quality_pass}/{_quality_total} 通过（{_quality_score} 分）"
        ]
        if _six_dimension_report:
            _complete_msg_parts.insert(
                0,
                f"六维综合 {_six_dimension_report.get('overall_score', 0)} 分"
                + ("（达标）" if _six_dimension_report.get("passed") else "（未达标）"),
            )
        if _pipeline_label == "word_full_extract":
            _complete_msg_parts.append(
                "可提取 Word：" + ("是" if _runnable else "否（handlers/convert 未对齐）")
            )
        if _quality_warn:
            _complete_msg_parts.append(f"{_quality_warn} 项需关注")
        if _quality_skip:
            _complete_msg_parts.append(f"{_quality_skip} 项跳过")
        _failed_checks = [q["check"] for q in _quality_items if q.get("ok") is False]
        if _failed_checks:
            _complete_msg_parts.append("⚠️ 未通过：" + "、".join(_failed_checks))
        _complete_msg_parts.append("下一步：在画布中编辑员工配置 → 部署到宿主 → 真实业务验证")
        _complete_status = "error" if _critical_failed else "done"
        if _critical_failed:
            _complete_msg_parts.insert(0, "⚠️ 关键质量项未通过，员工包不可用")
        await _facade()._set_step(
            sid, "complete", _complete_status, "；".join(_complete_msg_parts)[:480]
        )
        if _critical_failed:
            await _facade()._fail_session(sid, "complete", "；".join(_failed_critical)[:1000])
            return
        async with _facade()._SESSION_LOCK:
            sess = _facade().WORKBENCH_SESSIONS.get(sid)
            if sess:
                sess["sandbox_report"] = {"workflow": workflow_sandbox, "mod": emp_mod_sandbox}
                sess["quality_report"] = {
                    "items": _quality_items,
                    "pass": _quality_pass,
                    "total": _quality_total,
                    "warnings": _quality_warn,
                    "skipped": _quality_skip,
                    "failed_checks": _failed_checks,
                    "score": _quality_score,
                    "pipeline_label": _pipeline_label,
                    "runnable": _runnable,
                    "critical_failed": _critical_failed,
                    "six_dimension_report": _six_dimension_report or None,
                }
                if _six_dimension_report:
                    sess["six_dimension_report"] = _six_dimension_report
                _facade()._persist_workbench_session_unlocked(sid)
        emp = (res.get("manifest") or {}).get("employee") or {}
        _pack_id_final = str(res.get("id") or "")
        try:
            from modstore_server.employee_pack_cleanup import cleanup_experimental_pack

            cleanup_experimental_pack(
                _pack_id_final, metadata=payload if isinstance(payload, dict) else None
            )
        except Exception as _clean_exc:
            _facade()._LOG.warning(
                "experimental pack cleanup failed session=%s pack=%s: %s",
                sid,
                _pack_id_final,
                _clean_exc,
            )
        await _facade()._finalize_session_done(
            sid,
            {
                "pack_id": res["id"],
                "employee_id": res["id"],
                "manifest_employee_id": res["id"],
                "name": (res.get("manifest") or {}).get("name"),
                "description": (res.get("manifest") or {}).get("description"),
                "workflow_id": wid,
                "package": saved_package,
                "workflow_sandbox": workflow_sandbox,
                "mod_sandbox": emp_mod_sandbox,
                "employee_target": et,
                "employee_orchestration_plan": employee_plan,
                "workflow_attachment": wf_attach,
                "script_workflow": script_wf,
                "script_workflow_attachment": script_attachment,
                "host_probe": host_probe,
                "quality_report": {
                    "items": _quality_items,
                    "pass": _quality_pass,
                    "total": _quality_total,
                    "warnings": _quality_warn,
                    "skipped": _quality_skip,
                    "failed_checks": _failed_checks,
                    "score": _quality_score,
                    "pipeline_label": _pipeline_label,
                    "runnable": _runnable,
                    "critical_failed": _critical_failed,
                    "six_dimension_report": _six_dimension_report or None,
                },
                "six_dimension_report": _six_dimension_report or None,
                "runtime_generation": res.get("runtime_generation"),
                "domain_smoke": res.get("domain_smoke"),
                "golden_comparison": res.get("golden_comparison"),
                "rule_spec": res.get("rule_spec"),
                "validation_summary": {
                    "ok": bool(emp_mod_sandbox.get("ok")) and (not _emp_reg_zero_warning),
                    "mod_sandbox": emp_mod_sandbox,
                    "workflow_skipped": not bool(wid),
                    "standalone_smoke_ok": _standalone_smoke_ok,
                    "register_ok": not _emp_reg_zero_warning,
                },
            },
        )
    except Exception as e:
        import traceback as _tb

        _emp_id_debug = ""
        try:
            if pack_dir and pack_dir.is_dir():
                _mf_dbg = pack_dir / "manifest.json"
                if _mf_dbg.is_file():
                    _mf_dbg_data = _facade().json.loads(_mf_dbg.read_text(encoding="utf-8"))
                    _emp_dbg = _mf_dbg_data.get("employee") or {}
                    _wf_dbg = _mf_dbg_data.get("workflow_employees") or []
                    _emp_id_debug = " [disk: manifest.id=%s employee.id=%s wf[0].id=%s]" % (
                        _mf_dbg_data.get("id"),
                        _emp_dbg.get("id"),
                        _wf_dbg[0].get("id") if _wf_dbg else "N/A",
                    )
        except Exception:
            pass
        _facade()._LOG.exception(
            "workbench employee pipeline failed session=%s step=%s err=%s%s\nTRACEBACK:\n%s",
            sid,
            _emp_current_step,
            e,
            _emp_id_debug,
            _tb.format_exc(),
        )
        try:
            _fail_pack = ""
            if isinstance(res, dict):
                _fail_pack = str(res.get("id") or "")
            if not _fail_pack and pack_dir:
                _fail_pack = pack_dir.name
            if _fail_pack:
                from modstore_server.employee_pack_cleanup import cleanup_experimental_pack

                cleanup_experimental_pack(
                    _fail_pack, metadata=payload if isinstance(payload, dict) else None
                )
        except Exception as _clean_fail:
            _facade()._LOG.warning(
                "experimental cleanup on error failed session=%s: %s", sid, _clean_fail
            )
        async with _facade()._SESSION_LOCK:
            _sess = _facade().WORKBENCH_SESSIONS.get(sid)
            if _sess:
                _sess["_pipeline_checkpoint"] = {
                    "failed_step": _emp_current_step,
                    "res": res if isinstance(res, dict) and res.get("ok") else None,
                    "pack_dir": str(pack_dir) if pack_dir else None,
                    "employee_plan": employee_plan,
                    "script_wf": script_wf,
                    "script_attachment": script_attachment,
                    "wf_attach": wf_attach,
                    "saved_package": saved_package,
                    "published_to_catalog": published_to_catalog,
                    "employee_target": locals().get("et"),
                    "embed_script_workflow": locals().get("embed_script_workflow"),
                    "wf_name": locals().get("wf_name"),
                    "fhd_base": locals().get("fhd_base"),
                }
                _facade()._persist_workbench_session_unlocked(sid)
        await _facade()._fail_session(sid, _emp_current_step, str(e)[:2000])
    return
