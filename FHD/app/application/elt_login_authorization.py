"""Session-bound login notice receipts for the existing bounded ELT model pipeline."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC
from typing import Literal, cast

import httpx
import jwt
from fastapi import Request, Response

from app.utils.operational_errors import RECOVERABLE_ERRORS

NOTICE_VERSION = "2026-11-01-draft"
# The current legal text is a review draft. Publishing a verified notice is a
# separate reviewed release change; runtime configuration cannot bypass this.
NOTICE_PUBLISHED = False
NOTICE_COOKIE = "xcagi_elt_notice"
NOTICE_PURPOSE = "elt_file_processing"
_AUDIENCE = "xcagi-elt-login-notice"
_route_scope: ContextVar[dict | None] = ContextVar("elt_login_model_route", default=None)
_session_scope: ContextVar[tuple[str, int] | None] = ContextVar("elt_login_session", default=None)
logger = logging.getLogger(__name__)


class _LoginNoticeGrant(dict):
    """Keep the verified credential selector out of JSON, repr and audit mappings."""

    __slots__ = ("_session_id",)

    def __init__(self, receipt: dict, session_id: str):
        super().__init__(receipt)
        self._session_id = session_id


def _secret() -> str:
    key = os.environ.get("SECRET_KEY", "").strip()
    if len(key) < 32:
        raise ValueError("notice receipt signing unavailable")
    return key


def _session_digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


def notice_operation_scopes() -> dict:
    from app.application.reviewed_excel_budget import MAX_CLASSIFICATION_BATCHES, MAX_REQUEST_BYTES
    from app.application.reviewed_excel_evidence import (
        MAX_MODEL_CELLS,
        MAX_MODEL_TEXT_BYTES,
        MAX_VALUE_CHARS,
    )

    return {
        "template_candidates": {"max_cells": 100, "max_chars_per_cell": 160},
        "classification": {
            "max_cells": MAX_MODEL_CELLS,
            "max_chars_per_cell": MAX_VALUE_CHARS,
            "max_model_text_bytes": MAX_MODEL_TEXT_BYTES,
            "max_request_bytes": MAX_REQUEST_BYTES,
            "max_calls_per_round": 4,
            "max_classification_batches": MAX_CLASSIFICATION_BATCHES,
        },
    }


def _active_session(session_id: str) -> dict | None:
    from app.db.models.user import Session
    from app.db.session import get_host_db
    from app.utils.time import utc_now_naive

    with get_host_db() as db:
        row = db.query(Session).filter(Session.session_id == session_id).first()
        if row is None or row.expires_at <= utc_now_naive() or not row.user.is_active:
            return None
        if row.user.tenant_id is None or row.impersonating_market_user_id is not None:
            return None
        return {
            "owner": row.user_id,
            "tenant": row.user.tenant_id,
            "expires": int(row.expires_at.replace(tzinfo=UTC).timestamp()),
        }


def _platform_url() -> str:
    return (
        (
            os.environ.get("XCAGI_MARKET_BASE_URL")
            or os.environ.get("MODSTORE_PLATFORM_URL")
            or "http://127.0.0.1:8765"
        )
        .strip()
        .rstrip("/")
    )


async def _resolve_login_route(session_id: str) -> dict | None:
    from app.application.reviewed_excel_template import configured_template_llm_provider
    from app.fastapi_routes.market_account import session_market_token

    if configured_template_llm_provider() != "platform":
        return None
    token = session_market_token(session_id)
    if not token:
        return None
    base = _platform_url()
    async with httpx.AsyncClient(
        timeout=3.0, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        response = await client.get(f"{base}/api/llm/resolve-chat-default")
        response.raise_for_status()
        route = response.json()
    if not isinstance(route, dict) or not route.get("ok"):
        return None
    provider, model = route.get("provider"), route.get("model")
    if not all(
        isinstance(value, str) and 0 < len(value.strip()) <= 200 for value in (provider, model)
    ):
        return None
    return {"base": base, "provider": provider.strip(), "model": model.strip()}


async def attach_login_notice(response: Response, result: dict, body: dict) -> Response:
    """Only an explicit successful credential login can establish this receipt."""
    if not result.get("success"):
        return response
    response.delete_cookie(NOTICE_COOKIE, path="/")
    if not NOTICE_PUBLISHED or body.get("data_processing_notice_version") != NOTICE_VERSION:
        return response
    session_id = str(result.get("session_id") or "")
    if not session_id:
        return response
    try:
        _secret()
        identity = _active_session(session_id)
        if not identity or identity["owner"] != (result.get("user") or {}).get("id"):
            return response
        route = await _resolve_login_route(session_id)
        if not route:
            return response
        now = int(time.time())
        expires = min(identity["expires"], now + 12 * 3600)
        receipt = {
            "aud": _AUDIENCE,
            "iat": now,
            "exp": expires,
            "version": NOTICE_VERSION,
            "purpose": NOTICE_PURPOSE,
            "session": _session_digest(session_id),
            "owner": identity["owner"],
            "tenant": identity["tenant"],
            "route": route,
            "scopes": notice_operation_scopes(),
        }
        raw_samesite = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax").strip().lower()
        samesite = cast(
            "Literal['lax', 'strict', 'none']",
            raw_samesite if raw_samesite in {"lax", "strict", "none"} else "lax",
        )
        response.set_cookie(
            NOTICE_COOKIE,
            jwt.encode(receipt, _secret(), algorithm="HS256"),
            max_age=expires - now,
            httponly=True,
            secure=os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
            samesite=samesite,
            path="/",
        )
    except (httpx.InvalidURL, *RECOVERABLE_ERRORS) as exc:
        logger.info("ELT login notice receipt unavailable error_type=%s", type(exc).__name__)
    return response


def login_notice_grant(
    request: Request, tenant_id: int, owner_id: int, operation: str = "template_candidates"
) -> dict | None:
    """The caller must already have authenticated and checked the current account."""
    from app.application.reviewed_excel_template import configured_template_llm_provider
    from app.infrastructure.auth.dependencies import session_id_from_request

    if not NOTICE_PUBLISHED or operation not in notice_operation_scopes():
        return None
    try:
        raw = request.cookies.get(NOTICE_COOKIE, "")
        if not raw or len(raw) > 4096 or configured_template_llm_provider() != "platform":
            return None
        receipt = jwt.decode(
            raw,
            _secret(),
            algorithms=["HS256"],
            audience=_AUDIENCE,
            options={
                "require": [
                    "exp",
                    "iat",
                    "version",
                    "purpose",
                    "session",
                    "owner",
                    "tenant",
                    "route",
                ]
            },
        )
        session_id = session_id_from_request(request)
        route = receipt.get("route")
        if (
            not session_id
            or receipt["session"] != _session_digest(session_id)
            or receipt["version"] != NOTICE_VERSION
            or receipt["purpose"] != NOTICE_PURPOSE
            or receipt["owner"] != owner_id
            or receipt["tenant"] != tenant_id
            or not isinstance(receipt.get("scopes"), dict)
            or receipt["scopes"].get(operation) != notice_operation_scopes()[operation]
            or not isinstance(route, dict)
            or route.get("base") != _platform_url()
            or not all(
                isinstance(route.get(key), str) and 0 < len(route[key]) <= 200
                for key in ("provider", "model")
            )
        ):
            return None
        return _LoginNoticeGrant(receipt, session_id)
    except (jwt.PyJWTError, *RECOVERABLE_ERRORS):
        return None


def login_notice_status(
    request: Request, tenant_id: int, owner_id: int, operation: str = "template_candidates"
) -> dict:
    grant = login_notice_grant(request, tenant_id, owner_id, operation)
    return {
        "status": "authorized"
        if grant
        else "login_notice_required"
        if NOTICE_PUBLISHED
        else "notice_not_published",
        "version": NOTICE_VERSION,
        "purpose": NOTICE_PURPOSE,
        "operation": operation,
        "scope": notice_operation_scopes().get(operation),
        **(
            {"provider": grant["route"]["provider"], "model": grant["route"]["model"]}
            if grant
            else {}
        ),
    }


@contextmanager
def bind_login_notice_grant(grant: dict):
    """Copy the verified route and exact session through the model worker thread."""
    if not isinstance(grant, _LoginNoticeGrant):
        from app.application.reviewed_excel_audit import ModelRequestNotSent

        raise ModelRequestNotSent("登录授权会话无法核实，未调用模型")
    token = _route_scope.set(dict(grant["route"]))
    session_token = _session_scope.set((grant._session_id, grant["owner"]))
    try:
        yield
    finally:
        _session_scope.reset(session_token)
        _route_scope.reset(token)


def current_login_notice_session_id(owner_id: int) -> str | None:
    """None means legacy authorization; an owner mismatch must fail closed."""
    scoped = _session_scope.get()
    return None if scoped is None else scoped[0] if scoped[1] == owner_id else ""


def assert_login_notice_route(base: str, provider: str, model: str) -> None:
    expected = _route_scope.get()
    if expected is not None and expected != {"base": base, "provider": provider, "model": model}:
        from app.application.reviewed_excel_audit import ModelRequestNotSent

        raise ModelRequestNotSent("平台模型目的地已变化；当前登录授权不适用，未调用模型")
