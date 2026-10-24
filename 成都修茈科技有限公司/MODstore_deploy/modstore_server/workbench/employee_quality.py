"""Employee quality for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, List, cast

from modstore_server.workbench.employee_state import EmployeeBuildState
from modstore_server.workbench.sessions import ProgressCallbacks, SessionStore

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeeQualityPorts:
    sessions: SessionStore
    progress: ProgressCallbacks
    craft_step: Callable[..., Awaitable[dict[str, Any] | None]]
    quality_extras: Callable[..., tuple[list[dict[str, Any]], bool, bool]]


async def evaluate_employee_quality(
    state: EmployeeBuildState, *, ports: EmployeeQualityPorts
) -> bool:
    state.six_dimension_report = {}
    if state.should_skip("six_dim_gate"):
        await ports.progress.set_step(
            state.session_id, "six_dim_gate", "done", "已完成（重试复用）"
        )
    else:
        state.current_step = "six_dim_gate"
        await ports.progress.set_step(
            state.session_id, "six_dim_gate", "running", "正在汇总六维质量分数…"
        )
        _asset_n = 0
        if isinstance(state.result.get("asset_manifest"), dict):
            _asset_n = len((state.result.get("asset_manifest") or {}).get("assets") or [])
        async with ports.sessions.lock:
            _sess_sd = ports.sessions.data.get(state.session_id) or {}
            _spec_warn_sd = (
                cast(list[Any], _sess_sd.get("spec_warnings"))
                if isinstance(_sess_sd.get("spec_warnings"), list)
                else []
            )
            _struct_sd = (
                cast(dict[str, Any], _sess_sd.get("structured_requirement"))
                if isinstance(_sess_sd.get("structured_requirement"), dict)
                else {}
            )
            _val_err_sd = (
                cast(list[Any], _sess_sd.get("validate_errors"))
                if isinstance(_sess_sd.get("validate_errors"), list)
                else []
            )
        _sd_result = await ports.craft_step(
            "six_dim_gate",
            pack_dir=state.pack_dir,
            pipeline_label=state.pipeline_label,
            routing_brief=state.routing_brief,
            structured_requirement=_struct_sd,
            spec_warnings=_spec_warn_sd,
            validate_errors=_val_err_sd,
            mod_sandbox=(
                cast(dict[str, Any], state.package_sandbox)
                if isinstance(state.package_sandbox, dict)
                else {}
            ),
            workflow_sandbox=(
                cast(dict[str, Any], state.workflow_sandbox)
                if isinstance(state.workflow_sandbox, dict)
                else {}
            ),
            workflow_biz_ok=state.workflow_business_ok,
            standalone_smoke_ok=state.standalone_smoke_ok,
            catalog_registered=not state.registration_missing,
            employee_target=state.target,
            asset_count=_asset_n,
            domain_smoke=(
                cast(dict[str, Any], state.result.get("domain_smoke"))
                if isinstance(state.result.get("domain_smoke"), dict)
                else None
            ),
            golden_comparison=(
                cast(dict[str, Any], state.result.get("golden_comparison"))
                if isinstance(state.result.get("golden_comparison"), dict)
                else None
            ),
            runtime_generation=(
                cast(dict[str, Any], state.result.get("runtime_generation"))
                if isinstance(state.result.get("runtime_generation"), dict)
                else None
            ),
        )
        if _sd_result and _sd_result.get("six_dimension_report"):
            state.six_dimension_report = _sd_result["six_dimension_report"]
        else:
            from modstore_server.employee_six_dimension import compute_six_dimension_report

            state.six_dimension_report = compute_six_dimension_report(
                pack_dir=state.pack_dir,
                pipeline_label=state.pipeline_label,
                routing_brief=state.routing_brief,
                structured_requirement=_struct_sd,
                spec_warnings=_spec_warn_sd,
                validate_errors=_val_err_sd,
                mod_sandbox=(
                    cast(dict[str, Any], state.package_sandbox)
                    if isinstance(state.package_sandbox, dict)
                    else {}
                ),
                workflow_sandbox=(
                    cast(dict[str, Any], state.workflow_sandbox)
                    if isinstance(state.workflow_sandbox, dict)
                    else {}
                ),
                workflow_biz_ok=state.workflow_business_ok,
                standalone_smoke_ok=state.standalone_smoke_ok,
                catalog_registered=not state.registration_missing,
                employee_target=state.target,
                asset_count=_asset_n,
                domain_smoke=(
                    cast(dict[str, Any], state.result.get("domain_smoke"))
                    if isinstance(state.result.get("domain_smoke"), dict)
                    else None
                ),
                golden_comparison=(
                    cast(dict[str, Any], state.result.get("golden_comparison"))
                    if isinstance(state.result.get("golden_comparison"), dict)
                    else None
                ),
                runtime_generation=(
                    cast(dict[str, Any], state.result.get("runtime_generation"))
                    if isinstance(state.result.get("runtime_generation"), dict)
                    else None
                ),
            )
        _sd_pass = bool(state.six_dimension_report.get("passed"))
        _sd_overall = float(state.six_dimension_report.get("overall_score") or 0)
        _sd_failed = state.six_dimension_report.get("failed_dimensions") or []
        _sd_msg = f"六维评估 {_sd_overall} 分"
        if _sd_pass:
            _sd_msg += "；6/6 维达标，可在完成步查看雷达图"
        else:
            from modstore_server.employee_six_dimension_report import DIMENSION_LABELS_ZH

            _sd_msg += (
                "；未通过：" + "、".join((DIMENSION_LABELS_ZH.get(k, k) for k in _sd_failed[:4]))
                if _sd_failed
                else "综合分未达标"
            )
        await ports.progress.set_step(
            state.session_id,
            "six_dim_gate",
            "error" if state.six_dimension_report.get("critical_failed") else "done",
            _sd_msg[:480],
        )
        if state.six_dimension_report.get("critical_failed"):
            await ports.progress.fail(state.session_id, "six_dim_gate", _sd_msg[:1000])
            return True
    state.current_step = "complete"
    state.quality_items = []
    state.quality_items.append(
        {"check": "manifest 校验", "ok": bool(state.package_sandbox.get("ok"))}
    )
    state.quality_items.append(
        {"check": "Python 编译", "ok": state.package_sandbox.get("ok", False)}
    )
    state.quality_items.append(
        {
            "check": "工作流结构校验",
            "ok": state.workflow_sandbox.get("ok", False),
            "note": (
                "仅结构，未测业务"
                if not state.workflow_sandbox.get("business_tested", True)
                else ""
            ),
        }
    )
    if state.workflow_business_ok is not None:
        state.quality_items.append(
            {
                "check": "工作流真实调用",
                "ok": bool(state.workflow_business_ok),
                "critical": state.pipeline_label
                in ("word_full_extract", "txt_full_read", "txt_generate"),
            }
        )
    state.quality_items.append(
        {
            "check": "独立包自检",
            "ok": state.standalone_smoke_ok,
            "critical": state.pipeline_label
            in ("word_full_extract", "txt_full_read", "txt_generate"),
        }
    )
    state.quality_items.append(
        {"check": "员工包登记", "ok": not state.registration_missing, "critical": True}
    )
    _host_note = "已跳过"
    if state.host_probe.get("skipped") and state.pipeline_label in (
        "word_full_extract",
        "txt_full_read",
        "txt_generate",
    ):
        _host_note = "本地文件转换无需宿主"
    state.quality_items.append(
        {
            "check": "宿主连通性",
            "ok": state.host_probe.get("ok") if not state.host_probe.get("skipped") else None,
            "note": _host_note if state.host_probe.get("skipped") else "",
        }
    )
    _sess_validate_errors: List[str] = []
    async with ports.sessions.lock:
        _sess_q = ports.sessions.data.get(state.session_id) or {}
        _ve = _sess_q.get("validate_errors")
        if isinstance(_ve, list):
            _sess_validate_errors = [str(x) for x in _ve if x]
    _extra_items, state.runnable, state.critical_failed = ports.quality_extras(
        state.pack_dir,
        pipeline_label=state.pipeline_label,
        validate_errors=_sess_validate_errors,
        mod_sandbox=(
            cast(dict[str, Any], state.package_sandbox)
            if isinstance(state.package_sandbox, dict)
            else {}
        ),
        runtime_generation=(
            cast(dict[str, Any], state.result.get("runtime_generation"))
            if isinstance(state.result.get("runtime_generation"), dict)
            else {}
        ),
        domain_smoke=(
            cast(dict[str, Any], state.result.get("domain_smoke"))
            if isinstance(state.result.get("domain_smoke"), dict)
            else {}
        ),
        golden_comparison=(
            cast(dict[str, Any], state.result.get("golden_comparison"))
            if isinstance(state.result.get("golden_comparison"), dict)
            else {}
        ),
    )
    state.quality_items.extend(_extra_items)
    state.failed_critical = [
        q["check"] for q in state.quality_items if q.get("ok") is False and q.get("critical")
    ]
    if state.failed_critical:
        state.critical_failed = True
        state.runnable = False
    if state.six_dimension_report and state.six_dimension_report.get("critical_failed"):
        state.critical_failed = True
        state.runnable = False
    return False
