"""Planner 兼容对话服务（3d）：供宿主 /api/ai/* 与 Mod facade 共用。"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from app.application.agent_orchestrator.chat_trace import (
    attach_chat_trace_run,
    finalize_legacy_chat_run,
    start_legacy_chat_run,
)
from app.domain.ai.tier import (
    assert_p2_elevated_claim_or_raise,
    resolve_ai_tier,
    runtime_context_with_tier,
)
from app.domain.context.session_context import (
    planner_workflow_interrupt_reply,
    runtime_context_after_workflow_interrupt,
)
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
    _ensure_chat_db_read_authorized,
    _ensure_vector_index_if_needed,
    _merge_runtime_context_with_message_paths,
    _message_requires_db_read_token,
    _xcagi_chat_http_exc,
    _xcagi_chat_timeout_error_payload,
    _xcagi_chat_timeout_seconds,
    _xcagi_compat_reply_payload,
    _xcagi_planner_stream_bytes_async,
)
from app.infrastructure.llm.client import set_mode as set_llm_mode
from app.legacy.chat.legacy_chat_adapter import chat as run_agent_chat
from app.services.conversation.modstore_adapter import create_modstore_openai_client_from_request
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_SERVER_BOUND_CHAT_IDENTITY = "_server_bound_chat_identity"
_CHAT_SESSION_FALLBACK_SECRET = secrets.token_bytes(32)
_AUTHORIZATION_CONTEXT_KEYS = frozenset(
    {
        "access_context",
        "account_kind",
        "admin",
        "authorization",
        "claims",
        "entitlements",
        "is_admin",
        "permission",
        "permissions",
        "role",
        "scopes",
        "subject_user_id",
        "tenant",
        "tenant_id",
        "tenantid",
        "tier",
        "user_id",
        "userid",
        "workspace",
        "workspace_id",
        "workspace_root",
    }
)


@dataclass(frozen=True)
class _AuthenticatedChatPrincipal:
    """Server-verified identity used to scope chat state and audit records."""

    user_id: str
    tenant_id: str
    account_kind: str

    @property
    def scope(self) -> str:
        return f"tenant:{self.tenant_id}:account:{self.account_kind}:user:{self.user_id}"


def _chat_principal_from_user(
    user: Any,
    *,
    request: Request,
    account_kind: str = "",
) -> _AuthenticatedChatPrincipal | None:
    try:
        uid = int(getattr(user, "id", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        return None
    if uid <= 0 or not bool(getattr(user, "is_active", True)):
        return None

    raw_tenant = getattr(user, "tenant_id", None)
    if raw_tenant is None:
        raw_tenant = getattr(getattr(request, "state", None), "tenant_id", None)
    try:
        tenant_id = str(int(raw_tenant)) if raw_tenant is not None else "none"
    except (TypeError, ValueError):
        tenant_id = "none"

    kind = (
        str(
            account_kind
            or getattr(user, "tier", None)
            or getattr(user, "role", None)
            or "enterprise"
        )
        .strip()
        .lower()
    )
    kind = "".join(ch for ch in kind if ch.isalnum() or ch in {"-", "_"})[:32]
    kind = "admin" if kind in {"admin", "admin_portal", "super_admin", "owner"} else "enterprise"
    return _AuthenticatedChatPrincipal(
        user_id=str(uid),
        tenant_id=tenant_id,
        account_kind=kind or "enterprise",
    )


async def _resolve_authenticated_chat_principal(
    request: Request,
) -> _AuthenticatedChatPrincipal | None:
    """Resolve a session or mobile-JWT principal without trusting client IDs."""

    headers = getattr(request, "headers", {}) or {}
    cookies = getattr(request, "cookies", {}) or {}
    cookie_name = (os.environ.get("SESSION_COOKIE_NAME") or "session_id").strip()
    cookie_session = cookies.get(cookie_name) if isinstance(cookies, Mapping) else ""
    supplied_session_credential = bool(
        str(headers.get("X-Session-ID") or "").strip() or str(cookie_session or "").strip()
    )

    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        session_user = resolve_session_user(request)
    except RECOVERABLE_ERRORS:
        logger.debug("chat session identity lookup failed", exc_info=True)
        session_user = None
    session_principal = (
        _chat_principal_from_user(session_user, request=request)
        if session_user is not None
        else None
    )

    authorization = str(headers.get("Authorization") or "").strip()
    if not authorization:
        if session_principal is None and supplied_session_credential:
            raise HTTPException(status_code=401, detail="chat session invalid")
        return session_principal
    scheme, separator, token = authorization.partition(" ")
    token = token.strip()
    if not separator or scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="chat access token invalid")
    normalized_authorization = f"Bearer {token}"

    from app.security.mobile_jwt import verify_mobile_jwt

    payload = verify_mobile_jwt(token)
    # A Bearer may be a web JWT already accepted by resolve_session_user. Only
    # enter the mobile path when it verifies with the dedicated mobile issuer.
    if not payload:
        if session_principal is not None:
            return session_principal
        raise HTTPException(status_code=401, detail="chat access token invalid")
    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="mobile chat access token required")
    try:
        token_user_id = int(payload.get("user_id") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="mobile chat identity invalid") from None
    if token_user_id <= 0:
        raise HTTPException(status_code=401, detail="mobile chat identity invalid")

    # Reuse the mobile route's current-user projection so pairing scopes are
    # checked against the current DB row (disabled/revoked accounts fail closed).
    from app.fastapi_routes.mobile_api import get_mobile_user

    try:
        mobile_user = await get_mobile_user(request, authorization=normalized_authorization)
    except RECOVERABLE_ERRORS:
        logger.debug("chat mobile identity lookup failed", exc_info=True)
        raise HTTPException(status_code=401, detail="mobile chat identity unavailable") from None
    try:
        resolved_user_id = int(getattr(mobile_user, "id", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="mobile chat identity invalid") from None
    if resolved_user_id != token_user_id:
        raise HTTPException(status_code=401, detail="mobile chat identity mismatch")
    mobile_principal = _chat_principal_from_user(
        mobile_user,
        request=request,
        account_kind=str(payload.get("account_kind") or ""),
    )
    if mobile_principal is None:
        raise HTTPException(status_code=401, detail="mobile chat identity invalid")
    if session_principal is not None and (
        session_principal.user_id != mobile_principal.user_id
        or session_principal.tenant_id != mobile_principal.tenant_id
        or session_principal.account_kind != mobile_principal.account_kind
    ):
        raise HTTPException(status_code=401, detail="chat authentication subjects conflict")
    return session_principal or mobile_principal


def _client_chat_session_id(
    body: XcagiCompatChatBody | XcagiCompatChatBatchBody,
) -> str:
    context = body.context if isinstance(body.context, dict) else {}
    value = (
        getattr(body, "session_id", None)
        or context.get("session_id")
        or context.get("conversation_id")
        or ""
    )
    return str(value).strip()[:256]


def _scoped_chat_session_id(
    principal: _AuthenticatedChatPrincipal,
    client_session_id: str,
) -> str:
    configured = (os.environ.get("SECRET_KEY") or os.environ.get("XCAGI_SECRET_KEY") or "").strip()
    key = configured.encode("utf-8") if configured else _CHAT_SESSION_FALLBACK_SECRET
    payload = f"{principal.scope}\0{client_session_id}".encode()
    digest = hmac.new(key, payload, hashlib.sha256).hexdigest()[:48]
    return f"chat_{digest}"


async def _bind_chat_request_identity(
    request: Request,
    body: XcagiCompatChatBody | XcagiCompatChatBatchBody,
) -> XcagiCompatChatBody | XcagiCompatChatBatchBody:
    """Bind authenticated calls to server truth; preserve anonymous desktop compatibility."""

    principal = await _resolve_authenticated_chat_principal(request)
    # Anonymous/local legacy mode is deliberately separate. Strip the private
    # server marker even there so a JSON client can never forge it.
    if principal is None:
        if isinstance(body.context, dict) and _SERVER_BOUND_CHAT_IDENTITY in body.context:
            context = dict(body.context)
            context.pop(_SERVER_BOUND_CHAT_IDENTITY, None)
            return body.model_copy(update={"context": context})
        return body

    context: dict[str, Any] = {}
    for key, value in dict(body.context or {}).items():
        normalized = str(key).strip().lower().replace("-", "_")
        if normalized.startswith("dataset_") or normalized in _AUTHORIZATION_CONTEXT_KEYS:
            continue
        context[str(key)] = value
    context["user_id"] = principal.scope
    context["subject_user_id"] = int(principal.user_id)
    context["tenant_id"] = int(principal.tenant_id) if principal.tenant_id != "none" else None
    context["account_kind"] = principal.account_kind
    context["dataset_access_context"] = {
        "actor_id": principal.scope,
        "tenant_id": principal.tenant_id,
        "permissions": [],
        "is_admin": principal.account_kind == "admin",
    }
    context["dataset_tenant_id"] = principal.tenant_id
    context["dataset_permissions"] = []
    context["dataset_admin"] = principal.account_kind == "admin"
    context[_SERVER_BOUND_CHAT_IDENTITY] = True
    client_session_id = _client_chat_session_id(body)
    updates: dict[str, Any] = {
        # Keep the legacy body owner numeric for DB/approval compatibility.
        # The scoped identity used by AI/memory lives in runtime context.
        "user_id": principal.user_id,
        "context": context,
    }
    if client_session_id:
        bound_session_id = _scoped_chat_session_id(principal, client_session_id)
        context["session_id"] = bound_session_id
        context.pop("conversation_id", None)
        updates["session_id"] = bound_session_id
    return body.model_copy(update=updates)


def _derive_industry_from_session(request: Request) -> str:
    """单一真相源 + 自动派生：从 session account_kind + User.industry_id 派生 industry。

    1. admin 账号 → "管理端"（运维助手身份）
    2. 普通账号 → User.industry_id（涂料/考勤/批发/电商/餐饮/物流等）
    3. 兜底 → "通用"（业务管家身份）

    前端/手机端无需传 industry，后端自动判断。
    """
    try:
        from app.application.session_account_meta import load_session_account_meta
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        sid = _session_id_from_request(request)
        if not sid:
            return "通用"
        meta = load_session_account_meta(sid) or {}
        # 1. admin 账号 → 管理端
        if meta.get("account_kind") == "admin":
            return "管理端"
        # 2. 普通账号 → User.industry_id
        local_user_id = meta.get("local_user_id")
        if local_user_id:
            from app.db.models.user import User
            from app.db.session import get_db

            with get_db() as db:
                row = db.query(User.industry_id).filter(User.id == local_user_id).first()
                if row and row[0]:
                    return str(row[0]).strip()
    except Exception:  # noqa: BLE001  # best-effort 派生，失败回退到默认行业
        logger.debug("derive_industry_from_session failed", exc_info=True)
    return "通用"


def _attach_compat_chat_trace(
    payload: dict[str, Any],
    body: XcagiCompatChatBody | XcagiCompatChatBatchBody,
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    channel: str,
) -> dict[str, Any]:
    return attach_chat_trace_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=getattr(body, "user_id", None),
        source=getattr(body, "source", None),
        channel=channel,
    )


def _legacy_requires_token_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    raw_records = parsed.get("legacy_tool_records")
    legacy_tool_records = raw_records if isinstance(raw_records, list) else []
    data_payload = {
        "requires_token": True,
        "token_name": parsed.get("token_name"),
        "token_description": parsed.get("token_description"),
    }
    if legacy_tool_records:
        data_payload["legacy_tool_records"] = legacy_tool_records
    return {
        "success": True,
        "requires_token": True,
        "token_name": parsed.get("token_name"),
        "token_description": parsed.get("token_description"),
        "message": parsed.get("message"),
        "response": parsed.get("message"),
        "data": data_payload,
    }


def _reply_has_legacy_tool_records(reply: Any) -> bool:
    return isinstance(reply, dict) and isinstance(
        reply.get("legacy_tool_records") or reply.get("_tool_records"),
        list,
    )


def _clear_legacy_tool_result_if_reply_has_no_records(reply: Any) -> None:
    if _reply_has_legacy_tool_records(reply):
        return
    try:
        from app.legacy.chat.legacy_chat_adapter import clear_last_tool_result

        clear_last_tool_result()
    except RECOVERABLE_ERRORS:
        logger.debug("legacy planner local tool trace clear skipped", exc_info=True)


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _use_ai_chat_mainline(runtime_context: dict[str, Any] | None) -> bool:
    ctx = runtime_context if isinstance(runtime_context, dict) else {}
    if ctx.get("use_legacy_chat_adapter") is True:
        return False
    if ctx.get("use_ai_chat_mainline") is True:
        return True
    if _env_truthy("XCAGI_USE_LEGACY_CHAT_ADAPTER"):
        return False
    # Many legacy unit tests patch run_agent_chat directly. Keep pytest on the
    # historical path unless a test opts in, while production defaults to the
    # unified AIChatApplicationService mainline.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _legacy_chat_fallback_allowed(runtime_context: dict[str, Any] | None) -> bool:
    ctx = runtime_context if isinstance(runtime_context, dict) else {}
    if ctx.get("allow_legacy_chat_adapter") is True:
        return True
    if _env_truthy("XCAGI_ALLOW_LEGACY_CHAT_FALLBACK"):
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _merge_kitten_attachments(
    payload: dict[str, Any], kitten_extra: dict[str, Any] | None
) -> dict[str, Any]:
    if not kitten_extra:
        return payload
    enriched = dict(payload)
    data = enriched.get("data") if isinstance(enriched.get("data"), dict) else {}
    data = dict(data)
    for key, value in kitten_extra.items():
        if value is not None:
            data[key] = value
    enriched["data"] = data
    return enriched


async def _execute_ai_chat_mainline(
    body: XcagiCompatChatBody | XcagiCompatChatBatchBody,
    runtime_context: dict[str, Any],
    *,
    message: str | None = None,
    kitten_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.application.ai_chat_app_service import AIChatApplicationService

    service = AIChatApplicationService()
    file_context = runtime_context.get("file_context")
    if not isinstance(file_context, dict):
        file_context = runtime_context.get("file_analysis")
    if not isinstance(file_context, dict):
        file_context = {}
    message_text = str(message if message is not None else getattr(body, "message", "") or "")

    payload = await asyncio.to_thread(
        service.process_chat,
        user_id=str(runtime_context.get("user_id") or getattr(body, "user_id", None) or "default"),
        message=message_text,
        context=dict(runtime_context or {}),
        source=getattr(body, "source", None),
        file_context=file_context,
    )
    if not isinstance(payload, dict):
        payload = _xcagi_compat_reply_payload(str(payload))
    return _merge_kitten_attachments(payload, kitten_extra)


async def execute_compat_chat(request: Request, body: XcagiCompatChatBody) -> dict[str, Any]:
    body = await _bind_chat_request_identity(request, body)
    m = (body.mode or "").strip().lower()
    if m in ("online", "offline"):
        set_llm_mode(m)

    runtime_context, _ = _merge_runtime_context_with_message_paths(body.context, body.message)
    assert_p2_elevated_claim_or_raise(request)
    tier = resolve_ai_tier(request)
    runtime_context = runtime_context_with_tier(runtime_context, tier)
    try:
        from app.application.kitten_planner_context import (
            enrich_kitten_analyzer_runtime,
            kitten_reply_attachments,
        )

        runtime_context = await enrich_kitten_analyzer_runtime(runtime_context, body.message)
        kitten_extra = kitten_reply_attachments(runtime_context)
    except RECOVERABLE_ERRORS:
        logger.debug("kitten planner context enrich skipped", exc_info=True)
        kitten_extra = {}
    ok_read, read_req = _ensure_chat_db_read_authorized(
        request,
        message=body.message,
        provided_token=body.db_read_token,
    )
    if not ok_read and read_req:
        payload = {
            "success": True,
            "requires_token": True,
            "token_name": read_req.get("token_name"),
            "token_description": read_req.get("token_description"),
            "message": read_req.get("message"),
            "response": read_req.get("message"),
            "data": {
                "requires_token": True,
                "token_name": read_req.get("token_name"),
                "token_description": read_req.get("token_description"),
            },
        }
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=runtime_context,
            channel="compat_chat",
        )
    if ok_read and _message_requires_db_read_token(body.message):
        runtime_context["chat_db_read_authorized"] = True
    intr = planner_workflow_interrupt_reply(body.message)
    if intr is not None:
        cleared = runtime_context_after_workflow_interrupt(runtime_context)
        payload = _xcagi_compat_reply_payload(
            intr, runtime_context_update=cleared, kitten_attachments=kitten_extra or None
        )
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=cleared,
            channel="compat_chat",
        )

    vector_error = _ensure_vector_index_if_needed(body.message, runtime_context)
    if vector_error:
        payload = _xcagi_compat_reply_payload(vector_error, kitten_attachments=kitten_extra or None)
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=runtime_context,
            channel="compat_chat",
        )

    timeout = _xcagi_chat_timeout_seconds()
    pre_run = None
    planner_runtime_context = dict(runtime_context or {})
    if body.system_prompt:
        planner_runtime_context["system_prompt"] = body.system_prompt
    if body.db_write_token:
        planner_runtime_context["db_write_token_present"] = True
    if _use_ai_chat_mainline(planner_runtime_context):
        try:
            payload = await asyncio.wait_for(
                _execute_ai_chat_mainline(
                    body,
                    planner_runtime_context,
                    kitten_extra=kitten_extra or None,
                ),
                timeout=timeout,
            )
            if payload.get("run_id") or payload.get("agent_run_id"):
                return payload
            return _attach_compat_chat_trace(
                payload,
                body,
                message=body.message,
                runtime_context=planner_runtime_context,
                channel="compat_chat_mainline",
            )
        except TimeoutError:
            payload = _xcagi_chat_timeout_error_payload(timeout)
            return _attach_compat_chat_trace(
                payload,
                body,
                message=body.message,
                runtime_context=planner_runtime_context,
                channel="compat_chat_mainline",
            )
        except RECOVERABLE_ERRORS as e:
            if not _legacy_chat_fallback_allowed(planner_runtime_context):
                raise _xcagi_chat_http_exc(e) from e
            logger.warning(
                "AIChatApplicationService mainline failed; legacy fallback explicitly allowed: %s",
                e,
                exc_info=True,
            )
    try:
        workspace_root = os.environ.get("WORKSPACE_ROOT", os.getcwd())
        llm_client = create_modstore_openai_client_from_request(request)
        try:
            pre_run = start_legacy_chat_run(
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=getattr(body, "user_id", None),
                source=getattr(body, "source", None),
                channel="compat_chat",
            )
            planner_runtime_context["run_id"] = pre_run.run_id
            planner_runtime_context["agent_run_id"] = pre_run.run_id
        except RECOVERABLE_ERRORS:
            logger.debug("legacy planner AgentRun pre-create skipped", exc_info=True)
        reply = await asyncio.wait_for(
            asyncio.to_thread(
                run_agent_chat,
                body.message,
                runtime_context=planner_runtime_context or None,
                system_prompt=body.system_prompt,
                workspace_root=workspace_root,
                db_write_token=body.db_write_token,
                client=llm_client,
            ),
            timeout=timeout,
        )
        try:
            parsed = reply if isinstance(reply, dict) else None
            if parsed is None and isinstance(reply, str):
                parsed = json.loads(reply)
            if isinstance(parsed, dict) and parsed.get("requires_token"):
                payload = _legacy_requires_token_payload(parsed)
                if pre_run is not None:
                    return finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=body.message,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat",
                    )
                return _attach_compat_chat_trace(
                    payload,
                    body,
                    message=body.message,
                    runtime_context=planner_runtime_context,
                    channel="compat_chat",
                )
        except json.JSONDecodeError:
            pass
        _clear_legacy_tool_result_if_reply_has_no_records(reply)
    except TimeoutError:
        payload = _xcagi_chat_timeout_error_payload(timeout)
        if pre_run is not None:
            return finalize_legacy_chat_run(
                pre_run.run_id,
                payload,
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=getattr(body, "user_id", None),
                source=getattr(body, "source", None),
                channel="compat_chat",
            )
        return _attach_compat_chat_trace(
            payload,
            body,
            message=body.message,
            runtime_context=planner_runtime_context,
            channel="compat_chat",
        )
    except RECOVERABLE_ERRORS as e:
        if pre_run is not None:
            err_payload = {
                "success": False,
                "message": str(e),
                "response": str(e),
                "data": {"error": str(e)},
            }
            finalize_legacy_chat_run(
                pre_run.run_id,
                err_payload,
                message=body.message,
                runtime_context=planner_runtime_context,
                user_id=getattr(body, "user_id", None),
                source=getattr(body, "source", None),
                channel="compat_chat",
            )
        raise _xcagi_chat_http_exc(e) from e
    payload = _xcagi_compat_reply_payload(reply, kitten_attachments=kitten_extra or None)
    if pre_run is not None:
        return finalize_legacy_chat_run(
            pre_run.run_id,
            payload,
            message=body.message,
            runtime_context=planner_runtime_context,
            user_id=getattr(body, "user_id", None),
            source=getattr(body, "source", None),
            channel="compat_chat",
        )
    return _attach_compat_chat_trace(
        payload,
        body,
        message=body.message,
        runtime_context=planner_runtime_context,
        channel="compat_chat",
    )


async def execute_compat_chat_batch(
    request: Request, body: XcagiCompatChatBatchBody
) -> dict[str, Any]:
    body = await _bind_chat_request_identity(request, body)
    msgs = [str(x).strip() for x in (body.messages or []) if str(x).strip()]
    if not msgs:
        raise HTTPException(status_code=400, detail="messages 须为非空字符串数组")
    assert_p2_elevated_claim_or_raise(request)
    batch_tier = resolve_ai_tier(request)
    m = (body.mode or "").strip().lower()
    if m in ("online", "offline"):
        set_llm_mode(m)
    results: list[dict[str, Any]] = []
    timeout = _xcagi_chat_timeout_seconds()
    rolling_ctx = body.context
    llm_client = create_modstore_openai_client_from_request(request)
    for txt in msgs:
        runtime_context, _ = _merge_runtime_context_with_message_paths(rolling_ctx, txt)
        runtime_context = runtime_context_with_tier(runtime_context, batch_tier)
        ok_read, read_req = _ensure_chat_db_read_authorized(
            request,
            message=txt,
            provided_token=body.db_read_token,
        )
        if not ok_read and read_req:
            payload = {
                "success": True,
                "requires_token": True,
                "token_name": read_req.get("token_name"),
                "token_description": read_req.get("token_description"),
                "message": read_req.get("message"),
                "response": read_req.get("message"),
                "data": {
                    "requires_token": True,
                    "token_name": read_req.get("token_name"),
                    "token_description": read_req.get("token_description"),
                },
            }
            results.append(
                _attach_compat_chat_trace(
                    payload,
                    body,
                    message=txt,
                    runtime_context=runtime_context,
                    channel="compat_chat_batch",
                )
            )
            continue
        if ok_read and _message_requires_db_read_token(txt):
            runtime_context["chat_db_read_authorized"] = True
        intr = planner_workflow_interrupt_reply(txt)
        if intr is not None:
            cleared = runtime_context_after_workflow_interrupt(runtime_context)
            rolling_ctx = cleared
            payload = _xcagi_compat_reply_payload(intr, runtime_context_update=cleared)
            results.append(
                _attach_compat_chat_trace(
                    payload,
                    body,
                    message=txt,
                    runtime_context=cleared,
                    channel="compat_chat_batch",
                )
            )
            continue
        vector_error = _ensure_vector_index_if_needed(txt, runtime_context)
        if vector_error:
            payload = _xcagi_compat_reply_payload(vector_error)
            results.append(
                _attach_compat_chat_trace(
                    payload,
                    body,
                    message=txt,
                    runtime_context=runtime_context,
                    channel="compat_chat_batch",
                )
            )
            continue
        pre_run = None
        planner_runtime_context = dict(runtime_context or {})
        if body.system_prompt:
            planner_runtime_context["system_prompt"] = body.system_prompt
        if body.db_write_token:
            planner_runtime_context["db_write_token_present"] = True
        if _use_ai_chat_mainline(planner_runtime_context):
            try:
                payload = await asyncio.wait_for(
                    _execute_ai_chat_mainline(
                        body,
                        planner_runtime_context,
                        message=txt,
                    ),
                    timeout=timeout,
                )
                results.append(
                    payload
                    if payload.get("run_id") or payload.get("agent_run_id")
                    else _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch_mainline",
                    )
                )
                continue
            except TimeoutError:
                payload = _xcagi_chat_timeout_error_payload(timeout)
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch_mainline",
                    )
                )
                continue
            except RECOVERABLE_ERRORS as e:
                if not _legacy_chat_fallback_allowed(planner_runtime_context):
                    err = _xcagi_chat_http_exc(e)
                    results.append(
                        {
                            "success": False,
                            "message": (
                                err.detail if isinstance(err.detail, str) else str(err.detail)
                            ),
                            "response": err.detail
                            if isinstance(err.detail, str)
                            else str(err.detail),
                            "data": {"error": str(e)},
                        }
                    )
                    continue
                logger.warning(
                    "AIChatApplicationService batch mainline failed; legacy fallback explicitly allowed: %s",
                    e,
                    exc_info=True,
                )
        try:
            try:
                pre_run = start_legacy_chat_run(
                    message=txt,
                    runtime_context=planner_runtime_context,
                    user_id=getattr(body, "user_id", None),
                    source=getattr(body, "source", None),
                    channel="compat_chat_batch",
                )
                planner_runtime_context["run_id"] = pre_run.run_id
                planner_runtime_context["agent_run_id"] = pre_run.run_id
            except RECOVERABLE_ERRORS:
                logger.debug("legacy batch planner AgentRun pre-create skipped", exc_info=True)
            workspace_root = os.environ.get("WORKSPACE_ROOT", os.getcwd())
            reply = await asyncio.wait_for(
                asyncio.to_thread(
                    run_agent_chat,
                    txt,
                    runtime_context=planner_runtime_context or None,
                    system_prompt=body.system_prompt,
                    workspace_root=workspace_root,
                    db_write_token=body.db_write_token,
                    client=llm_client,
                ),
                timeout=timeout,
            )
            try:
                parsed = reply if isinstance(reply, dict) else None
                if parsed is None and isinstance(reply, str):
                    parsed = json.loads(reply)
                if isinstance(parsed, dict) and parsed.get("requires_token"):
                    payload = _legacy_requires_token_payload(parsed)
                    if pre_run is not None:
                        results.append(
                            finalize_legacy_chat_run(
                                pre_run.run_id,
                                payload,
                                message=txt,
                                runtime_context=planner_runtime_context,
                                user_id=getattr(body, "user_id", None),
                                source=getattr(body, "source", None),
                                channel="compat_chat_batch",
                            )
                        )
                    else:
                        results.append(
                            _attach_compat_chat_trace(
                                payload,
                                body,
                                message=txt,
                                runtime_context=planner_runtime_context,
                                channel="compat_chat_batch",
                            )
                        )
                    continue
            except json.JSONDecodeError:
                pass
            _clear_legacy_tool_result_if_reply_has_no_records(reply)
            payload = _xcagi_compat_reply_payload(reply)
            if pre_run is not None:
                results.append(
                    finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat_batch",
                    )
                )
            else:
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch",
                    )
                )
        except TimeoutError:
            payload = _xcagi_chat_timeout_error_payload(timeout)
            if pre_run is not None:
                results.append(
                    finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat_batch",
                    )
                )
            else:
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch",
                    )
                )
        except RECOVERABLE_ERRORS as e:
            err = _xcagi_chat_http_exc(e)
            payload = {
                "success": False,
                "message": err.detail if isinstance(err.detail, str) else str(err.detail),
            }
            if pre_run is not None:
                results.append(
                    finalize_legacy_chat_run(
                        pre_run.run_id,
                        payload,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        user_id=getattr(body, "user_id", None),
                        source=getattr(body, "source", None),
                        channel="compat_chat_batch",
                    )
                )
            else:
                results.append(
                    _attach_compat_chat_trace(
                        payload,
                        body,
                        message=txt,
                        runtime_context=planner_runtime_context,
                        channel="compat_chat_batch",
                    )
                )
    ok = all(r.get("success") for r in results)
    return {"success": ok, "batch": True, "results": results, "count": len(results)}


def _recent_history(svc, user_id: str) -> list[dict]:
    """从对话服务里尽力读取该用户最近历史（供 persona L2/L3 周期推断使用）。

    取不到则返回空列表（容错，绝不因此中断流式响应）。
    """
    try:
        contexts = getattr(svc, "contexts", None)
        if not contexts:
            return []
        ctx = contexts.get(user_id)
        hist = getattr(ctx, "conversation_history", None) if ctx else None
        return list(hist) if hist else []
    except Exception:  # noqa: BLE001
        return []


def _resolve_chat_user_id(request: Request, body: XcagiCompatChatBody) -> str:
    """Resolve the already-bound stream identity or anonymous legacy fallback.

    ``compat_chat_stream_async`` first replaces ``body.user_id`` with the
    authenticated session/mobile-JWT subject. ``X-User-Id`` is therefore only
    consulted for the explicit unauthenticated desktop compatibility path.
    """
    context = body.context if isinstance(body.context, dict) else {}
    if context.get(_SERVER_BOUND_CHAT_IDENTITY) is True and context.get("user_id"):
        return str(context["user_id"])
    uid = getattr(body, "user_id", None)
    if uid:
        return str(uid)
    try:
        hdr = request.headers.get("X-User-Id") or request.headers.get("X-User-ID")
        if hdr and str(hdr).strip():
            return str(hdr).strip()
    except Exception:  # noqa: BLE001
        pass
    return "1"


async def compat_chat_stream_async(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str | None = None
):
    body = await _bind_chat_request_identity(request, body)
    # 注入 persona system_prompt（前端没传时用 persona 系统生成去客服腔 prompt）
    if not body.system_prompt and body.message:
        try:
            from app.services.conversation.manager import get_ai_conversation_service

            svc = get_ai_conversation_service()
            persona_svc = getattr(svc, "persona_service", None)
            logger.info(
                "persona_inject check: has_persona=%s msg=%s",
                persona_svc is not None,
                body.message[:50],
            )
            if persona_svc is not None:
                user_id = _resolve_chat_user_id(request, body)
                ctx = body.context or {}
                # 单一真相源 + 自动派生：优先用前端传的 industry；
                # 没传则从 session account_kind 派生（admin → 管理端，其他 → 通用）
                industry = ctx.get("industry") if isinstance(ctx, dict) else None
                if not industry:
                    industry = _derive_industry_from_session(request)
                history = _recent_history(svc, user_id)
                logger.info(
                    "persona_inject ctx=%s industry=%s history_len=%d",
                    ctx,
                    industry,
                    len(history),
                )
                prompt, _params = await persona_svc.build_prompt_from_message(
                    user_id=user_id,
                    message=body.message,
                    history=history,
                    industry=industry,
                    context_prompt="",
                )
                body.system_prompt = prompt
                logger.info("persona_inject OK: prompt_len=%d", len(prompt))
        except Exception as e:  # noqa: BLE001  # persona 注入为尽力而为，失败不应中断流式响应
            logger.warning("persona_inject FAIL: %s", e, exc_info=True)

    tier = ai_tier or resolve_ai_tier(request)
    async for chunk in _xcagi_planner_stream_bytes_async(request, body, ai_tier=tier):
        yield chunk
