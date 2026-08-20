# mypy: disable-error-code="attr-defined, misc, no-any-return, type-arg, valid-type"
# isort: skip_file
"""Employee build pipeline phase."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_employee_pipeline_phase_06(ctx: dict[str]) -> bool:
    ctx["_six_dimension_report"]: _facade().Dict[str, _facade().Any] = {}
    if ctx["_should_skip"]("six_dim_gate"):
        await _facade()._set_step(ctx["sid"], "six_dim_gate", "done", "已完成（重试复用）")
    else:
        ctx["_emp_current_step"] = "six_dim_gate"
        await _facade()._set_step(ctx["sid"], "six_dim_gate", "running", "正在汇总六维质量分数…")
        _asset_n = 0
        if isinstance(ctx["res"].get("asset_manifest"), dict):
            _asset_n = len((ctx["res"].get("asset_manifest") or {}).get("assets") or [])
        async with _facade()._SESSION_LOCK:
            _sess_sd = _facade().WORKBENCH_SESSIONS.get(ctx["sid"]) or {}
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
            pack_dir=ctx["pack_dir"],
            pipeline_label=ctx["_pipeline_label"],
            routing_brief=ctx["_routing_brief"],
            structured_requirement=_struct_sd,
            spec_warnings=_spec_warn_sd,
            validate_errors=_val_err_sd,
            mod_sandbox=ctx["emp_mod_sandbox"] if isinstance(ctx["emp_mod_sandbox"], dict) else {},
            workflow_sandbox=(
                ctx["workflow_sandbox"] if isinstance(ctx["workflow_sandbox"], dict) else {}
            ),
            workflow_biz_ok=ctx["_wf_sandbox_biz_ok"],
            standalone_smoke_ok=ctx["_standalone_smoke_ok"],
            catalog_registered=not ctx["_emp_reg_zero_warning"],
            employee_target=ctx["et"],
            asset_count=_asset_n,
            domain_smoke=(
                ctx["res"].get("domain_smoke")
                if isinstance(ctx["res"].get("domain_smoke"), dict)
                else None
            ),
            golden_comparison=(
                ctx["res"].get("golden_comparison")
                if isinstance(ctx["res"].get("golden_comparison"), dict)
                else None
            ),
            runtime_generation=(
                ctx["res"].get("runtime_generation")
                if isinstance(ctx["res"].get("runtime_generation"), dict)
                else None
            ),
        )
        if _sd_result and _sd_result.get("six_dimension_report"):
            ctx["_six_dimension_report"] = _sd_result["six_dimension_report"]
        else:
            from modstore_server.employee_six_dimension import (
                compute_six_dimension_report,
            )

            ctx["_six_dimension_report"] = compute_six_dimension_report(
                pack_dir=ctx["pack_dir"],
                pipeline_label=ctx["_pipeline_label"],
                routing_brief=ctx["_routing_brief"],
                structured_requirement=_struct_sd,
                spec_warnings=_spec_warn_sd,
                validate_errors=_val_err_sd,
                mod_sandbox=(
                    ctx["emp_mod_sandbox"] if isinstance(ctx["emp_mod_sandbox"], dict) else {}
                ),
                workflow_sandbox=(
                    ctx["workflow_sandbox"] if isinstance(ctx["workflow_sandbox"], dict) else {}
                ),
                workflow_biz_ok=ctx["_wf_sandbox_biz_ok"],
                standalone_smoke_ok=ctx["_standalone_smoke_ok"],
                catalog_registered=not ctx["_emp_reg_zero_warning"],
                employee_target=ctx["et"],
                asset_count=_asset_n,
                domain_smoke=(
                    ctx["res"].get("domain_smoke")
                    if isinstance(ctx["res"].get("domain_smoke"), dict)
                    else None
                ),
                golden_comparison=(
                    ctx["res"].get("golden_comparison")
                    if isinstance(ctx["res"].get("golden_comparison"), dict)
                    else None
                ),
                runtime_generation=(
                    ctx["res"].get("runtime_generation")
                    if isinstance(ctx["res"].get("runtime_generation"), dict)
                    else None
                ),
            )
        _sd_pass = bool(ctx["_six_dimension_report"].get("passed"))
        _sd_overall = float(ctx["_six_dimension_report"].get("overall_score") or 0)
        _sd_failed = ctx["_six_dimension_report"].get("failed_dimensions") or []
        _sd_msg = f"六维评估 {_sd_overall} 分"
        if _sd_pass:
            _sd_msg += "；6/6 维达标，可在完成步查看雷达图"
        else:
            from modstore_server.employee_six_dimension import DIMENSION_LABELS_ZH

            _sd_msg += (
                "；未通过："
                + "、".join(
                    (DIMENSION_LABELS_ZH.get(ctx["k"], ctx["k"]) for ctx["k"] in _sd_failed[:4])
                )
                if _sd_failed
                else "综合分未达标"
            )
        await _facade()._set_step(
            ctx["sid"],
            "six_dim_gate",
            "error" if ctx["_six_dimension_report"].get("critical_failed") else "done",
            _sd_msg[:480],
        )
        if ctx["_six_dimension_report"].get("critical_failed"):
            await _facade()._fail_session(ctx["sid"], "six_dim_gate", _sd_msg[:1000])
            return True
    ctx["_emp_current_step"] = "complete"
    ctx["_quality_items"]: _facade().List[_facade().Dict[str, _facade().Any]] = []
    ctx["_quality_items"].append(
        {"check": "manifest 校验", "ok": bool(ctx["emp_mod_sandbox"].get("ok"))}
    )
    ctx["_quality_items"].append(
        {"check": "Python 编译", "ok": ctx["emp_mod_sandbox"].get("ok", False)}
    )
    ctx["_quality_items"].append(
        {
            "check": "工作流结构校验",
            "ok": ctx["workflow_sandbox"].get("ok", False),
            "note": (
                "仅结构，未测业务"
                if not ctx["workflow_sandbox"].get("business_tested", True)
                else ""
            ),
        }
    )
    if ctx["_wf_sandbox_biz_ok"] is not None:
        ctx["_quality_items"].append(
            {
                "check": "工作流真实调用",
                "ok": bool(ctx["_wf_sandbox_biz_ok"]),
                "critical": ctx["_pipeline_label"]
                in ("word_full_extract", "txt_full_read", "txt_generate"),
            }
        )
    ctx["_quality_items"].append(
        {
            "check": "独立包自检",
            "ok": ctx["_standalone_smoke_ok"],
            "critical": ctx["_pipeline_label"]
            in ("word_full_extract", "txt_full_read", "txt_generate"),
        }
    )
    ctx["_quality_items"].append(
        {
            "check": "员工包登记",
            "ok": not ctx["_emp_reg_zero_warning"],
            "critical": True,
        }
    )
    _host_note = "已跳过"
    if ctx["host_probe"].get("skipped") and ctx["_pipeline_label"] in (
        "word_full_extract",
        "txt_full_read",
        "txt_generate",
    ):
        _host_note = "本地文件转换无需宿主"
    ctx["_quality_items"].append(
        {
            "check": "宿主连通性",
            "ok": ctx["host_probe"].get("ok") if not ctx["host_probe"].get("skipped") else None,
            "note": _host_note if ctx["host_probe"].get("skipped") else "",
        }
    )
    _sess_validate_errors: _facade().List[str] = []
    async with _facade()._SESSION_LOCK:
        _sess_q = _facade().WORKBENCH_SESSIONS.get(ctx["sid"]) or {}
        _ve = _sess_q.get("validate_errors")
        if isinstance(_ve, list):
            _sess_validate_errors = [str(ctx["x"]) for ctx["x"] in _ve if ctx["x"]]
    _extra_items, ctx["_runnable"], ctx["_critical_failed"] = _facade()._employee_quality_extras(
        ctx["pack_dir"],
        pipeline_label=ctx["_pipeline_label"],
        validate_errors=_sess_validate_errors,
        mod_sandbox=ctx["emp_mod_sandbox"] if isinstance(ctx["emp_mod_sandbox"], dict) else {},
        runtime_generation=(
            ctx["res"].get("runtime_generation")
            if isinstance(ctx["res"].get("runtime_generation"), dict)
            else {}
        ),
        domain_smoke=(
            ctx["res"].get("domain_smoke")
            if isinstance(ctx["res"].get("domain_smoke"), dict)
            else {}
        ),
        golden_comparison=(
            ctx["res"].get("golden_comparison")
            if isinstance(ctx["res"].get("golden_comparison"), dict)
            else {}
        ),
    )
    ctx["_quality_items"].extend(_extra_items)
    ctx["_failed_critical"] = [
        ctx["q"]["check"]
        for ctx["q"] in ctx["_quality_items"]
        if ctx["q"].get("ok") is False and ctx["q"].get("critical")
    ]
    if ctx["_failed_critical"]:
        ctx["_critical_failed"] = True
        ctx["_runnable"] = False
    if ctx["_six_dimension_report"] and ctx["_six_dimension_report"].get("critical_failed"):
        ctx["_critical_failed"] = True
        ctx["_runnable"] = False
    return False
