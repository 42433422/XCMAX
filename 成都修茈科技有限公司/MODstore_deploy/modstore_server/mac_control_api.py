"""Admin-only durable Mac control and source-labelled fleet observations."""

from __future__ import annotations

import json
import os
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db, require_admin
from modstore_server.db.mac_control import (
    MacControlEvent,
    MacControlObservation,
    MacControlTask,
)
from modstore_server.mac_control_store import TERMINAL, accept, transition, view
from modstore_server.models import User

router = APIRouter(prefix="/api/admin/mac-control", tags=["mac-control"])


class TaskRequest(BaseModel):
    request_key: str = Field(min_length=8, max_length=128)
    message: str = Field(min_length=1, max_length=12000)
    target: Literal["mac", "windows"] = "mac"
    tool: Literal["codex", "claude_code", "cursor", "trae"] = "codex"
    mode: Literal["review", "code"] = "review"
    source_sha: str = Field(default="", pattern=r"^(?:[0-9a-f]{40})?$")
    ticket_id: int | None = Field(default=None, gt=0)
    customer_id: int | None = Field(default=None, gt=0)


@router.post("/tasks", status_code=202)
def create_task(
    body: TaskRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if os.environ.get("MODSTORE_MAC_CONTROL_ENABLED") != "1":
        raise HTTPException(503, "Mac 主控尚未启用，原有入口不受影响")
    if not os.environ.get("XCMAX_FACTORY_CAPABILITY_TOKEN"):
        raise HTTPException(503, "工厂执行能力尚未配置")
    request = body.model_dump(exclude={"request_key"})
    request["source"] = "admin"
    if body.ticket_id:
        from modstore_server.models_cs import CustomerServiceTicket

        ticket = db.get(CustomerServiceTicket, body.ticket_id)
        if ticket is None:
            raise HTTPException(404, "工单不存在")
        if body.customer_id and ticket.user_id != body.customer_id:
            raise HTTPException(409, "工单与客户不匹配")
        request["customer_id"] = ticket.user_id
    try:
        task = accept(db, actor=f"admin:{user.id}", key=body.request_key, request=request)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"success": True, "task": view(task), "accepted": True}


@router.get("/tasks")
def list_tasks(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(MacControlTask).order_by(MacControlTask.created_at.desc()).limit(100)
    return {
        "success": True,
        "tasks": [view(r) for r in rows],
        "source": "mac_control_tasks",
    }


@router.get("/tasks/{task_id}")
def task_detail(
    task_id: str,
    after: int = Query(0, ge=0),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = db.get(MacControlTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    events = (
        db.query(MacControlEvent)
        .filter(
            MacControlEvent.task_id == task_id,
            MacControlEvent.id > after,
        )
        .order_by(MacControlEvent.id)
        .limit(200)
        .all()
    )
    payload = view(task)
    request = payload["request"]
    if request.get("ticket_id") or request.get("customer_id"):
        from modstore_server.mac_control_facts import customer_facts

        payload["facts"] = customer_facts(db, request.get("customer_id"), request.get("ticket_id"))
    return {
        "success": True,
        "task": payload,
        "events": [
            {
                "id": e.id,
                "state": e.state,
                "attempt_id": e.attempt_id,
                "detail": json.loads(e.payload_json),
                "created_at": e.created_at,
            }
            for e in events
        ],
        "cursor": events[-1].id if events else after,
    }


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    task = db.query(MacControlTask).filter_by(id=task_id).with_for_update().first()
    if task is None:
        raise HTTPException(404, "任务不存在")
    if task.state not in TERMINAL:
        if task.lease_until > time.time():
            raise HTTPException(409, "正在同步执行状态，请稍后重试取消")
        state = "cancel_requested" if task.attempt_id else "cancelled"
        # Para currently exposes deletion, not confirmed executor cancellation.
        # Never delete an active task or falsely report that its process stopped.
        transition(
            db,
            task,
            state,
            "executor_stop_confirmation_required" if task.attempt_id else "",
        )
    return {"success": True, "task": view(task)}


@router.get("/fleet")
def fleet(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(MacControlObservation, "para")
    now = time.time()
    age = now - row.observed_at if row and row.observed_at else None
    return {
        "success": True,
        "enabled": os.environ.get("MODSTORE_MAC_CONTROL_ENABLED") == "1",
        "controller": "mac",
        "primary_device_id": os.environ.get("MODSTORE_PARA_DEVICE_ID", ""),
        "source": "para:/api/devices",
        "observed_at": row.observed_at if row else None,
        "checked_at": row.checked_at if row else None,
        "freshness": "missing" if age is None else "stale" if age > 90 else "fresh",
        "error": row.error if row else "not_observed",
        "devices": json.loads(row.payload_json) if row and row.observed_at else [],
    }


@router.get("/facts")
def facts(
    customer_id: int | None = Query(None, gt=0),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from modstore_server.mac_control_facts import customer_facts

    return {"success": True, **customer_facts(db, customer_id)}
