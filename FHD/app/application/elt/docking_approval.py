"""Data-docking writes are approval-center requests. Approving releases the write."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.application.elt.auto_ingest_service import get_auto_ingest_service
from app.application.workflow.approval_service import get_approval_service
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import RECOVERABLE_ERRORS


def submit_docking_write(
    *,
    owner_user_id: int,
    tenant_id: int,
    source_path: str | Path,
    file_name: str = "",
    template_id: str = "",
    review_id: str = "",
    classification_id: str = "",
    composer_note: str = "",
    labels: list[str] | None = None,
    prepared_plan: dict[str, Any] | None = None,
    owned_upload_user_id: int | None = None,
    submission_origin: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Queue the prepared write and create the approval-center request. Do not write yet."""
    service = get_auto_ingest_service()
    batch = service.queue_for_approval(
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        source_path=source_path,
        file_name=file_name,
        template_id=template_id,
        review_id=review_id,
        classification_id=classification_id,
        composer_note=composer_note,
        labels=labels,
        prepared_plan=prepared_plan,
        owned_upload_user_id=owned_upload_user_id,
    )
    batch_id = str(batch.get("batch_id") or "")
    visible_name = str(batch.get("file_name") or file_name or batch_id)
    plan = PlanGraph(
        plan_id=f"data-docking-{batch_id}",
        intent=f"数据对接入库：{visible_name}",
        todo_steps=[f"审批通过后写入：{visible_name}"],
        nodes=[
            WorkflowNode(
                node_id="data_docking_write",
                tool_id="data_docking",
                action="auto_ingest",
                params={"batch_id": batch_id},
                risk="high",
                idempotent=False,
                description=f"数据对接入库：{visible_name}",
            )
        ],
        risk_level="high",
        metadata={
            "source": "data_docking_auto_ingest",
            **({"office_stage_origin": dict(submission_origin)} if submission_origin else {}),
        },
    )
    context = {
        "local_user_id": int(owner_user_id),
        "tenant_id": int(tenant_id),
        "source": "data_docking_auto_ingest",
    }
    try:
        with tenant_scope(int(tenant_id)):
            request = get_approval_service().create_approval_request(
                plan_id=plan.plan_id,
                node=plan.nodes[0],
                runtime_context=context,
                plan=plan,
                require_persistence=True,
                title=f"数据对接入库：{visible_name}",
            )
    except RECOVERABLE_ERRORS + (RuntimeError,):
        service.cancel_unreleased_batch(batch_id=batch_id, tenant_id=int(tenant_id))
        raise
    queued = dict(batch)
    metadata = get_approval_service().get_request_metadata(request.request_id) or {}
    queued["approval_id"] = metadata.get("id")
    queued["approval_request_id"] = str(request.request_id or "")
    queued["status"] = "awaiting_approval"
    queued["success"] = True
    return queued


def verify_office_stage_submission(
    run: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    from app.application.agent_orchestrator.verification_readback import _report
    from app.application.office_parse_app_service import office_submission_origin
    from app.application.workflow.approval_persistence import load_durable_workflow_snapshot
    from app.db.models.approval import ApprovalRequest
    from app.db.session import get_db
    from app.infrastructure.auth.agent_mod_scope import agent_mod_execution_scope
    from app.infrastructure.tenant_scope import tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    data = output.get("data") or {}
    origin = office_submission_origin(context, run.message)
    if not isinstance(data, dict) or data.get("status") != "awaiting_approval" or not origin:
        return _report("inconclusive", "result_receipt_missing", "docking_approval")
    request_id, batch_id = data.get("approval_request_id"), data.get("batch_id")
    if (
        not isinstance(request_id, str)
        or not request_id
        or not isinstance(batch_id, str)
        or not batch_id
    ):
        return _report("inconclusive", "result_receipt_missing", "docking_approval")
    tenant, owner = int(context["tenant_id"]), int(context["user_id"])
    token = set_request_active_mod_id("")
    try:
        with agent_mod_execution_scope(context.get("_mod_authorization")), tenant_scope(tenant):
            with get_db() as db:
                approval = (
                    db.query(ApprovalRequest)
                    .filter(
                        ApprovalRequest.request_no == request_id,
                        ApprovalRequest.tenant_id == tenant,
                        ApprovalRequest.applicant_id == owner,
                        ApprovalRequest.status == "pending",
                    )
                    .first()
                )
                snapshot = load_durable_workflow_snapshot(request_id) if approval else None
            batch = get_auto_ingest_service().get_batch(tenant_id=tenant, batch_id=batch_id)
    finally:
        reset_request_active_mod_id(token)
    plan = snapshot.get("plan") if snapshot else None
    saved_context = snapshot.get("runtime_context") if snapshot else {}
    if (
        not plan
        or len(plan.nodes) != 1
        or not isinstance(plan.metadata, dict)
        or plan.metadata.get("office_stage_origin") != origin
        or plan.nodes[0].tool_id != "data_docking"
        or plan.nodes[0].action != "auto_ingest"
        or plan.nodes[0].params != {"batch_id": batch_id}
        or not isinstance(saved_context, dict)
        or str(saved_context.get("local_user_id")) != str(owner)
        or str(saved_context.get("tenant_id")) != str(tenant)
        or not batch
        or batch.get("owner_user_id") != owner
        or batch.get("tenant_id") != tenant
        or batch.get("status") != "awaiting_approval"
    ):
        return _report("inconclusive", "result_receipt_unavailable", "docking_approval")
    return _report(
        "verified",
        "result_verified",
        "docking_approval",
        approval_request_id=request_id,
        batch_id=batch_id,
        tenant_id=str(tenant),
        submission_verified=True,
        admission_verified=True,
        business_execution_verified=False,
    )
