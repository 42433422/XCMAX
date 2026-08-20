# mypy: disable-error-code="type-arg"
# isort: skip_file
"""Employee build pipeline phase."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_employee_pipeline_phase_07(ctx: dict[str]) -> bool:
    if (
        ctx["_emp_reg_zero_warning"]
        and ctx["res"].get("manifest")
        and isinstance(ctx["res"].get("manifest"), dict)
    ):
        try:
            await _facade()._set_step(
                ctx["sid"], "complete", "running", "登记未通过，正在重试 manifest 对齐…"
            )

            _retry_mf = ctx["res"]["manifest"]
            _retry_pid = str(_retry_mf.get("id") or ctx["res"].get("id") or "").strip()
            if _retry_pid and ctx["pack_dir"].is_dir():
                ctx["_raw_mf"] = _facade().json.loads(
                    (ctx["pack_dir"] / "manifest.json").read_text(encoding="utf-8")
                )
                ctx["_aligned_mf"], ctx["_"] = ctx["normalize_editor_manifest_for_registry"](
                    ctx["_raw_mf"], _retry_pid
                )
                (ctx["pack_dir"] / "manifest.json").write_text(
                    _facade().json.dumps(ctx["_aligned_mf"], ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                ctx["_emp_reg_zero_warning"] = False
                for qi in ctx["_quality_items"]:
                    if qi["check"] == "员工包登记":
                        qi["ok"] = True
                        qi["note"] = "重试 manifest 对齐成功（未自动上架）"
        except RECOVERABLE_ERRORS as _retry_exc:
            _facade()._LOG.warning(
                "register_pack local retry failed session=%s: %s",
                ctx["sid"],
                _retry_exc,
            )
            for qi in ctx["_quality_items"]:
                if qi["check"] == "员工包登记":
                    qi["note"] = f"重试失败: {_retry_exc!s}"[:120]
    _quality_pass = sum((1 for ctx["q"] in ctx["_quality_items"] if ctx["q"].get("ok") is True))
    _quality_total = sum(
        (1 for ctx["q"] in ctx["_quality_items"] if ctx["q"].get("ok") is not None)
    )
    _quality_warn = sum((1 for ctx["q"] in ctx["_quality_items"] if ctx["q"].get("ok") is False))
    _quality_skip = sum((1 for ctx["q"] in ctx["_quality_items"] if ctx["q"].get("ok") is None))
    _quality_score = round(_quality_pass / _quality_total * 100, 1) if _quality_total else 0.0
    _complete_msg_parts = [
        f"质量报告：{_quality_pass}/{_quality_total} 通过（{_quality_score} 分）"
    ]
    if ctx["_six_dimension_report"]:
        _complete_msg_parts.insert(
            0,
            f"六维综合 {ctx['_six_dimension_report'].get('overall_score', 0)} 分"
            + ("（达标）" if ctx["_six_dimension_report"].get("passed") else "（未达标）"),
        )
    if ctx["_pipeline_label"] == "word_full_extract":
        _complete_msg_parts.append(
            "可提取 Word：" + ("是" if ctx["_runnable"] else "否（handlers/convert 未对齐）")
        )
    if _quality_warn:
        _complete_msg_parts.append(f"{_quality_warn} 项需关注")
    if _quality_skip:
        _complete_msg_parts.append(f"{_quality_skip} 项跳过")
    _failed_checks = [
        ctx["q"]["check"] for ctx["q"] in ctx["_quality_items"] if ctx["q"].get("ok") is False
    ]
    if _failed_checks:
        _complete_msg_parts.append("⚠️ 未通过：" + "、".join(_failed_checks))
    _complete_msg_parts.append("下一步：在画布中编辑员工配置 → 部署到宿主 → 真实业务验证")
    _complete_status = "error" if ctx["_critical_failed"] else "done"
    if ctx["_critical_failed"]:
        _complete_msg_parts.insert(0, "⚠️ 关键质量项未通过，员工包不可用")
    await _facade()._set_step(
        ctx["sid"], "complete", _complete_status, "；".join(_complete_msg_parts)[:480]
    )
    if ctx["_critical_failed"]:
        await _facade()._fail_session(
            ctx["sid"], "complete", "；".join(ctx["_failed_critical"])[:1000]
        )
        return True
    async with _facade()._SESSION_LOCK:
        ctx["sess"] = _facade().WORKBENCH_SESSIONS.get(ctx["sid"])
        if ctx["sess"]:
            ctx["sess"]["sandbox_report"] = {
                "workflow": ctx["workflow_sandbox"],
                "mod": ctx["emp_mod_sandbox"],
            }
            ctx["sess"]["quality_report"] = {
                "items": ctx["_quality_items"],
                "pass": _quality_pass,
                "total": _quality_total,
                "warnings": _quality_warn,
                "skipped": _quality_skip,
                "failed_checks": _failed_checks,
                "score": _quality_score,
                "pipeline_label": ctx["_pipeline_label"],
                "runnable": ctx["_runnable"],
                "critical_failed": ctx["_critical_failed"],
                "six_dimension_report": ctx["_six_dimension_report"] or None,
            }
            if ctx["_six_dimension_report"]:
                ctx["sess"]["six_dimension_report"] = ctx["_six_dimension_report"]
            _facade()._persist_workbench_session_unlocked(ctx["sid"])
    _pack_id_final = str(ctx["res"].get("id") or "")
    try:
        ctx["cleanup_experimental_pack"](
            _pack_id_final,
            metadata=ctx["payload"] if isinstance(ctx["payload"], dict) else None,
        )
    except RECOVERABLE_ERRORS as _clean_exc:
        _facade()._LOG.warning(
            "experimental pack cleanup failed session=%s pack=%s: %s",
            ctx["sid"],
            _pack_id_final,
            _clean_exc,
        )
    await _facade()._finalize_session_done(
        ctx["sid"],
        {
            "pack_id": ctx["res"]["id"],
            "employee_id": ctx["res"]["id"],
            "manifest_employee_id": ctx["res"]["id"],
            "name": (ctx["res"].get("manifest") or {}).get("name"),
            "description": (ctx["res"].get("manifest") or {}).get("description"),
            "workflow_id": ctx["wid"],
            "package": ctx["saved_package"],
            "workflow_sandbox": ctx["workflow_sandbox"],
            "mod_sandbox": ctx["emp_mod_sandbox"],
            "employee_target": ctx["et"],
            "employee_orchestration_plan": ctx["employee_plan"],
            "workflow_attachment": ctx["wf_attach"],
            "script_workflow": ctx["script_wf"],
            "script_workflow_attachment": ctx["script_attachment"],
            "host_probe": ctx["host_probe"],
            "quality_report": {
                "items": ctx["_quality_items"],
                "pass": _quality_pass,
                "total": _quality_total,
                "warnings": _quality_warn,
                "skipped": _quality_skip,
                "failed_checks": _failed_checks,
                "score": _quality_score,
                "pipeline_label": ctx["_pipeline_label"],
                "runnable": ctx["_runnable"],
                "critical_failed": ctx["_critical_failed"],
                "six_dimension_report": ctx["_six_dimension_report"] or None,
            },
            "six_dimension_report": ctx["_six_dimension_report"] or None,
            "runtime_generation": ctx["res"].get("runtime_generation"),
            "domain_smoke": ctx["res"].get("domain_smoke"),
            "golden_comparison": ctx["res"].get("golden_comparison"),
            "rule_spec": ctx["res"].get("rule_spec"),
            "validation_summary": {
                "ok": bool(ctx["emp_mod_sandbox"].get("ok")) and (not ctx["_emp_reg_zero_warning"]),
                "mod_sandbox": ctx["emp_mod_sandbox"],
                "workflow_skipped": not bool(ctx["wid"]),
                "standalone_smoke_ok": ctx["_standalone_smoke_ok"],
                "register_ok": not ctx["_emp_reg_zero_warning"],
            },
        },
    )
    return False
