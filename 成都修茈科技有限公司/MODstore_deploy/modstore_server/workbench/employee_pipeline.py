"""Coordinate employee planning, packaging, publication and evidence-based delivery."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from modstore_server.employee_brief_utils import extract_routing_brief, is_contract_doc_review_brief
from modstore_server.employee_pack_cleanup import cleanup_experimental_pack
from modstore_server.employee_pipeline_routing import (
    classify_employee_pipeline,
    resolve_employee_runtime_kind,
    validate_runtime_pipeline_consistency,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.employee_delivery import EmployeeDeliveryPorts, deliver_employee
from modstore_server.workbench.employee_generation import EmployeeGenerationPorts, generate_employee
from modstore_server.workbench.employee_planning import EmployeePlanningPorts, plan_employee
from modstore_server.workbench.employee_quality import (
    EmployeeQualityPorts,
    evaluate_employee_quality,
)
from modstore_server.workbench.employee_registration import (
    EmployeeRegistrationPorts,
    register_and_verify_workflow,
)
from modstore_server.workbench.employee_runtime_checks import (
    EmployeeRuntimePorts,
    check_employee_runtime,
)
from modstore_server.workbench.employee_state import EmployeeBuildState
from modstore_server.workbench.employee_workflows import (
    EmployeeWorkflowPorts,
    bind_employee_workflows,
)
from modstore_server.workbench.intent import _contains_uploaded_docx
from modstore_server.workbench.sessions import ProgressCallbacks, SessionStore

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeeBuildServices:
    sessions: SessionStore
    progress: ProgressCallbacks
    planning: EmployeePlanningPorts
    generation: EmployeeGenerationPorts
    workflows: EmployeeWorkflowPorts
    registration: EmployeeRegistrationPorts
    runtime: EmployeeRuntimePorts
    quality: EmployeeQualityPorts
    delivery: EmployeeDeliveryPorts

    async def run(self, state: EmployeeBuildState) -> None:
        if await plan_employee(state, ports=self.planning):
            return
        if await generate_employee(state, ports=self.generation):
            return
        if await bind_employee_workflows(state, ports=self.workflows):
            return
        if await register_and_verify_workflow(state, ports=self.registration):
            return
        if await check_employee_runtime(state, ports=self.runtime):
            return
        if await evaluate_employee_quality(state, ports=self.quality):
            return
        await deliver_employee(state, ports=self.delivery)


async def run_employee_pipeline(
    sid: str,
    user_id: int,
    payload: dict[str, Any],
    brief: str,
    provider: str | None,
    model: str | None,
    replace: bool,
    *,
    services: EmployeeBuildServices,
) -> None:
    files = payload.get("_files") or []
    routing_brief = extract_routing_brief(payload, fallback=brief)
    lowered = (routing_brief or brief or "").lower()
    reasoning = is_contract_doc_review_brief(routing_brief) or any(
        (
            word in lowered
            for word in (
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
    label, word_extract, _, _, assets = classify_employee_pipeline(
        routing_brief, employee_files=files, needs_llm_reasoning=reasoning
    )
    valid, error = validate_runtime_pipeline_consistency(
        routing_brief=routing_brief,
        pipeline_label=label,
        rule_spec={"runtime_kind": resolve_employee_runtime_kind(routing_brief)},
    )
    if not valid:
        await services.progress.fail(sid, "spec", error[:1000])
        return
    state = EmployeeBuildState(
        session_id=sid,
        user_id=user_id,
        payload=payload,
        brief=brief,
        provider=provider,
        model=model,
        replace=replace,
        target=str(payload.get("employee_target") or "pack_only").strip().lower(),
        embed_script_workflow=bool(payload.get("embed_script_workflow", True)),
        workflow_name=(payload.get("employee_workflow_name") or "").strip() or None,
        fhd_base=(payload.get("fhd_base_url") or "").strip()
        or os.environ.get("FHD_BASE_URL", "").strip()
        or None,
        employee_files=files,
        routing_brief=routing_brief,
        pipeline_label=label,
        needs_llm_reasoning=reasoning,
        uploaded_docx=_contains_uploaded_docx(files),
        use_assets=assets,
        use_word_extract=word_extract,
    )
    async with services.sessions.lock:
        session = services.sessions.data.get(sid)
        checkpoint = session.pop("_resume_checkpoint", None) if session else None
        if checkpoint:
            services.sessions.persist(sid)
    if isinstance(checkpoint, dict):
        state.restore(checkpoint)
        if state.resume_from:
            _LOG.info(
                "pipeline resume session=%s from step=%s pack_dir=%s",
                sid,
                state.resume_from,
                state.package_path,
            )
    try:
        await services.run(state)
    except RECOVERABLE_ERRORS as error:
        _LOG.error(
            "workbench employee pipeline failed session=%s step=%s error_type=%s",
            sid,
            state.current_step,
            type(error).__name__,
        )
        try:
            failed_pack = str(state.result.get("id") or "")
            if not failed_pack and state.package_path:
                failed_pack = state.package_path.name
            if failed_pack:
                cleanup_experimental_pack(failed_pack, metadata=state.payload)
        except RECOVERABLE_ERRORS:
            _LOG.warning("experimental cleanup on error failed session=%s", sid, exc_info=True)
        async with services.sessions.lock:
            session = services.sessions.data.get(sid)
            if session:
                session["_pipeline_checkpoint"] = state.checkpoint()
                services.sessions.persist(sid)
        await services.progress.fail(sid, state.current_step, str(error)[:2000])


def _manifest_diagnostic(state: EmployeeBuildState) -> str:
    if state.package_path is None:
        return ""
    manifest = state.package_path / "manifest.json"
    if not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        employee = data.get("employee") or {}
        workflows = data.get("workflow_employees") or []
        return " [disk: manifest.id=%s employee.id=%s wf[0].id=%s]" % (
            data.get("id"),
            employee.get("id"),
            workflows[0].get("id") if workflows else "N/A",
        )
    except RECOVERABLE_ERRORS:
        return ""
