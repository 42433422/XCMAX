"""Independent result gates over the existing run, tool receipts and read ports.

Execution receipts are immutable observations, not proof of a business effect.
The host freezes the acceptance contract before dispatch; a separate readback
adapter supplies evidence afterwards. No model or tool payload can select a
verifier, supply its verdict, or turn an unavailable verifier into a pass.
"""

from __future__ import annotations

import copy
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall, utc_now_iso
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2
from app.domain.task_lifecycle.results import execution_result_envelopes, execution_result_error
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

PROTOCOL = "xcagi.result-verification.v1"
ACCEPTED_STATUSES = frozenset({"verified", "not_required"})
_READBACK_SCHEMA = {
    "type": "object",
    "required": ["status", "code", "checks"],
    "properties": {
        "status": {"enum": ["verified", "failed", "inconclusive"]},
        "code": {"type": "string", "minLength": 1},
        "checks": {
            "type": "array",
            "maxItems": 64,
            "items": {
                "type": "object",
                "required": ["check_id", "status", "source", "evidence"],
                "properties": {
                    "check_id": {"type": "string", "minLength": 1},
                    "status": {"enum": ["passed", "failed", "unavailable"]},
                    "source": {"type": "string", "minLength": 1},
                    "evidence": {"type": "object"},
                },
            },
        },
    },
}


def _scope(run: AgentRun, context: dict[str, Any]) -> dict[str, str]:
    original = run.metadata.get("runtime_context") or {}
    task = run.metadata.get("task_context") or {}
    binding = context.get("_mod_authorization") or {}
    return {
        "run_id": run.run_id,
        "owner_id": run.user_id,
        "tenant_id": str(context.get("tenant_id") or task.get("tenant_id") or ""),
        "actor_id": str(context.get("actor_id") or context.get("user_id") or run.user_id),
        "mod_id": str(
            binding.get("mod_id") or context.get("mod_id") or context.get("active_mod_id") or ""
        ),
        "task_id": str(task.get("task_id") or original.get("task_id") or run.run_id),
    }


def freeze_verification_contract(
    run: AgentRun,
    step: AgentStep,
    call: ToolCall,
    spec: ToolActionSpecV2 | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Called by the host before dispatch, never from tool/model JSON."""
    contract = {
        "protocol": PROTOCOL,
        "scope": _scope(run, context),
        "step_id": step.step_id,
        "node_id": step.node_id,
        "call_id": call.call_id,
        "attempt": int(call.metadata.get("attempt_count") or step.attempt_count),
        "tool_id": step.tool_id,
        "action": step.action,
        "input_sha256": canonical_hash(call.params),
        "tool_version": str(spec.version) if spec else "",
        "read_only": bool(spec and spec.read_only),
        "output_schema": copy.deepcopy(spec.output_schema) if spec else {},
    }
    if step.tool_id == "sales":
        from app.application.agent_orchestrator.verification_sales import (
            SALES_ACTIONS,
            capture_sales_baseline,
        )

        if step.action in SALES_ACTIONS:
            contract["authority_baseline"] = capture_sales_baseline(step, context)
    if (step.tool_id, step.action) == ("kellai", "send"):
        from app.application.kellai_binding_app_service import connection_identity_sha256

        contract["kellai_connection_sha256"] = connection_identity_sha256()
    from app.application.agent_orchestrator.verification_surface import (
        capture_surface_acceptance,
        supports_surface_verification,
    )

    if supports_surface_verification(step.tool_id, step.action):
        contract["surface_acceptance"] = capture_surface_acceptance(run, step, context)
    if (step.tool_id, step.action) == ("employee", "execute"):
        from app.application.employee_runtime.task_continuity import task_admission_origin
        from app.infrastructure.workspace import workspace_root

        contract["workspace_sha256"] = task_admission_origin({}, workspace_root())[
            "workspace_sha256"
        ]
    contract["contract_sha256"] = canonical_hash(contract)
    call.metadata["verification_contract"] = contract
    call.metadata["verification"] = {
        "protocol": PROTOCOL,
        "status": "pending",
        "accepted": False,
        "code": "awaiting_execution_receipt",
        "call_id": call.call_id,
        "checks": [],
    }
    return copy.deepcopy(contract)


def bind_execution_receipt(call: ToolCall) -> None:
    """Persist this digest with the raw receipt before making any verification I/O."""
    call.metadata["verification_output_sha256"] = canonical_hash(call.output)
    call.metadata["verification"] = {
        "protocol": PROTOCOL,
        "status": "pending",
        "accepted": False,
        "code": "awaiting_independent_readback",
        "call_id": call.call_id,
        "checks": [],
    }


def _binding_valid(run, step, call, context, contract) -> bool:
    if not isinstance(contract, dict) or contract.get("protocol") != PROTOCOL:
        return False
    content = {key: value for key, value in contract.items() if key != "contract_sha256"}
    return (
        contract.get("contract_sha256") == canonical_hash(content)
        and contract.get("scope") == _scope(run, context)
        and (contract.get("step_id"), contract.get("node_id"), contract.get("call_id"))
        == (step.step_id, step.node_id, call.call_id)
        and (call.step_id, call.node_id, call.tool_id, call.action)
        == (step.step_id, step.node_id, step.tool_id, step.action)
        and (contract.get("tool_id"), contract.get("action")) == (step.tool_id, step.action)
        and contract.get("attempt") == int(call.metadata.get("attempt_count") or step.attempt_count)
        and contract.get("input_sha256") == canonical_hash(call.params)
        and call.params == step.params
        and step.output == call.output
        and call.metadata.get("verification_output_sha256") == canonical_hash(call.output)
    )


def _declared_files(output: dict[str, Any]) -> list[dict[str, Any]]:
    files = []
    for envelope in execution_result_envelopes(output):
        for key in ("artifacts", "artifact"):
            declared = envelope.get(key)
            for item in declared if isinstance(declared, list) else [declared]:
                if isinstance(item, dict) and item.get("artifact_type") in {
                    "file",
                    "office_document",
                }:
                    files.append(item)
    return files


def _files_have_evidence(output: dict[str, Any], checks: list[dict[str, Any]]) -> bool:
    for artifact in _declared_files(output):
        metadata = artifact.get("metadata") or {}
        if (
            not isinstance(metadata, dict)
            or not artifact.get("artifact_id")
            or not metadata.get("sha256")
        ):
            return False
        if not any(
            isinstance(check, dict)
            and check.get("status") == "passed"
            and check.get("source") == "run_artifact"
            and isinstance(check.get("evidence"), dict)
            and check["evidence"].get("artifact_id") == artifact["artifact_id"]
            and check["evidence"].get("sha256") == metadata["sha256"]
            for check in checks
        ):
            return False
    return True


def verify_step_result(
    *, run: AgentRun, step: AgentStep, call: ToolCall, context: dict[str, Any]
) -> dict[str, Any]:
    """Re-read facts without dispatching the business tool or touching its receipt."""
    previous = call.metadata.get("verification") or {}
    contract = call.metadata.get("verification_contract") or {}
    report: dict[str, Any] = {
        "protocol": PROTOCOL,
        "status": "inconclusive",
        "accepted": False,
        "code": "verification_binding_invalid",
        "scope": copy.deepcopy(contract.get("scope") or {}),
        "step_id": step.step_id,
        "call_id": call.call_id,
        "contract_sha256": contract.get("contract_sha256", ""),
        "output_sha256": call.metadata.get("verification_output_sha256", ""),
        "observed_at": utc_now_iso(),
        "verification_attempt": int(previous.get("verification_attempt") or 0) + 1,
        "checks": [],
    }
    try:
        if _binding_valid(run, step, call, context, contract):
            report.update(_evaluate(run, step, call, context, contract))
    except (SchemaError, Unresolvable) + RECOVERABLE_ERRORS + BOUNDARY_ERRORS:
        # Unknown source state is never evidence of absence or permission to replay.
        report.update(status="inconclusive", code="verification_source_unavailable", checks=[])
    report["accepted"] = report["status"] in ACCEPTED_STATUSES
    report["evidence_sha256"] = canonical_hash(report["checks"])
    report["report_sha256"] = canonical_hash(report)
    call.metadata["verification"] = copy.deepcopy(report)
    return report


def _evaluate(run, step, call, context, contract) -> dict[str, Any]:
    from app.application.agent_orchestrator.verification_cognition import plan_admission_receipt
    from app.application.agent_orchestrator.verification_kellai import can_observe_kellai_delivery

    delivery_observation = can_observe_kellai_delivery(run, step, call)
    child_admission = (step.tool_id, step.action) == ("enterprise_cognition", "plan") and (
        plan_admission_receipt(call.output)
    )
    if not delivery_observation and (
        call.output.get("success") is not True
        or (execution_result_error(call.output) and not child_admission)
    ):
        return {"status": "failed", "code": "execution_receipt_not_successful", "checks": []}
    schema = contract.get("output_schema")
    if not contract.get("tool_version") or not isinstance(schema, dict) or not schema:
        return {"status": "inconclusive", "code": "verification_contract_unavailable", "checks": []}
    Draft202012Validator.check_schema(schema)
    # An explicit empty Registry has no retrieval callback. External references
    # fail closed; jsonschema's default remote-retrieval compatibility is unused.
    validator = Draft202012Validator(schema, registry=Registry())
    if next(validator.iter_errors(call.output), None) is not None:
        return {"status": "failed", "code": "verification_output_schema_mismatch", "checks": []}
    from app.application.agent_orchestrator.verification_readback import verify_independent_result

    evidence: dict[str, Any] = verify_independent_result(
        run=run, step=step, call=call, output=copy.deepcopy(call.output), context=dict(context)
    )
    if not Draft202012Validator(_READBACK_SCHEMA).is_valid(evidence):
        return {"status": "inconclusive", "code": "verification_evidence_invalid", "checks": []}
    checks = evidence["checks"]
    if evidence["status"] == "verified" and (
        not checks or any(check["status"] != "passed" or not check["evidence"] for check in checks)
    ):
        return {"status": "inconclusive", "code": "verification_evidence_missing", "checks": []}
    if evidence["status"] == "verified" and not _files_have_evidence(call.output, checks):
        return {
            "status": "inconclusive",
            "code": "artifact_verification_incomplete",
            "checks": checks,
        }
    if delivery_observation and evidence["status"] == "verified":
        # The original transport outcome, billing and queue effect remain
        # unsettled. Observing delivery alone cannot authorize generic retry.
        return {
            "status": "inconclusive",
            "code": "original_delivery_observed_execution_unsettled",
            "checks": checks,
        }
    if evidence["code"] == "result_verifier_unavailable" and contract["read_only"]:
        if _declared_files(call.output):
            return {"status": "inconclusive", "code": "artifact_verifier_unavailable", "checks": []}
        return {
            "status": "not_required",
            "code": "read_only_output_contract_checked",
            "checks": [
                {
                    "check_id": "output_schema",
                    "status": "passed",
                    "source": "host_tool_contract",
                    "evidence": {"schema_sha256": canonical_hash(schema)},
                }
            ],
        }
    return evidence


def latest_step_call(run: AgentRun, step: AgentStep) -> ToolCall | None:
    return next((call for call in reversed(run.tool_calls) if call.step_id == step.step_id), None)


def step_verification_blocked(run: AgentRun, step: AgentStep) -> bool:
    call = latest_step_call(run, step)
    if call is None or not call.metadata.get("verification_contract"):
        from app.application.agent_orchestrator.clarification import control_verification_report

        if control_verification_report(run, step) is not None:
            return False
        return bool(
            step.status == "completed"
            and any(item.metadata.get("verification_contract") for item in run.tool_calls)
        )
    if call.output.get("success") is not True:
        return False
    report = call.metadata.get("verification") or {}
    try:
        return not (
            report.get("status") in ACCEPTED_STATUSES
            and report.get("accepted") is True
            and _binding_valid(
                run,
                step,
                call,
                run.metadata.get("runtime_context") or {},
                call.metadata["verification_contract"],
            )
            and report.get("contract_sha256")
            == call.metadata["verification_contract"].get("contract_sha256")
            and report.get("output_sha256") == call.metadata.get("verification_output_sha256")
            and report.get("evidence_sha256") == canonical_hash(report.get("checks"))
            and _files_have_evidence(call.output, report.get("checks") or [])
            and report.get("report_sha256")
            == canonical_hash(
                {key: value for key, value in report.items() if key != "report_sha256"}
            )
        )
    except (TypeError, ValueError, OverflowError):
        return True


def summarize_verification(run: AgentRun) -> dict[str, Any]:
    reports = []
    for step in run.steps:
        call = latest_step_call(run, step)
        if call is not None and call.metadata.get("verification_contract"):
            report = copy.deepcopy(call.metadata.get("verification") or {})
            if report.get("status") in ACCEPTED_STATUSES and step_verification_blocked(run, step):
                report.update(
                    status="inconclusive", accepted=False, code="verification_binding_changed"
                )
            reports.append({"step_id": step.step_id, "node_id": step.node_id, **report})
        elif step.status == "completed":
            from app.application.agent_orchestrator.clarification import control_verification_report

            if control_report := control_verification_report(run, step):
                reports.append({"step_id": step.step_id, "node_id": step.node_id, **control_report})
                continue
            reports.append(
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "status": "not_verified",
                    "accepted": False,
                    "code": "historical_receipt_has_no_verification_contract",
                    "checks": [],
                }
            )
    status = next(
        (
            status
            for status in ("failed", "inconclusive", "pending", "not_verified")
            if any(report.get("status") == status for report in reports)
        ),
        "verified"
        if any(report.get("status") == "verified" for report in reports)
        else "not_required"
        if reports
        else "not_verified",
    )
    return {
        "protocol": PROTOCOL,
        "status": status,
        "accepted": bool(reports) and all(r.get("status") in ACCEPTED_STATUSES for r in reports),
        "independently_verified_steps": sum(r.get("status") == "verified" for r in reports),
        "contract_only_steps": sum(r.get("status") == "not_required" for r in reports),
        "steps": reports,
    }


def verification_blocked(run: AgentRun) -> bool:
    return any(step_verification_blocked(run, step) for step in run.steps)


def project_verification(run: AgentRun) -> dict[str, Any]:
    """Keep task/UI projections current even if the next verification read crashes."""
    report = summarize_verification(run)
    run.metadata["verification"] = report
    run.final_output["verification"] = copy.deepcopy(report)
    return report


def restore_verified_artifacts(
    run: AgentRun, step: AgentStep, call: ToolCall, attach_artifacts=None
) -> None:
    """Rebuild the download projection from the original accepted receipt, once."""
    if step_verification_blocked(run, step) or call.output.get("success") is not True:
        return
    from app.application.agent_orchestrator.artifact_attachment import ArtifactAttachmentMixin

    attach = attach_artifacts or ArtifactAttachmentMixin()._attach_artifacts_from_payload
    artifacts = call.output.get("artifacts", call.output.get("artifact"))
    items = (
        artifacts
        if isinstance(artifacts, list)
        else [artifacts]
        if isinstance(artifacts, dict)
        else []
    )
    known = {artifact.artifact_id for artifact in run.artifacts}
    pending = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        item = copy.deepcopy(raw)
        if not item.get("artifact_id"):
            if item.get("artifact_type") in {"file", "office_document"}:
                continue
            item["artifact_id"] = "view_" + canonical_hash([call.call_id, index, item])[:32]
        if item["artifact_id"] not in known:
            pending.append(item)
            known.add(item["artifact_id"])
    if pending:
        attach(
            run,
            {"artifacts": pending},
            source=f"{step.tool_id}.{step.action}",
            extra_metadata={"step_id": step.step_id, "call_id": call.call_id},
        )


class VerificationEngine:
    """Host facade; all persistence remains on AgentRun/ToolCall and their existing CAS."""

    freeze = staticmethod(freeze_verification_contract)
    verify = staticmethod(verify_step_result)
    summarize = staticmethod(summarize_verification)
