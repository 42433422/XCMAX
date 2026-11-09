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
        metadata={"source": "data_docking_auto_ingest"},
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
    queued["approval_request_id"] = str(request.request_id or "")
    queued["status"] = "awaiting_approval"
    queued["success"] = True
    return queued
