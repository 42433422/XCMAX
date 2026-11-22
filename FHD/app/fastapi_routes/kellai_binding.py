"""Loopback-only API for pairing XCMAX with the 客来来 desktop app."""

from __future__ import annotations

import urllib.request
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from app.application import kellai_binding_app_service as kellai_binding_app
from app.domain.shared_services.kellai_tool_contract import KELLAI_MESSAGE_MAX_LENGTH

router = APIRouter(prefix="/api/kellai/binding", tags=["kellai-binding"])
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_TOOL_ORIGINS = {
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://127.0.0.1:8793",
    "http://localhost:8793",
}
_DIRECT_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ApproveBindingBody(BaseModel):
    protocol_version: Literal[2]
    request_id: str = Field(min_length=12, max_length=128)
    authorization_secret: str = Field(min_length=24, max_length=256)
    accepted_scopes: list[str] = Field(default_factory=list, max_length=10)
    access_token: str = Field(min_length=32, max_length=256)
    authorized_by: dict[str, Any] = Field(default_factory=dict)


class CancelBindingBody(BaseModel):
    request_id: str = Field(min_length=12, max_length=128)
    authorization_secret: str = Field(min_length=24, max_length=256)


class StartBindingBody(BaseModel):
    requested_scopes: list[str] | None = Field(default=None, max_length=10)


class SendMessageBody(BaseModel):
    connection_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    client_request_id: str = Field(min_length=12, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    customer_id: int = Field(ge=1)
    channel_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    contact_id: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=KELLAI_MESSAGE_MAX_LENGTH)


def _require_loopback(request: Request) -> None:
    client = request.client.host if request.client else ""
    if client not in _LOCAL_HOSTS or request.url.hostname not in _LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="客来来绑定仅允许本机桌面端访问")
    origin = request.headers.get("origin")
    local_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin is not None and origin not in _TOOL_ORIGINS | {local_origin}:
        raise HTTPException(status_code=403, detail="拒绝跨站访问客来来授权")


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
    owners = kellai_binding_app.binding_owners()
    if owners and _client_actor(request) not in owners:
        raise HTTPException(status_code=403, detail="此客来来连接属于另一个 XCMAX 账号")
    connection = kellai_binding_app.connection_metadata()
    if (
        connection
        and connection.get("xcmax_user_id") is not None
        and str(connection.get("xcmax_tenant_id") or "") != _client_tenant(request)
    ):
        raise HTTPException(status_code=403, detail="此客来来连接属于另一个企业范围")


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


def _client_tenant(request: Request) -> str:
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        user = resolve_session_user(request)
        return str(getattr(user, "tenant_id", "") or "")
    except (ImportError, RuntimeError, TypeError, ValueError):
        return ""


def _open_kellai_request(request: urllib.request.Request, *, timeout: float):
    """Open the fixed loopback hop directly, independent of process proxy hooks."""
    return _DIRECT_LOOPBACK_OPENER.open(request, timeout=timeout)


def _scoped_connection(request: Request, scope: str) -> dict[str, Any]:
    _require_xcmax_client(request)
    try:
        return kellai_binding_app.scoped_connection(
            actor=_client_actor(request), tenant_id=_client_tenant(request), scope=scope
        )
    except kellai_binding_app.KellaiAuthorizationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _kellai_scoped_request(
    path: str, connection: dict[str, Any], body: dict[str, Any] | None = None
) -> dict[str, Any]:
    from app.infrastructure.kellai_client import KellaiRequestError

    try:
        return kellai_binding_app.request_kellai(
            path, connection, body, opener=_open_kellai_request
        )
    except KellaiRequestError as exc:
        detail = (
            {
                "code": exc.code,
                "message": str(exc),
                **({"request_not_dispatched": True} if exc.request_not_dispatched else {}),
            }
            if exc.code or exc.request_not_dispatched
            else str(exc)
        )
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


@router.get("/status")
def get_binding_status(request: Request):
    _require_xcmax_client(request)
    return {"success": True, "data": kellai_binding_app.binding_status()}


@router.post("/start")
def start_binding(request: Request, body: StartBindingBody | None = None):
    _require_xcmax_client(request)
    _require_pairing_request(request)
    try:
        data = kellai_binding_app.start_pairing(
            requested_scopes=body.requested_scopes if body else None,
            actor=_client_actor(request),
            tenant_id=_client_tenant(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": data}


@router.post("/handoff")
def claim_binding_handoff(request: Request):
    _require_pairing_request(request)
    try:
        pending = kellai_binding_app.claim_handoff()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not pending:
        raise HTTPException(status_code=409, detail="请先在 XCMAX 发起连接授权")
    return {"success": True, "data": pending}


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

    kellai_binding_app.disconnect()
    return {"success": True}


@router.get("/channels")
def get_channels(request: Request):
    connection = _scoped_connection(request, "channels.read")
    return _kellai_scoped_request("channels", connection)


@router.post("/messages/send")
def send_message(request: Request, body: SendMessageBody):
    try:
        _require_pairing_request(request)
        connection = _scoped_connection(request, "messages.send")
        if not body.content.strip() or not body.contact_id.strip():
            raise HTTPException(status_code=422, detail="接收人和消息内容不能为空")
    except HTTPException as exc:
        # This invocation has not entered the tool transport. It says nothing
        # about an earlier attempt using the same request ID.
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}
        raise HTTPException(
            status_code=exc.status_code, detail={**detail, "request_not_dispatched": True}
        ) from exc
    return _kellai_scoped_request("messages/send", connection, body.model_dump())


@router.get("/messages/requests/{client_request_id}")
def get_send_receipt(
    request: Request,
    client_request_id: str = Path(min_length=12, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
):
    connection = _scoped_connection(request, "messages.send")
    return _kellai_scoped_request(f"messages/requests/{client_request_id}", connection)


@router.get("/contacts")
def get_contacts(request: Request, limit: int = Query(default=50, ge=1, le=100)):
    connection = _scoped_connection(request, "messages.read")
    return _kellai_scoped_request(f"contacts?limit={limit}", connection)


@router.get("/contacts/{customer_id}/messages")
def get_contact_messages(
    request: Request,
    customer_id: int = Path(ge=1),
    connection_id: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    limit: int = Query(default=100, ge=1, le=100),
):
    connection = _scoped_connection(request, "messages.read")
    query = urlencode({"connection_id": connection_id, "limit": limit})
    return _kellai_scoped_request(f"contacts/{customer_id}/messages?{query}", connection)
