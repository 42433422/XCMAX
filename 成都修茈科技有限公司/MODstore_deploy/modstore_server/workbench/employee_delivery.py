"""Employee delivery for workbench delivery."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, cast

from modstore_server.employee_ai_scaffold import normalize_editor_manifest_for_registry
from modstore_server.employee_pack_cleanup import cleanup_experimental_pack
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.employee_state import EmployeeBuildState
from modstore_server.workbench.sessions import ProgressCallbacks, SessionStore

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeeDeliveryPorts:
    sessions: SessionStore
    progress: ProgressCallbacks


async def deliver_employee(
    state: EmployeeBuildState, *, ports: EmployeeDeliveryPorts
) -> bool:
    if (
        state.registration_missing
        and state.result.get("manifest")
        and isinstance(state.result.get("manifest"), dict)
    ):
        try:
            await ports.progress.set_step(
                state.session_id,
                "complete",
                "running",
                "登记未通过，正在重试 manifest 对齐…",
            )
            _retry_mf = state.result["manifest"]
            _retry_pid = str(
                _retry_mf.get("id") or state.result.get("id") or ""
            ).strip()
            if _retry_pid and state.pack_dir.is_dir():
                _raw_mf = json.loads(
                    (state.pack_dir / "manifest.json").read_text(encoding="utf-8")
                )
                _aligned_mf, _ = normalize_editor_manifest_for_registry(
                    _raw_mf, _retry_pid
                )
                (state.pack_dir / "manifest.json").write_text(
                    json.dumps(_aligned_mf, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                state.registration_missing = False
                for qi in state.quality_items:
                    if qi["check"] == "员工包登记":
                        qi["ok"] = True
                        qi["note"] = "重试 manifest 对齐成功（未自动上架）"
        except RECOVERABLE_ERRORS as _retry_exc:
            _LOG.warning(
                "register_pack local retry failed error_type=%s",
                type(_retry_exc).__name__,
            )
            for qi in state.quality_items:
                if qi["check"] == "员工包登记":
                    qi["note"] = f"重试失败: {_retry_exc!s}"[:120]
    _quality_pass = sum((1 for q in state.quality_items if q.get("ok") is True))
    _quality_total = sum((1 for q in state.quality_items if q.get("ok") is not None))
    _quality_warn = sum((1 for q in state.quality_items if q.get("ok") is False))
    _quality_skip = sum((1 for q in state.quality_items if q.get("ok") is None))
    _quality_score = (
        round(_quality_pass / _quality_total * 100, 1) if _quality_total else 0.0
    )
    _complete_msg_parts = [
        f"质量报告：{_quality_pass}/{_quality_total} 通过（{_quality_score} 分）"
    ]
    if state.six_dimension_report:
        _complete_msg_parts.insert(
            0,
            f"六维综合 {state.six_dimension_report.get('overall_score', 0)} 分"
            + (
                "（达标）" if state.six_dimension_report.get("passed") else "（未达标）"
            ),
        )
    if state.pipeline_label == "word_full_extract":
        _complete_msg_parts.append(
            "可提取 Word："
            + ("是" if state.runnable else "否（handlers/convert 未对齐）")
        )
    if _quality_warn:
        _complete_msg_parts.append(f"{_quality_warn} 项需关注")
    if _quality_skip:
        _complete_msg_parts.append(f"{_quality_skip} 项跳过")
    _failed_checks = [q["check"] for q in state.quality_items if q.get("ok") is False]
    if _failed_checks:
        _complete_msg_parts.append("⚠️ 未通过：" + "、".join(_failed_checks))
    _complete_msg_parts.append(
        "下一步：在画布中编辑员工配置 → 部署到宿主 → 真实业务验证"
    )
    _complete_status = "error" if state.critical_failed else "done"
    if state.critical_failed:
        _complete_msg_parts.insert(0, "⚠️ 关键质量项未通过，员工包不可用")
    await ports.progress.set_step(
        state.session_id,
        "complete",
        _complete_status,
        "；".join(_complete_msg_parts)[:480],
    )
    if state.critical_failed:
        await ports.progress.fail(
            state.session_id, "complete", "；".join(state.failed_critical)[:1000]
        )
        return True
    async with ports.sessions.lock:
        sess = ports.sessions.data.get(state.session_id)
        if sess:
            sess["sandbox_report"] = {
                "workflow": state.workflow_sandbox,
                "mod": state.package_sandbox,
            }
            sess["quality_report"] = {
                "items": state.quality_items,
                "pass": _quality_pass,
                "total": _quality_total,
                "warnings": _quality_warn,
                "skipped": _quality_skip,
                "failed_checks": _failed_checks,
                "score": _quality_score,
                "pipeline_label": state.pipeline_label,
                "runnable": state.runnable,
                "critical_failed": state.critical_failed,
                "six_dimension_report": state.six_dimension_report or None,
            }
            if state.six_dimension_report:
                sess["six_dimension_report"] = state.six_dimension_report
            ports.sessions.persist(state.session_id)
    _pack_id_final = str(state.result.get("id") or "")
    try:
        cleanup_experimental_pack(
            _pack_id_final,
            metadata=(
                cast(dict[str, Any], state.payload)
                if isinstance(state.payload, dict)
                else None
            ),
        )
    except RECOVERABLE_ERRORS as _clean_exc:
        _LOG.warning(
            "experimental pack cleanup failed error_type=%s", type(_clean_exc).__name__
        )
    await ports.progress.finish(
        state.session_id,
        {
            "pack_id": state.result["id"],
            "employee_id": state.result["id"],
            "manifest_employee_id": state.result["id"],
            "name": (state.result.get("manifest") or {}).get("name"),
            "description": (state.result.get("manifest") or {}).get("description"),
            "workflow_id": state.workflow_id,
            "package": state.saved_package,
            "workflow_sandbox": state.workflow_sandbox,
            "mod_sandbox": state.package_sandbox,
            "employee_target": state.target,
            "employee_orchestration_plan": state.employee_plan,
            "workflow_attachment": state.workflow_attachment,
            "script_workflow": state.script_workflow,
            "script_workflow_attachment": state.script_attachment,
            "host_probe": state.host_probe,
            "quality_report": {
                "items": state.quality_items,
                "pass": _quality_pass,
                "total": _quality_total,
                "warnings": _quality_warn,
                "skipped": _quality_skip,
                "failed_checks": _failed_checks,
                "score": _quality_score,
                "pipeline_label": state.pipeline_label,
                "runnable": state.runnable,
                "critical_failed": state.critical_failed,
                "six_dimension_report": state.six_dimension_report or None,
            },
            "six_dimension_report": state.six_dimension_report or None,
            "runtime_generation": state.result.get("runtime_generation"),
            "domain_smoke": state.result.get("domain_smoke"),
            "golden_comparison": state.result.get("golden_comparison"),
            "rule_spec": state.result.get("rule_spec"),
            "validation_summary": {
                "ok": bool(state.package_sandbox.get("ok"))
                and (not state.registration_missing),
                "mod_sandbox": state.package_sandbox,
                "workflow_skipped": not bool(state.workflow_id),
                "standalone_smoke_ok": state.standalone_smoke_ok,
                "register_ok": not state.registration_missing,
            },
        },
    )
    return False
