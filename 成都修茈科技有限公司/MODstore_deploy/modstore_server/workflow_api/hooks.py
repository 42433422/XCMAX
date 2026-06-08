from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    Workflow,
    WorkflowTrigger,
)
from modstore_server.workflow_event_runner import run_workflow_for_trigger

workflow_hooks_router = APIRouter(prefix="/api/workflow-hooks", tags=["workflow-hooks"])


@workflow_hooks_router.post("/webhook/{trigger_key}", summary="外部 Webhook 触发工作流（无需 JWT）")
async def public_webhook_run_workflow(
    trigger_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    trig = (
        db.query(WorkflowTrigger)
        .filter(
            WorkflowTrigger.trigger_key == trigger_key,
            WorkflowTrigger.trigger_type == "webhook",
            WorkflowTrigger.is_active.is_(True),
        )
        .first()
    )
    if not trig:
        raise HTTPException(404, "触发器不存在或未激活")

    cfg = json.loads(trig.config_json or "{}")
    secret = str(cfg.get("secret") or os.getenv("WORKFLOW_WEBHOOK_DEFAULT_SECRET") or "").strip()
    if secret:
        body_bytes = await request.body()
        sig = request.headers.get("X-Webhook-Signature") or request.headers.get(
            "X-Hub-Signature-256", ""
        )
        if not sig:
            raise HTTPException(401, "缺少签名头 X-Webhook-Signature")
        expected = "sha256=" + hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(403, "签名校验失败")

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        payload = {}

    try:
        return run_workflow_for_trigger(
            workflow_id=trig.workflow_id,
            user_id=trig.user_id,
            input_data=payload or {},
        )
    except Exception as e:
        raise HTTPException(500, str(e)) from e
