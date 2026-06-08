from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)
from modstore_server.workflow_api.schemas import (
    AddWorkflowEdgeBody,
    AddWorkflowNodeBody,
    PatchWorkflowNodeBody,
)

router = APIRouter()


@router.post("/{workflow_id}/nodes", summary="添加工作流节点")
async def add_workflow_node(
    workflow_id: int,
    body: AddWorkflowNodeBody,
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

    node = WorkflowNode(
        workflow_id=workflow_id,
        node_type=body.node_type.strip(),
        name=body.name.strip(),
        config=json.dumps(body.config or {}),
        position_x=body.position_x,
        position_y=body.position_y,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return {
        "id": node.id,
        "node_type": node.node_type,
        "name": node.name,
        "config": json.loads(node.config),
        "position_x": node.position_x,
        "position_y": node.position_y,
    }


@router.put("/nodes/{node_id}", summary="更新工作流节点")
async def update_workflow_node(
    node_id: int,
    body: PatchWorkflowNodeBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    node = (
        db.query(WorkflowNode)
        .join(Workflow)
        .filter(
            WorkflowNode.id == node_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not node:
        raise HTTPException(404, "节点不存在")

    if body.name is not None:
        node.name = body.name
    if body.config is not None:
        node.config = json.dumps(body.config)
    if body.position_x is not None:
        node.position_x = body.position_x
    if body.position_y is not None:
        node.position_y = body.position_y

    db.commit()
    db.refresh(node)
    return {
        "id": node.id,
        "name": node.name,
        "config": json.loads(node.config),
        "position_x": node.position_x,
        "position_y": node.position_y,
    }


@router.delete("/nodes/{node_id}", summary="删除工作流节点")
async def delete_workflow_node(
    node_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    node = (
        db.query(WorkflowNode)
        .join(Workflow)
        .filter(
            WorkflowNode.id == node_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not node:
        raise HTTPException(404, "节点不存在")

    db.query(WorkflowEdge).filter(
        (WorkflowEdge.source_node_id == node_id) | (WorkflowEdge.target_node_id == node_id)
    ).delete()
    db.delete(node)
    db.commit()
    return {"message": "节点已删除"}


@router.post("/{workflow_id}/edges", summary="添加工作流边")
async def add_workflow_edge(
    workflow_id: int,
    body: AddWorkflowEdgeBody,
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

    source_node = (
        db.query(WorkflowNode)
        .filter(
            WorkflowNode.id == body.source_node_id,
            WorkflowNode.workflow_id == workflow_id,
        )
        .first()
    )
    target_node = (
        db.query(WorkflowNode)
        .filter(
            WorkflowNode.id == body.target_node_id,
            WorkflowNode.workflow_id == workflow_id,
        )
        .first()
    )
    if not source_node or not target_node:
        raise HTTPException(400, "源节点或目标节点不存在")

    edge = WorkflowEdge(
        workflow_id=workflow_id,
        source_node_id=body.source_node_id,
        target_node_id=body.target_node_id,
        condition=body.condition or "",
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return {
        "id": edge.id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "condition": edge.condition,
    }


@router.delete("/edges/{edge_id}", summary="删除工作流边")
async def delete_workflow_edge(
    edge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    edge = (
        db.query(WorkflowEdge)
        .join(Workflow)
        .filter(
            WorkflowEdge.id == edge_id,
            Workflow.user_id == user.id,
        )
        .first()
    )
    if not edge:
        raise HTTPException(404, "边不存在")

    db.delete(edge)
    db.commit()
    return {"message": "边已删除"}
