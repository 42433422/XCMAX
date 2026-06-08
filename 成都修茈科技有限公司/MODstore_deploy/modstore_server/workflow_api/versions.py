from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
    WorkflowVersion,
)
from modstore_server.workflow_api.helpers import (
    _restore_workflow_from_snapshot,
    _serialize_workflow_snapshot,
)
from modstore_server.workflow_api.schemas import PublishVersionBody

router = APIRouter()


@router.post("/{workflow_id}/versions/publish", summary="发布工作流版本")
async def publish_workflow_version(
    workflow_id: int,
    body: PublishVersionBody,
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

    snapshot = _serialize_workflow_snapshot(db, workflow)

    last = (
        db.query(WorkflowVersion)
        .filter(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_number.desc())
        .first()
    )
    next_ver = (last.version_number + 1) if last else 1

    version = WorkflowVersion(
        workflow_id=workflow_id,
        user_id=user.id,
        version_number=next_ver,
        note=body.note or "",
        graph_snapshot=json.dumps(snapshot, ensure_ascii=False),
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return {
        "id": version.id,
        "version_number": version.version_number,
        "note": version.note,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


@router.get("/{workflow_id}/versions", summary="获取工作流版本列表")
async def list_workflow_versions(
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

    versions = (
        db.query(WorkflowVersion)
        .filter(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_number.desc())
        .all()
    )
    return [
        {
            "id": v.id,
            "version_number": v.version_number,
            "note": v.note,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


@router.get("/{workflow_id}/versions/{version_id}", summary="获取工作流版本详情")
async def get_workflow_version(
    workflow_id: int,
    version_id: int,
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

    version = (
        db.query(WorkflowVersion)
        .filter(
            WorkflowVersion.id == version_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
        .first()
    )
    if not version:
        raise HTTPException(404, "版本不存在")

    return {
        "id": version.id,
        "version_number": version.version_number,
        "note": version.note,
        "graph_snapshot": json.loads(version.graph_snapshot or "{}"),
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


@router.post("/{workflow_id}/versions/{version_id}/rollback", summary="回滚工作流版本")
async def rollback_workflow_version(
    workflow_id: int,
    version_id: int,
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

    version = (
        db.query(WorkflowVersion)
        .filter(
            WorkflowVersion.id == version_id,
            WorkflowVersion.workflow_id == workflow_id,
        )
        .first()
    )
    if not version:
        raise HTTPException(404, "版本不存在")

    snapshot = json.loads(version.graph_snapshot or "{}")
    _restore_workflow_from_snapshot(db, workflow, snapshot)
    db.commit()
    return {"ok": True, "rolled_back_to": version.version_number}
