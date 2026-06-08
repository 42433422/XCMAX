from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    WorkflowSandboxRun,
)
from modstore_server.workflow_api.helpers import (
    _repair_empty_employee_workflow_graph,
    _workflow_summary,
)
from modstore_server.workflow_api.schemas import CreateWorkflowBody, UpdateWorkflowBody
from modstore_server.workflow_sandbox_state import (
    sandbox_status_for_workflow,
    workflow_graph_fingerprint,
)

router = APIRouter(tags=["workflow"])


@router.post("/", summary="创建工作流")
async def create_workflow(
    body: CreateWorkflowBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = Workflow(
        user_id=user.id,
        name=body.name.strip(),
        description=(body.description or "").strip(),
        is_active=True,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return {"id": workflow.id, "name": workflow.name, "description": workflow.description}


@router.get("/", summary="获取工作流列表")
async def list_workflows(
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    query = db.query(Workflow).filter(Workflow.user_id == user.id)
    if is_active is not None:
        query = query.filter(Workflow.is_active == is_active)
    workflows = query.all()
    return [_workflow_summary(db, w, user.id) for w in workflows]


@router.get("/{workflow_id}", summary="获取工作流详情")
async def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
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

    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()
    if not nodes and _repair_empty_employee_workflow_graph(db, workflow):
        nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()

    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).all()

    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "is_active": workflow.is_active,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
        "graph_fingerprint": workflow_graph_fingerprint(db, workflow_id),
        "sandbox_status": sandbox_status_for_workflow(db, workflow, user_id=user.id),
        "nodes": [
            {
                "id": n.id,
                "node_type": n.node_type,
                "name": n.name,
                "config": json.loads(n.config),
                "position_x": n.position_x,
                "position_y": n.position_y,
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": e.id,
                "source_node_id": e.source_node_id,
                "target_node_id": e.target_node_id,
                "condition": e.condition,
            }
            for e in edges
        ],
    }


@router.put("/{workflow_id}", summary="更新工作流")
async def update_workflow(
    workflow_id: int,
    body: UpdateWorkflowBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
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

    if body.name is not None:
        workflow.name = body.name
    if body.description is not None:
        workflow.description = body.description
    if body.is_active is not None:
        workflow.is_active = body.is_active
    workflow.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(workflow)
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "is_active": workflow.is_active,
        "updated_at": workflow.updated_at.isoformat(),
    }


@router.delete("/{workflow_id}", summary="删除工作流")
async def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
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

    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).delete()
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).delete()
    db.query(WorkflowExecution).filter(WorkflowExecution.workflow_id == workflow_id).delete()
    db.query(WorkflowSandboxRun).filter(WorkflowSandboxRun.workflow_id == workflow_id).delete()
    db.delete(workflow)
    db.commit()
    return {"message": "工作流已删除"}
