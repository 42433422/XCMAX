"""Authenticated desktop/client bridge for the canonical enterprise-CS thread.

The desktop database has node-local user and conversation ids, so dedicated-CS
messages must never be copied to production through the generic IM sync stream.
The local route forwards the market token bound to the current FHD session; the
remote route validates that token against MODstore and resolves the canonical
production user by ``market_user_id``.
"""

from __future__ import annotations

import logging
import os
import time
from hashlib import sha256
from typing import Any, cast

import httpx
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.application.enterprise_cs_automation import (
    EnterpriseCsAutomationService,
    process_enterprise_cs_customer_message,
)
from app.application.im_app_service import (
    ENTERPRISE_DEDICATED_CS_USERNAME,
    ImApplicationService,
    ensure_im_tables,
)
from app.db import HostSessionLocal, get_host_engine
from app.db.models.user import User
from app.infrastructure.auth.dependencies import (
    CurrentUser,
    require_identified_user,
    session_id_from_request,
)
from app.infrastructure.topology import FHD_API_BASE_URL
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["im-v0"])
_schema_ready = False
_REMOTE_PATH = "/api/im/enterprise-cs/remote/messages"
_IM_UNAVAILABLE = "企业专属客服暂时不可用，请稍后重试"
_identity_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    ensure_im_tables(get_host_engine())
    _schema_ready = True


def _bearer_token(request: Request) -> str:
    raw = str(request.headers.get("Authorization") or "").strip()
    if not raw.lower().startswith("bearer "):
        return ""
    return raw[7:].strip()


def _market_user_blob(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    raw: dict[str, Any] = payload
    if isinstance(payload.get("data"), dict):
        raw = payload["data"]
    user_blob = raw.get("user")
    if isinstance(user_blob, dict):
        return dict(user_blob)
    return dict(raw)


async def _validate_market_identity(request: Request) -> dict[str, Any]:
    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="缺少市场登录凭证")
    cache_key = sha256(token.encode("utf-8")).hexdigest()
    cached = _identity_cache.get(cache_key)
    if cached is not None and cached[0] > time.monotonic():
        return dict(cached[1])

    from app.fastapi_routes import market_account

    result = await market_account._proxy_json(
        "GET",
        "/api/auth/me",
        authorization=f"Bearer {token}",
        return_error_payload=True,
    )
    if isinstance(result, JSONResponse):
        raise HTTPException(status_code=503, detail="市场身份服务暂时不可用")
    if not isinstance(result, dict):
        raise HTTPException(status_code=401, detail="市场登录凭证无效")
    if result.get("__proxy_error__"):
        status = int(result.get("status_code") or 503)
        raise HTTPException(
            status_code=401 if status in {401, 403} else 503,
            detail="市场登录凭证无效" if status in {401, 403} else "市场身份服务暂时不可用",
        )

    identity = _market_user_blob(result)
    if identity.get("ok") is False or identity.get("success") is False:
        raise HTTPException(status_code=401, detail="市场登录凭证无效")
    try:
        market_user_id = int(identity.get("id") or 0)
    except (TypeError, ValueError):
        market_user_id = 0
    username = str(identity.get("username") or "").strip()
    if market_user_id <= 0 or not username:
        raise HTTPException(status_code=401, detail="市场账号身份不完整")
    if bool(identity.get("is_admin")) or not bool(identity.get("is_enterprise")):
        raise HTTPException(status_code=403, detail="仅企业客户账号可使用企业专属客服")
    if username.lower() == ENTERPRISE_DEDICATED_CS_USERNAME:
        raise HTTPException(status_code=403, detail="客服系统账号不能作为客户发起会话")
    verified = {"market_user_id": market_user_id, "username": username}
    try:
        ttl = min(60.0, max(5.0, float(os.environ.get("XCAGI_CS_IDENTITY_CACHE_SECONDS", "15"))))
    except ValueError:
        ttl = 15.0
    _identity_cache[cache_key] = (time.monotonic() + ttl, verified)
    if len(_identity_cache) > 2048:
        now = time.monotonic()
        for key, value in list(_identity_cache.items()):
            if value[0] <= now:
                _identity_cache.pop(key, None)
    return dict(verified)


def _resolve_canonical_customer(db: Any, identity: dict[str, Any]) -> User:
    market_user_id = int(identity["market_user_id"])
    username = str(identity["username"]).strip()
    user = (
        db.execute(select(User).where(User.market_user_id == market_user_id).limit(1))
        .scalars()
        .first()
    )
    if user is None:
        user = (
            db.execute(select(User).where(func.lower(User.username) == username.lower()).limit(1))
            .scalars()
            .first()
        )
    if user is None or not bool(user.is_active):
        raise HTTPException(status_code=403, detail="企业账号尚未同步到客户系统")
    bound_market_id = getattr(user, "market_user_id", None)
    if bound_market_id is not None and int(bound_market_id) != market_user_id:
        raise HTTPException(status_code=409, detail="企业账号绑定信息冲突，请转人工处理")
    if bound_market_id is None:
        user.market_user_id = market_user_id
        db.commit()
        db.refresh(user)
    return cast(User, user)


def _canonical_thread(db: Any, customer: User, *, limit: int) -> dict[str, Any]:
    svc = ImApplicationService(db)
    cs_id = svc.enterprise_cs_user_id()
    if cs_id is None:
        raise HTTPException(status_code=503, detail="企业专属客服通道未就绪")
    conversation = svc.get_or_create_direct(int(customer.id), int(cs_id))
    conversation_id = int(conversation["id"])
    messages = svc.list_messages(conversation_id, int(customer.id), limit=limit)
    if messages:
        try:
            svc.mark_read(
                conversation_id,
                int(customer.id),
                int(messages[-1]["id"]),
                record_sync=False,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("canonical CS mark-read skipped", exc_info=True)
    state = EnterpriseCsAutomationService(db).public_state(conversation_id)
    return {
        "success": True,
        "conversation": {
            "id": conversation_id,
            "title": "企业专属客服",
            "is_enterprise_dedicated_cs": True,
            **state,
        },
        "messages": messages,
    }


@router.get(_REMOTE_PATH)
async def remote_enterprise_cs_messages(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
):
    """Production SSOT read endpoint; identity comes only from a verified market JWT."""
    identity = await _validate_market_identity(request)
    _ensure_schema()
    db = HostSessionLocal()
    try:
        customer = _resolve_canonical_customer(db, identity)
        return _canonical_thread(db, customer, limit=limit)
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS:
        logger.exception("remote_enterprise_cs_messages")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
    finally:
        db.close()


@router.post(_REMOTE_PATH)
async def remote_enterprise_cs_send(
    request: Request,
    background_tasks: BackgroundTasks,
    body: dict = Body(default_factory=dict),
):
    """Write one customer message using the canonical production user id."""
    text = str(body.get("body") or "").strip()[:4000]
    if not text:
        return JSONResponse({"success": False, "message": "消息不能为空"}, status_code=400)
    identity = await _validate_market_identity(request)
    _ensure_schema()
    db = HostSessionLocal()
    try:
        customer = _resolve_canonical_customer(db, identity)
        svc = ImApplicationService(db)
        cs_id = svc.enterprise_cs_user_id()
        if cs_id is None:
            raise HTTPException(status_code=503, detail="企业专属客服通道未就绪")
        conversation = svc.get_or_create_direct(int(customer.id), int(cs_id))
        conversation_id = int(conversation["id"])
        result = svc.send_message(
            conversation_id,
            int(customer.id),
            text,
            origin="customer",
            record_sync=False,
        )
        message = dict(result["message"])
        message["is_self"] = True
        message_id = int(message.get("id") or 0)
        background_tasks.add_task(
            process_enterprise_cs_customer_message,
            conversation_id,
            int(customer.id),
            message_id,
            text,
        )
        return {
            "success": True,
            "conversation_id": conversation_id,
            "message": message,
            "state": EnterpriseCsAutomationService(db).public_state(conversation_id),
        }
    except HTTPException:
        raise
    except ValueError:
        return JSONResponse({"success": False, "message": "消息参数无效"}, status_code=400)
    except RECOVERABLE_ERRORS:
        logger.exception("remote_enterprise_cs_send")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
    finally:
        db.close()


async def _local_market_token(request: Request) -> str:
    from app.fastapi_routes.market_account import session_market_token

    sid = session_id_from_request(request)
    if not sid:
        return ""
    # Production re-validates this token against MODstore.  Avoid validating a
    # second time on every 2.5 s desktop poll.
    return str(session_market_token(sid) or "").strip()


def _public_fhd_base_url() -> str:
    return (
        str(
            os.environ.get("XCAGI_PUBLIC_FHD_BASE_URL")
            or os.environ.get("XCAGI_ENTERPRISE_CS_REMOTE_BASE_URL")
            or FHD_API_BASE_URL
        )
        .strip()
        .rstrip("/")
    )


async def _proxy_to_production(
    method: str,
    token: str,
    *,
    body: dict[str, Any] | None = None,
) -> JSONResponse:
    url = f"{_public_fhd_base_url()}{_REMOTE_PATH}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            if method.upper() == "POST":
                prime = await client.get(url, headers=headers)
                if prime.status_code >= 400:
                    response = prime
                else:
                    csrf = str(client.cookies.get("csrf_token") or "").strip()
                    post_headers = {**headers, "Content-Type": "application/json"}
                    if csrf:
                        post_headers["X-CSRF-Token"] = csrf
                    response = await client.post(url, headers=post_headers, json=body or {})
            else:
                response = await client.get(url, headers=headers)
    except httpx.HTTPError:
        logger.exception("enterprise CS production bridge unavailable")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=502)
    try:
        payload = response.json()
    except ValueError:
        payload = {"success": False, "message": _IM_UNAVAILABLE}
    if not isinstance(payload, dict):
        payload = {"success": False, "message": _IM_UNAVAILABLE}
    return JSONResponse(payload, status_code=response.status_code)


@router.get("/api/im/enterprise-cs/messages")
async def local_enterprise_cs_messages(
    request: Request,
    _user: CurrentUser = Depends(require_identified_user),
):
    """Desktop/browser bridge: never trusts or forwards local database ids."""
    token = await _local_market_token(request)
    if not token:
        return JSONResponse({"success": False, "message": "请重新登录企业账号"}, status_code=401)
    return await _proxy_to_production("GET", token)


@router.post("/api/im/enterprise-cs/messages")
async def local_enterprise_cs_send(
    request: Request,
    body: dict = Body(default_factory=dict),
    _user: CurrentUser = Depends(require_identified_user),
):
    """Desktop/browser bridge for a customer send; only the text crosses nodes."""
    token = await _local_market_token(request)
    if not token:
        return JSONResponse({"success": False, "message": "请重新登录企业账号"}, status_code=401)
    return await _proxy_to_production("POST", token, body={"body": body.get("body")})
