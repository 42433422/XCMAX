# mypy: disable-error-code="attr-defined, misc, no-any-return, type-arg, valid-type"
# isort: skip_file
"""Employee build pipeline phase."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_employee_pipeline_phase_03(ctx: dict[str]) -> bool:
    if ctx["_should_skip"]("script_workflow"):
        await _facade()._set_step(ctx["sid"], "script_workflow", "done", "已完成（重试复用）")
    else:
        ctx["_emp_current_step"] = "script_workflow"
        if ctx["_use_asset_pipeline"] or (ctx["_needs_llm_reasoning"] and ctx["_uploaded_docx"]):
            _asset_names = [
                str(f.get("filename") or f.get("name") or "")[:60]
                for f in ctx["employee_files"]
                if isinstance(f, dict)
            ][:5]
            _asset_hint = f"（资产：{'、'.join(_asset_names)}）" if _asset_names else ""
            if ctx["_use_word_extract_pipeline"]:
                _skip_reason = "Word direct_python 模式：员工内置 vendor convert，无需配套小程序"
            elif ctx["_needs_llm_reasoning"] and ctx["_uploaded_docx"]:
                _skip_reason = "LLM 驱动文档审核模式"
            else:
                _skip_reason = "资产驱动模式"
            await _facade()._set_step(
                ctx["sid"],
                "script_workflow",
                "skipped",
                f"{_skip_reason}{(_asset_hint if not ctx['_use_word_extract_pipeline'] else '')}",
            )
            ctx["embed_script_workflow"] = False
        elif ctx["embed_script_workflow"]:
            _facade()._LOG.info(
                "pipeline: script_workflow step — prov=%r mdl=%r db=%s sid=%s",
                ctx["prov"],
                ctx["mdl"],
                type(ctx["db"]).__name__ if ctx["db"] else None,
                ctx["sid"],
            )
            await _facade()._set_step(
                ctx["sid"], "script_workflow", "running", "正在生成员工配套小程序"
            )

            async def _script_progress(msg: str) -> None:
                await _facade()._set_step(ctx["sid"], "script_workflow", "running", ctx["msg"])

            _sw_result = await _facade()._dispatch_craft_step(
                "script_workflow",
                db=ctx["db"],
                user_id=ctx["user_id"],
                session_id=f"{ctx['sid']}-employee-script",
                brief=ctx["script_brief"],
                files=ctx["employee_files"],
                provider=ctx["prov"],
                model=ctx["mdl"],
                system_hint=ctx["script_hint"],
                payload={
                    **ctx["payload"],
                    "brief": ctx["script_brief"],
                    "workflow_name": ctx["planned_script_name"]
                    or ctx["wf_name"]
                    or ctx["res"].get("id")
                    or "员工配套",
                },
                status_hook=_script_progress,
            )
            if _sw_result:
                ctx["script_result"] = _sw_result["script_result"]
                ctx["script_wf"] = _sw_result["script_wf"]
            else:
                ctx["script_result"] = await _facade().run_script_agent_job(
                    db=ctx["db"],
                    user_id=ctx["user_id"],
                    session_id=f"{ctx['sid']}-employee-script",
                    brief=ctx["script_brief"],
                    files=ctx["employee_files"],
                    provider=ctx["prov"],
                    model=ctx["mdl"],
                    system_hint=ctx["script_hint"],
                    status_hook=_script_progress,
                )
                ctx["script_wf"] = None
                if ctx["script_result"].get("ok") and (not ctx["script_result"].get("errors")):
                    ctx["script_wf"] = _facade()._commit_script_workflow_from_result(
                        ctx["db"],
                        user_id=ctx["user_id"],
                        session_id=ctx["sid"],
                        payload={
                            **ctx["payload"],
                            "brief": ctx["script_brief"],
                            "workflow_name": ctx["planned_script_name"]
                            or ctx["wf_name"]
                            or ctx["res"].get("id")
                            or "员工配套",
                        },
                        files=ctx["employee_files"],
                        result=ctx["script_result"],
                    )
            if not ctx["script_wf"]:
                if ctx["script_result"].get("ok"):
                    _script_err_parts = []
                    if not str(ctx["script_result"].get("script") or "").strip():
                        _script_err_parts.append("脚本代码为空")
                    if ctx["script_result"].get("errors"):
                        _script_err_parts.append(
                            "；".join(
                                (str(ctx["e"]) for ctx["e"] in ctx["script_result"]["errors"][:3])
                            )
                        )
                    _skip_reason = (
                        "；".join(_script_err_parts)
                        if _script_err_parts
                        else "未能生成可保存的脚本工作流"
                    )
                    await _facade()._set_step(
                        ctx["sid"],
                        "script_workflow",
                        "skipped",
                        f"已跳过：{_skip_reason}",
                    )
                    _facade()._LOG.warning(
                        "pipeline: script_wf=None but ok=True — skipping, reason=%s session=%s",
                        _skip_reason,
                        ctx["sid"],
                    )
                else:
                    _script_err = (
                        "；".join(
                            (
                                str(ctx["e"])
                                for ctx["e"] in (ctx["script_result"].get("errors") or [])[:3]
                            )
                        )
                        or "脚本执行失败"
                    )
                    ctx["msg"] = f"脚本运行失败：{_script_err}"
                    await _facade()._set_step(
                        ctx["sid"], "script_workflow", "error", ctx["msg"][:300]
                    )
                    await _facade()._fail_session(ctx["sid"], "script_workflow", ctx["msg"][:1000])
                    return True
            else:
                await _facade()._set_step(
                    ctx["sid"],
                    "script_workflow",
                    "done",
                    f"已生成脚本工作流 id={ctx['script_wf'].get('id')}",
                )
        else:
            await _facade()._set_step(
                ctx["sid"], "script_workflow", "skipped", "已跳过：未开启配套小程序"
            )
    if ctx["_should_skip"]("embed_script"):
        await _facade()._set_step(ctx["sid"], "embed_script", "done", "已完成（重试复用）")
    else:
        ctx["wf_attach"]: _facade().Dict[str, _facade().Any] = {}
        ctx["saved_package"]: _facade().Dict[str, _facade().Any] = ctx["res"].get("package") or {}
        ctx["published_to_catalog"] = False
        ctx["_emp_current_step"] = "embed_script"
        if ctx["embed_script_workflow"] and ctx["script_wf"]:
            await _facade()._set_step(
                ctx["sid"], "embed_script", "running", "正在把配套小程序绑定到员工能力"
            )
            _es_result = await _facade()._dispatch_craft_step(
                "embed_script",
                pack_dir=ctx["pack_dir"],
                script_wf=ctx["script_wf"],
                brief=ctx["script_brief"],
                db=ctx["db"],
                published_to_catalog=ctx["published_to_catalog"],
                user=ctx["user"],
            )
            if _es_result:
                ctx["script_attachment"] = _es_result["script_attachment"]
                if _es_result.get("saved_package"):
                    ctx["saved_package"] = _es_result["saved_package"]
            else:
                ctx["script_attachment"] = _facade()._embed_script_workflow_in_employee_pack(
                    ctx["pack_dir"],
                    script_workflow=ctx["script_wf"],
                    brief=ctx["script_brief"],
                    db=ctx["db"],
                )
                if ctx["published_to_catalog"]:
                    ctx["saved_package"] = _facade()._refresh_employee_pack_catalog_zip(
                        ctx["db"], ctx["user"], ctx["pack_dir"]
                    )
            await _facade()._set_step(
                ctx["sid"],
                "embed_script",
                "done",
                f"已写入脚本工作流 id={ctx['script_attachment'].get('script_workflow_id')}",
            )
        else:
            if ctx["_use_word_extract_pipeline"]:
                _embed_skip = "Word direct_python 模式：无需脚本工作流绑定"
            elif not ctx["script_wf"]:
                _embed_skip = "已跳过绑定：未生成配套脚本工作流"
            else:
                _embed_skip = "已跳过绑定：未开启 embed_script_workflow"
            await _facade()._set_step(ctx["sid"], "embed_script", "skipped", _embed_skip)
    if ctx["_should_skip"]("workflow"):
        await _facade()._set_step(ctx["sid"], "workflow", "done", "已完成（重试复用）")
    else:
        ctx["_emp_current_step"] = "workflow"
        await _facade()._set_step(ctx["sid"], "workflow", "running", "正在创建自动化流程…")

        async def _emp_wf_msg(text: str) -> None:
            await _facade()._set_step(ctx["sid"], "workflow", "running", text)

        if ctx["et"] == "pack_plus_workflow":
            _wf_result = await _facade()._dispatch_craft_step(
                "workflow",
                db=ctx["db"],
                user=ctx["user"],
                pack_dir=ctx["pack_dir"],
                brief=ctx["workflow_brief"],
                workflow_name=ctx["wf_name"] or ctx["planned_workflow_name"],
                provider=ctx["prov"],
                model=ctx["mdl"],
                published_to_catalog=ctx["published_to_catalog"],
                status_hook=_emp_wf_msg,
            )
            if _wf_result:
                ctx["wf_attach"] = _wf_result["wf_attach"]
                if _wf_result.get("saved_package"):
                    ctx["saved_package"] = _wf_result["saved_package"]
            else:
                ctx["wf_attach"] = await _facade().attach_nl_workflow_to_employee_pack_dir(
                    ctx["db"],
                    ctx["user"],
                    pack_dir=ctx["pack_dir"],
                    brief=ctx["workflow_brief"],
                    workflow_name=ctx["wf_name"] or ctx["planned_workflow_name"],
                    provider=ctx["prov"],
                    model=ctx["mdl"],
                    status_hook=_emp_wf_msg,
                )
                if ctx["published_to_catalog"]:
                    ctx["saved_package"] = _facade()._refresh_employee_pack_catalog_zip(
                        ctx["db"], ctx["user"], ctx["pack_dir"]
                    )
            _eskill_n = int(ctx["wf_attach"].get("eskill_count") or 0)
            _nl_ok = (ctx["wf_attach"].get("nl") or {}).get("ok")
            if _eskill_n:
                wmsg = f"已创建工作流 id={ctx['wf_attach'].get('workflow_id')}；注入 {_eskill_n} 个真脚本 Skill，NL 编排{('成功' if _nl_ok else '有提示')}"
            else:
                wmsg = f"已创建工作流 id={ctx['wf_attach'].get('workflow_id')}；NL 生图{('成功' if _nl_ok else '有提示')}"
            await _facade()._set_step(ctx["sid"], "workflow", "done", wmsg[:480])
        else:
            await _facade()._set_step(
                ctx["sid"],
                "workflow",
                "skipped",
                "已跳过：当前为「仅员工包」模式；若需画布请选 pack_plus_workflow 并重新编排",
            )
    return False
