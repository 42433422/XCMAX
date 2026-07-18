"""Loopback-only API for pairing XCMAX with the 客来来 desktop app."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field

from app.application import kellai_binding_app_service as kellai_binding_app

router = APIRouter(prefix="/api/kellai/binding", tags=["kellai-binding"])
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_KELLAI_BASE = "http://127.0.0.1:8793"


class ApproveBindingBody(BaseModel):
    request_id: str = Field(min_length=12, max_length=128)
    authorization_secret: str = Field(min_length=24, max_length=256)
    accepted_scopes: list[str] = Field(default_factory=list, max_length=10)
    access_token: str = Field(min_length=32, max_length=256)
    authorized_by: dict[str, Any] = Field(default_factory=dict)


class CancelBindingBody(BaseModel):
    request_id: str = Field(min_length=12, max_length=128)
    authorization_secret: str = Field(min_length=24, max_length=256)


class CopilotDecisionBody(BaseModel):
    note: str = Field(default="", max_length=500)


class FollowUpCompletionBody(BaseModel):
    outcome_result: Literal["success", "no_result", "failed"]


def _require_loopback(request: Request) -> None:
    client = request.client.host if request.client else ""
    if client not in _LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="客来来绑定仅允许本机桌面端访问")


def _require_xcmax_client(request: Request) -> None:
    """Keep customer data in the enterprise/client plane, never the admin shell."""
    _require_loopback(request)
    shell = str(request.headers.get("X-XCMAX-Client-Shell") or "").strip().lower()
    if shell not in {"enterprise", "desktop", "web"}:
        raise HTTPException(status_code=403, detail="客来来客户数据仅允许企业客户端访问")

    try:
        from app.application.session_account_meta import load_session_account_meta
        from app.infrastructure.auth.client_shell_session import resolve_session_id_from_request

        session_id = resolve_session_id_from_request(request)
        meta = load_session_account_meta(session_id) if session_id else None
    except (ImportError, RuntimeError, OSError):
        meta = None
    if isinstance(meta, dict) and (
        str(meta.get("account_kind") or "").strip().lower() == "admin"
        or bool(meta.get("market_is_admin"))
    ):
        raise HTTPException(status_code=403, detail="平台管理账号无权读取客户原始会话")


def _require_pairing_request(request: Request) -> None:
    _require_loopback(request)
    if request.headers.get("X-Kellai-Local-Pairing") != "1":
        raise HTTPException(status_code=403, detail="缺少本机配对请求标识")


def _client_actor(request: Request) -> int | None:
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        user = resolve_session_user(request)
        user_id = getattr(user, "id", None) if user is not None else None
        return int(user_id) if user_id is not None else None
    except (ImportError, RuntimeError, TypeError, ValueError):
        return None


def _kellai_get(path: str) -> dict[str, Any]:
    connection = kellai_binding_app.connection_credentials()
    if not connection:
        raise HTTPException(status_code=409, detail="客来来尚未连接")
    token = str(connection.get("access_token") or "")
    request = urllib.request.Request(
        f"{_KELLAI_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310 - fixed loopback URL
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"无法读取客来来本地数据：{exc}") from exc
    if not isinstance(payload, dict) or not payload.get("success"):
        raise HTTPException(status_code=503, detail="客来来没有返回可用客户数据")
    return payload


@router.get("/status")
def get_binding_status(request: Request):
    _require_xcmax_client(request)
    return {"success": True, "data": kellai_binding_app.binding_status()}


@router.post("/start")
def start_binding(request: Request):
    _require_xcmax_client(request)
    _require_pairing_request(request)
    return {"success": True, "data": kellai_binding_app.start_pairing()}


@router.get("/pending")
def get_pending_binding(request: Request):
    _require_pairing_request(request)
    return {"success": True, "data": kellai_binding_app.pending_for_kellai()}


@router.post("/approve")
def approve_binding(body: ApproveBindingBody, request: Request):
    _require_pairing_request(request)
    try:
        connection = kellai_binding_app.approve_pairing(
            request_id=body.request_id,
            authorization_secret=body.authorization_secret,
            accepted_scopes=body.accepted_scopes,
            access_token=body.access_token,
            authorized_by=body.authorized_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": connection}


@router.post("/cancel")
def cancel_binding(body: CancelBindingBody, request: Request):
    _require_pairing_request(request)
    try:
        kellai_binding_app.cancel_pairing(
            request_id=body.request_id,
            authorization_secret=body.authorization_secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True}


@router.post("/disconnect")
def disconnect_binding(request: Request):
    _require_xcmax_client(request)
    _require_pairing_request(request)

    try:
        kellai_binding_app.purge_all(actor=_client_actor(request))
    except kellai_binding_app.KellaiCopilotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    kellai_binding_app.disconnect()
    return {"success": True}


@router.get("/data-status")
def get_data_status(request: Request):
    _require_xcmax_client(request)
    payload = _kellai_get("/api/kellai/integrations/xcmax/data-status")
    return {"success": True, "data": payload.get("data") or {}}


@router.get("/customers")
def get_customers(request: Request, limit: int = 12):
    _require_xcmax_client(request)
    payload = _kellai_get(f"/api/kellai/integrations/xcmax/customers?limit={max(1, min(limit, 50))}")
    return {"success": True, "data": payload.get("data") or {}}


@router.get("/customers/{customer_id}/conversations")
def get_customer_conversations(
    request: Request,
    customer_id: int = Path(ge=1),
    limit: int = 30,
):
    _require_xcmax_client(request)
    payload = _kellai_get(
        f"/api/kellai/integrations/xcmax/customers/{customer_id}/conversations?limit={max(1, min(limit, 100))}"
    )
    return {"success": True, "data": payload.get("data") or {}}


@router.get("/customers/{customer_id}/copilot-drafts/latest")
def get_latest_copilot_draft(
    request: Request,
    customer_id: int = Path(ge=1),
):
    _require_xcmax_client(request)
    return {"success": True, "data": kellai_binding_app.latest_draft(customer_id)}


@router.get("/customers/{customer_id}/follow-up-tasks")
def get_customer_follow_up_tasks(
    request: Request,
    customer_id: int = Path(ge=1),
):
    _require_xcmax_client(request)
    return {
        "success": True,
        "data": {
            "tasks": kellai_binding_app.list_follow_up_tasks(customer_id),
            "metrics": kellai_binding_app.follow_up_metrics(customer_id),
        },
    }


@router.post("/customers/{customer_id}/copilot-drafts")
async def create_copilot_draft(
    request: Request,
    customer_id: int = Path(ge=1),
):
    _require_xcmax_client(request)
    _require_pairing_request(request)

    customer_payload = _kellai_get("/api/kellai/integrations/xcmax/customers?limit=50")
    customers = (customer_payload.get("data") or {}).get("customers") or []
    customer = next(
        (
            item
            for item in customers
            if isinstance(item, dict) and int(item.get("customer_id") or 0) == customer_id
        ),
        None,
    )
    if not isinstance(customer, dict):
        raise HTTPException(status_code=404, detail="未找到已授权的真实客户")
    conversation_payload = _kellai_get(
        f"/api/kellai/integrations/xcmax/customers/{customer_id}/conversations?limit=100"
    )
    messages = (conversation_payload.get("data") or {}).get("messages") or []
    try:
        draft = await kellai_binding_app.generate_draft(
            customer_id=customer_id,
            customer=customer,
            messages=messages if isinstance(messages, list) else [],
            actor=_client_actor(request),
            request=request,
        )
    except kellai_binding_app.KellaiCopilotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": draft}


@router.post("/copilot-drafts/{draft_id}/approve")
def approve_copilot_draft(
    draft_id: str,
    body: CopilotDecisionBody,
    request: Request,
):
    _require_xcmax_client(request)
    _require_pairing_request(request)

    try:
        draft = kellai_binding_app.decide_draft(
            draft_id=draft_id,
            decision="approve",
            actor=_client_actor(request),
            note=body.note,
        )
    except kellai_binding_app.KellaiCopilotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": draft}


@router.post("/copilot-drafts/{draft_id}/reject")
def reject_copilot_draft(
    draft_id: str,
    body: CopilotDecisionBody,
    request: Request,
):
    _require_xcmax_client(request)
    _require_pairing_request(request)

    try:
        draft = kellai_binding_app.decide_draft(
            draft_id=draft_id,
            decision="reject",
            actor=_client_actor(request),
            note=body.note,
        )
    except kellai_binding_app.KellaiCopilotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": draft}


@router.post("/copilot-drafts/{draft_id}/follow-up-task")
def create_copilot_follow_up_task(
    draft_id: str,
    request: Request,
):
    _require_xcmax_client(request)
    _require_pairing_request(request)

    try:
        task = kellai_binding_app.create_follow_up_task(
            draft_id=draft_id, actor=_client_actor(request)
        )
    except kellai_binding_app.KellaiCopilotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": task}


@router.post("/follow-up-tasks/{task_id}/complete")
def complete_customer_follow_up_task(
    task_id: str,
    body: FollowUpCompletionBody,
    request: Request,
):
    _require_xcmax_client(request)
    _require_pairing_request(request)

    try:
        task = kellai_binding_app.decide_follow_up_task(
            task_id=task_id,
            decision="complete",
            actor=_client_actor(request),
            outcome_result=body.outcome_result,
        )
    except kellai_binding_app.KellaiCopilotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": task}


@router.post("/follow-up-tasks/{task_id}/cancel")
def cancel_customer_follow_up_task(
    task_id: str,
    request: Request,
):
    _require_xcmax_client(request)
    _require_pairing_request(request)

    try:
        task = kellai_binding_app.decide_follow_up_task(
            task_id=task_id,
            decision="cancel",
            actor=_client_actor(request),
        )
    except kellai_binding_app.KellaiCopilotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "data": task}
