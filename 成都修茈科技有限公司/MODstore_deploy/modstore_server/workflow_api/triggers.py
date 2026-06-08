from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
    WorkflowTrigger,
)
from modstore_server.workflow_api.schemas import WorkflowTriggerBody
from modstore_server.workflow_event_runner import run_workflow_for_trigger

router = APIRouter()


@router.get("/{workflow_id}/triggers", summary="获取工作流触发器")
async def list_workflow_triggers(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    rows = db.query(WorkflowTrigger).filter(WorkflowTrigger.workflow_id == workflow_id).all()
    return [
        {
            "id": r.id,
            "trigger_type": r.trigger_type,
            "trigger_key": r.trigger_key,
            "config": json.loads(r.config_json or "{}"),
            "is_active": r.is_active,
        }
        for r in rows
    ]


@router.post("/{workflow_id}/triggers", summary="新增工作流触发器")
async def create_workflow_trigger(
    workflow_id: int,
    body: WorkflowTriggerBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    row = WorkflowTrigger(
        workflow_id=workflow_id,
        user_id=user.id,
        trigger_type=body.trigger_type.strip().lower(),
        trigger_key=(body.trigger_key or "").strip(),
        config_json=json.dumps(body.config or {}),
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if (row.trigger_type or "").strip().lower() == "cron":
        from modstore_server.workflow_scheduler import refresh_cron_trigger

        refresh_cron_trigger(row.id)
    return {"id": row.id, "ok": True}


@router.delete("/{workflow_id}/triggers/{trigger_id}", summary="删除或停用工作流触发器")
async def delete_workflow_trigger(
    workflow_id: int,
    trigger_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    row = (
        db.query(WorkflowTrigger)
        .filter(
            WorkflowTrigger.id == trigger_id,
            WorkflowTrigger.workflow_id == workflow_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "触发器不存在")
    row.is_active = False
    db.commit()
    from modstore_server.workflow_scheduler import unregister_cron_trigger

    unregister_cron_trigger(trigger_id)
    return {"ok": True}


@router.post(
    "/{workflow_id}/webhook-run", summary="Webhook 方式触发执行工作流（需已配置 webhook 触发器）"
)
async def webhook_run_workflow(
    workflow_id: int,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflow = (
        db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    )
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    trig = (
        db.query(WorkflowTrigger)
        .filter(
            WorkflowTrigger.workflow_id == workflow_id,
            WorkflowTrigger.trigger_type == "webhook",
            WorkflowTrigger.is_active.is_(True),
        )
        .first()
    )
    if not trig:
        raise HTTPException(400, "该工作流未配置激活的 webhook 触发器")
    try:
        return run_workflow_for_trigger(
            workflow_id=workflow_id,
            user_id=user.id,
            input_data=body or {},
        )
    except Exception as e:
        raise HTTPException(500, str(e)) from e
