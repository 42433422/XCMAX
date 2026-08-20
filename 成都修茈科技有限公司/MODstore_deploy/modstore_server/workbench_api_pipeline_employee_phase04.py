# mypy: disable-error-code="attr-defined, misc, no-any-return, type-arg, valid-type"
# isort: skip_file
"""Employee build pipeline phase."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_employee_pipeline_phase_04(ctx: dict[str]) -> bool:
    if ctx["_should_skip"]("register_pack"):
        await _facade()._set_step(ctx["sid"], "register_pack", "done", "已完成（重试复用）")
    elif ctx["et"] == "pack_plus_workflow" and (
        not (
            isinstance(ctx["wf_attach"], dict)
            and (
                ctx["wf_attach"].get("automation_complete")
                or (ctx["wf_attach"].get("ok") and ctx["wf_attach"].get("workflow_id"))
            )
        )
    ):
        _reg_upstream = "workflow-automator 未完成（缺少 automation_complete / workflow_id），已拒收登记并退回上游"
        await _facade()._set_step(ctx["sid"], "register_pack", "error", _reg_upstream[:480])
        await _facade()._fail_session(ctx["sid"], "register_pack", _reg_upstream[:1000])
    else:
        ctx["_emp_current_step"] = "register_pack"
        await _facade()._set_step(ctx["sid"], "register_pack", "running", "正在保存员工包到本地库…")
        ctx["_emp_reg_zero_warning"] = False
        try:
            _emp_mf = ctx["res"].get("manifest") if isinstance(ctx["res"], dict) else None
            _emp_pack_id = str(ctx["res"].get("id") or (_emp_mf or {}).get("id") or "").strip()
            if _emp_pack_id and ctx["pack_dir"].is_dir():
                ctx["reconcile_employee_pack_manifest"](
                    ctx["pack_dir"], brief=ctx["employee_brief"]
                )
                ctx["_raw_mf"] = _facade().json.loads(
                    (ctx["pack_dir"] / "manifest.json").read_text(encoding="utf-8")
                )
                ctx["_aligned_mf"], _align_errs = ctx["normalize_editor_manifest_for_registry"](
                    ctx["_raw_mf"], _emp_pack_id
                )
                (ctx["pack_dir"] / "manifest.json").write_text(
                    _facade().json.dumps(ctx["_aligned_mf"], ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                ctx["reconcile_employee_pack_manifest"](
                    ctx["pack_dir"], brief=ctx["employee_brief"]
                )
                if ctx["_use_word_extract_pipeline"]:
                    _reg_wx_errs, ctx["_"] = ctx["validate_word_extract_backend"](ctx["pack_dir"])
                    if _reg_wx_errs:
                        _reg_fail = "登记前 Word runtime 未就绪：" + "；".join(_reg_wx_errs[:3])
                        await _facade()._set_step(
                            ctx["sid"], "register_pack", "error", _reg_fail[:480]
                        )
                        await _facade()._fail_session(ctx["sid"], "register_pack", _reg_fail[:1000])
                        return True
                try:
                    ctx["saved_package"] = _facade()._refresh_employee_pack_catalog_zip(
                        ctx["db"], ctx["user"], ctx["pack_dir"]
                    )
                    ctx["published_to_catalog"] = True
                    _reg_msg = (
                        f"员工包已保存并登记至目录（{_emp_pack_id}）；可在「员工制作」左侧列表查看"
                    )
                except RECOVERABLE_ERRORS as _cat_exc:
                    _facade()._LOG.warning(
                        "register_pack catalog sync failed session=%s pack=%s: %s",
                        ctx["sid"],
                        _emp_pack_id,
                        _cat_exc,
                    )
                    _reg_msg = f"目录登记失败：{_cat_exc!s}"[:480]
                    await _facade()._set_step(ctx["sid"], "register_pack", "error", _reg_msg)
                    await _facade()._fail_session(ctx["sid"], "register_pack", _reg_msg[:1000])
                    return True
                await _facade()._set_step(ctx["sid"], "register_pack", "done", _reg_msg[:480])
            else:
                ctx["_emp_reg_zero_warning"] = True
                ctx["msg"] = "未找到有效包 ID 或包目录，员工包未保存——请确认 manifest.id"
                await _facade()._set_step(ctx["sid"], "register_pack", "error", ctx["msg"][:480])
                await _facade()._fail_session(ctx["sid"], "register_pack", ctx["msg"][:1000])
                return True
        except RECOVERABLE_ERRORS as _reg_exc:
            _facade()._LOG.exception(
                "register_pack failed for employee session=%s: %s", ctx["sid"], _reg_exc
            )
            ctx["_emp_reg_zero_warning"] = True
            ctx["msg"] = f"保存异常: {_reg_exc!s}"
            await _facade()._set_step(ctx["sid"], "register_pack", "error", ctx["msg"][:480])
            await _facade()._fail_session(ctx["sid"], "register_pack", ctx["msg"][:1000])
            return True
    if ctx["_should_skip"]("workflow_sandbox"):
        await _facade()._set_step(ctx["sid"], "workflow_sandbox", "done", "已完成（重试复用）")
    else:
        ctx["_emp_current_step"] = "workflow_sandbox"
        await _facade()._set_step(
            ctx["sid"], "workflow_sandbox", "running", "工作流结构校验（validate_only）"
        )
        ctx["workflow_sandbox"]: _facade().Dict[str, _facade().Any]
        wid_raw = (
            ctx["wf_attach"].get("workflow_id") if isinstance(ctx["wf_attach"], dict) else None
        )
        try:
            wid_int = int(wid_raw) if wid_raw is not None else 0
        except (TypeError, ValueError):
            wid_int = 0
        if ctx["et"] == "pack_plus_workflow" and wid_int <= 0:
            from modstore_server.craft_failure_signals import (
                invalid_workflow_sandbox_report,
            )

            _wf_invalid_msg = "输入 workflow_id 无效：pack-registrar / workflow-automator 须先创建画布工作流并写入 wf_attach.workflow_id"
            report = invalid_workflow_sandbox_report(wid_raw)
            ctx["workflow_sandbox"] = {
                "ok": False,
                "skipped": False,
                "workflow_id": wid_raw,
                "reports": [report],
                "business_tested": False,
                "summary": report.get("summary") or "输入 workflow_id 无效",
            }
            await _facade()._set_step(
                ctx["sid"], "workflow_sandbox", "error", _wf_invalid_msg[:480]
            )
            await _facade()._fail_session(ctx["sid"], "workflow_sandbox", _wf_invalid_msg[:1000])
            return True
        if ctx["et"] == "pack_plus_workflow" and wid_int > 0:
            ctx["wid"] = wid_int
            _ws_result = await _facade()._dispatch_craft_step(
                "workflow_sandbox",
                workflow_id=ctx["wid"],
                brief=ctx["brief"] or "测试任务",
                user_id=ctx["user"].id,
                db=ctx["db"],
            )
            if _ws_result and isinstance(_ws_result.get("report"), dict):
                report = _ws_result["report"]
            elif _ws_result is None:
                report = _facade().run_workflow_sandbox(
                    ctx["wid"],
                    {},
                    mock_employees=True,
                    validate_only=True,
                    user_id=ctx["user"].id,
                )
            else:
                report = (
                    _ws_result.get("report")
                    if isinstance(_ws_result.get("report"), dict)
                    else _facade().run_workflow_sandbox(
                        ctx["wid"],
                        {},
                        mock_employees=True,
                        validate_only=True,
                        user_id=ctx["user"].id,
                    )
                )
            _facade().record_workflow_sandbox_run(
                ctx["db"],
                workflow_id=int(ctx["wid"]),
                user_id=ctx["user"].id,
                report=report,
                validate_only=True,
                mock_employees=True,
            )
            ctx["workflow_sandbox"] = {
                "ok": bool(report.get("ok")),
                "skipped": False,
                "workflow_id": int(ctx["wid"]),
                "reports": [report],
                "business_tested": False,
                "note": "仅验证了工作流图结构完整性，未执行真实员工业务逻辑",
            }
            if report.get("ok"):
                await _facade()._set_step(
                    ctx["sid"],
                    "workflow_sandbox",
                    "running",
                    "结构校验通过，正在执行真实员工调用验证…",
                )
                _biz_pack_id = str(
                    ctx["res"].get("id")
                    or (
                        ctx["res"].get("manifest") or {}
                        if isinstance(ctx["res"].get("manifest"), dict)
                        else {}
                    ).get("id")
                    or ctx["pack_dir"].name
                ).strip()
                if not _facade()._assert_employee_catalog_registered(ctx["db"], _biz_pack_id):
                    try:
                        _facade()._refresh_employee_pack_catalog_zip(
                            ctx["db"], ctx["user"], ctx["pack_dir"]
                        )
                        ctx["published_to_catalog"] = True
                    except RECOVERABLE_ERRORS as _cat_retry_exc:
                        _facade()._LOG.warning(
                            "workflow_sandbox catalog retry failed: %s", _cat_retry_exc
                        )
                if not _facade()._assert_employee_catalog_registered(ctx["db"], _biz_pack_id):
                    ctx["_wf_sandbox_biz_ok"] = False
                    _wf_sb_msg = (
                        f"结构校验通过 ✅，真实调用验证失败：员工包未登记（{_biz_pack_id}）"
                    )
                    if ctx["_pipeline_label"] in (
                        "word_full_extract",
                        "txt_full_read",
                        "txt_generate",
                    ):
                        await _facade()._set_step(
                            ctx["sid"], "workflow_sandbox", "error", _wf_sb_msg[:480]
                        )
                        await _facade()._fail_session(
                            ctx["sid"], "workflow_sandbox", _wf_sb_msg[:1000]
                        )
                        return True
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
                            "task": ctx["_routing_brief"] or ctx["brief"] or "测试任务"
                        }
                        if ctx["_pipeline_label"] == "word_full_extract":
                            _biz_input["files"] = [
                                {
                                    "filename": "smoke.docx",
                                    "content_base64": minimal_docx_fixture_b64(),
                                }
                            ]
                        elif ctx["_pipeline_label"] in (
                            "txt_full_read",
                            "txt_generate",
                        ):
                            _biz_input["files"] = [
                                {
                                    "filename": "smoke.txt",
                                    "content_base64": _b64mod.b64encode(
                                        minimal_txt_fixture_bytes()
                                    ).decode("ascii"),
                                }
                            ]
                        biz_report = _facade().run_workflow_sandbox(
                            int(ctx["wid"]),
                            _biz_input,
                            mock_employees=False,
                            validate_only=False,
                            user_id=ctx["user"].id,
                        )
                        _facade().record_workflow_sandbox_run(
                            ctx["db"],
                            workflow_id=int(ctx["wid"]),
                            user_id=ctx["user"].id,
                            report=biz_report,
                            validate_only=False,
                            mock_employees=False,
                        )
                        ctx["workflow_sandbox"]["reports"].append(biz_report)
                        ctx["workflow_sandbox"]["business_tested"] = True
                        if biz_report.get("ok"):
                            ctx["workflow_sandbox"]["ok"] = True
                            ctx["_wf_sandbox_biz_ok"] = True
                            _wf_sb_msg = "结构校验通过 ✅ + 真实员工调用验证通过 ✅"
                        else:
                            ctx["_wf_sandbox_biz_ok"] = False
                            _biz_errs = biz_report.get("errors") or []
                            _biz_warns = biz_report.get("warnings") or []
                            _wf_sb_msg = f"结构校验通过 ✅，真实调用验证有提示（{len(_biz_errs)} 错误，{len(_biz_warns)} 警告）"
                            if _biz_errs:
                                _wf_sb_msg += "；" + "；".join(
                                    (str(ctx["e"])[:100] for ctx["e"] in _biz_errs[:2])
                                )
                            if ctx["_pipeline_label"] in (
                                "word_full_extract",
                                "txt_full_read",
                                "txt_generate",
                            ):
                                await _facade()._set_step(
                                    ctx["sid"],
                                    "workflow_sandbox",
                                    "error",
                                    _wf_sb_msg[:480],
                                )
                                await _facade()._fail_session(
                                    ctx["sid"], "workflow_sandbox", _wf_sb_msg[:1000]
                                )
                                return True
                    except RECOVERABLE_ERRORS as _biz_exc:
                        ctx["workflow_sandbox"]["business_tested"] = True
                        ctx["_wf_sandbox_biz_ok"] = False
                        _wf_sb_msg = f"结构校验通过 ✅，真实调用验证异常：{_biz_exc!s}"[:300]
                        if ctx["_pipeline_label"] in (
                            "word_full_extract",
                            "txt_full_read",
                            "txt_generate",
                        ):
                            await _facade()._set_step(
                                ctx["sid"],
                                "workflow_sandbox",
                                "error",
                                _wf_sb_msg[:480],
                            )
                            await _facade()._fail_session(
                                ctx["sid"], "workflow_sandbox", _wf_sb_msg[:1000]
                            )
                            return True
            else:
                _wf_sb_msg = "结构校验有提示，请进画布查看"
            await _facade()._set_step(ctx["sid"], "workflow_sandbox", "done", _wf_sb_msg)
        else:
            wf_skip_msg = "已跳过结构校验：未创建画布工作流或模式为仅员工包。如需工作流结构校验，请选择 pack_plus_workflow 模式。"
            ctx["workflow_sandbox"] = {
                "ok": True,
                "skipped": True,
                "reason": wf_skip_msg,
                "reports": [],
                "business_tested": False,
            }
            await _facade()._set_step(ctx["sid"], "workflow_sandbox", "skipped", wf_skip_msg[:520])
    return False
