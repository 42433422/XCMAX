"""Dispatch-only service identity for handing GitHub tickets to Para.

The token behind this router can only create and read Mac control *code* tasks
that it created itself. It is not an admin token: it cannot list other tasks,
cancel, approve, read customer facts, or reach any other admin route.

Tokens are never stored in plaintext. Production keeps only SHA-256 digests in
``MODSTORE_PARA_DISPATCH_TOKEN_SHA256`` (comma separated), so a token can be
rotated by adding the new digest, switching callers, then removing the old one.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db
from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_store import TERMINAL, accept, transition, view

router = APIRouter(prefix="/api/service/mac-control", tags=["mac-control-dispatch"])

SERVICE_ACTOR = "service:para-dispatch"
TOKEN_DIGESTS_ENV = "MODSTORE_PARA_DISPATCH_TOKEN_SHA256"
_MIN_TOKEN_LENGTH = 32


def _configured_digests() -> list[str]:
    raw = os.environ.get(TOKEN_DIGESTS_ENV, "")
    digests = []
    for item in raw.split(","):
        item = item.strip().lower()
        if len(item) == 64 and all(c in "0123456789abcdef" for c in item):
            digests.append(item)
    return digests


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_dispatch_service(authorization: str = Header(default="")) -> str:
    """Authenticate the dispatch-only service token; never accepts user/admin JWTs."""
    digests = _configured_digests()
    if not digests:
        raise HTTPException(503, "派单服务令牌尚未配置")
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or len(token) < _MIN_TOKEN_LENGTH:
        raise HTTPException(401, "需要派单服务令牌")
    presented = token_digest(token)
    matched = False
    for expected in digests:
        # Compare against every digest so timing does not reveal which one matched.
        matched = hmac.compare_digest(presented, expected) or matched
    if not matched:
        raise HTTPException(401, "派单服务令牌无效")
    return SERVICE_ACTOR


class DispatchRequest(BaseModel):
    request_key: str = Field(min_length=8, max_length=128)
    message: str = Field(min_length=1, max_length=12000)
    tool: str = Field(default="cursor", pattern=r"^(cursor|codex|claude_code|trae)$")
    source_sha: str = Field(default="", pattern=r"^(?:[0-9a-f]{40})?$")
    github_issue: int | None = Field(default=None, gt=0)


def _service_view(task: MacControlTask) -> dict:
    payload = view(task)
    # Only the fields the dispatcher needs; no customer facts or delivery traces.
    keys = ("id", "state", "reason", "para_task_id", "device_id", "created_at", "updated_at")
    return {key: payload[key] for key in (*keys, "execution")} | {
        "terminal": task.state in TERMINAL
    }


@router.post("/tasks", status_code=202)
def create_code_task(
    body: DispatchRequest,
    actor: str = Depends(require_dispatch_service),
    db: Session = Depends(get_db),
):
    if os.environ.get("MODSTORE_MAC_CONTROL_ENABLED") != "1":
        raise HTTPException(503, "Mac 主控尚未启用，原有入口不受影响")
    if not os.environ.get("XCMAX_FACTORY_CAPABILITY_TOKEN"):
        raise HTTPException(503, "工厂执行能力尚未配置")
    request: dict = {
        "message": body.message,
        "target": "mac",
        "tool": body.tool,
        "mode": "code",
        "source_sha": body.source_sha,
        "ticket_id": None,
        "customer_id": None,
        "source": "github_issue_dispatch",
    }
    if body.github_issue:
        request["github_issue"] = body.github_issue
    try:
        task = accept(db, actor=actor, key=body.request_key, request=request)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"success": True, "task": _service_view(task), "accepted": True}


@router.get("/tasks/{task_id}")
def get_code_task(
    task_id: str,
    actor: str = Depends(require_dispatch_service),
    db: Session = Depends(get_db),
):
    task = db.get(MacControlTask, task_id)
    # Tasks created by admins or other identities are invisible to this token.
    if task is None or task.actor != actor:
        raise HTTPException(404, "任务不存在")
    if task.para_task_id and task.state in TERMINAL:
        from modstore_server.mac_control_transport import (
            ParaClient,
            ParaUnavailable,
            execution_view,
        )

        client = None
        try:
            client = ParaClient()
            snapshot = execution_view(client.task(task.para_task_id))
            if snapshot != view(task)["execution"]:
                transition(db, task, task.state, task.reason, snapshot=snapshot)
        except ParaUnavailable:
            pass
        finally:
            if client:
                client.close()
    return {"success": True, "task": _service_view(task), "checked_at": time.time()}
