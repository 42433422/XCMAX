from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
)
from modstore_server.workflow_api.schemas import SandboxRunBody
from modstore_server.workflow_sandbox_state import (
    record_workflow_sandbox_run,
    sandbox_status_for_workflow,
)

router = APIRouter()


@router.get("/{workflow_id}/validate", summary="校验工作流（静态 + 拓扑提示）")
async def validate_workflow_endpoint(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    from modstore_server.workflow_engine import run_workflow_sandbox

    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    report = run_workflow_sandbox(workflow_id, {}, validate_only=True, user_id=user.id)
    return report


@router.post(
    "/{workflow_id}/sandbox-run",
    summary="[已弃用] 节点图沙盒运行；新工作流请用 /api/script-workflows/{id}/sandbox-run",
    deprecated=True,
)
async def sandbox_run_workflow(
    workflow_id: int,
    body: SandboxRunBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    from modstore_server.workflow_engine import run_workflow_sandbox

    workflow = (
        db.query(Workflow)
        .filter(
            Workflow.id == workflow_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    report = run_workflow_sandbox(
        workflow_id,
        body.input_data,
        mock_employees=body.mock_employees,
        validate_only=body.validate_only,
        user_id=user.id,
    )
    if not body.validate_only:
        row = record_workflow_sandbox_run(
            db,
            workflow_id=workflow_id,
            user_id=user.id,
            report=report,
            validate_only=body.validate_only,
            mock_employees=body.mock_employees,
        )
        status = sandbox_status_for_workflow(db, workflow, user_id=user.id)
        report = {
            **report,
            "sandbox_run_id": int(row.id),
            "graph_fingerprint": row.graph_fingerprint,
            "sandbox_status": status,
            "sandbox_passed_for_current_graph": status["sandbox_passed_for_current_graph"],
        }
    if not report.get("ok") and not body.validate_only:
        raise HTTPException(
            400,
            detail={
                "errors": report.get("errors"),
                "warnings": report.get("warnings"),
                "mode": "real" if not body.mock_employees else "mock",
                "sandbox_status": report.get("sandbox_status"),
            },
        )
    return report
