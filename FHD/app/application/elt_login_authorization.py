"""Session-bound login notice receipts for the existing bounded ELT model pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Literal, cast

import httpx
import jwt
from fastapi import HTTPException, Request, Response

from app.utils.operational_errors import RECOVERABLE_ERRORS

NOTICE_VERSION = "2026-11-01"
RECIPIENT_DISCLOSURE_VERSION = "2026-11-01"
NOTICE_PUBLICATION_ENV = "FHD_ELT_NOTICE_PUBLICATION"
_COVERED_RELAY = "https://xiu-ci.com"
_DISCLOSED_RECIPIENT = {
    "id": "xiaomi-mimo-cn",
    "api_base": "https://token-plan-cn.xiaomimimo.com/v1",
    "region": "CN",
    "disclosure_version": RECIPIENT_DISCLOSURE_VERSION,
}
_DATA_CATEGORIES = (
    "instructions",
    "file_text",
    "formulas",
    "table_structure",
    "cell_coordinates",
    "task_business_fields",
    "related_context",
    "necessary_request_parameters",
)
NOTICE_COOKIE = "xcagi_elt_notice"
NOTICE_PURPOSE = "elt_file_processing"
_AUDIENCE = "xcagi-elt-login-notice"
_route_scope: ContextVar[dict | None] = ContextVar("elt_login_model_route", default=None)
_session_scope: ContextVar[tuple[str, int] | None] = ContextVar("elt_login_session", default=None)
logger = logging.getLogger(__name__)
_LOGIN_NOTICE_ERRORS: tuple[type[Exception], ...] = (httpx.InvalidURL, *RECOVERABLE_ERRORS)
_NOTICE_VERIFY_ERRORS: tuple[type[Exception], ...] = (jwt.PyJWTError, *RECOVERABLE_ERRORS)
_PUBLIC_ROUTE_FIELDS = ("provider", "model", "key_source", "config_revision")


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
    if os.environ.get("XCAGI_MARKET_BASE_URL"):
        from app.fastapi_routes.market_bridge.settings import _market_api_base_url

        return _market_api_base_url()
    return (
        (
            os.environ.get("XCAGI_MARKET_BASE_URL")
            or os.environ.get("MODSTORE_PLATFORM_URL")
            or "http://127.0.0.1:8765"
        )
        .strip()
        .rstrip("/")
    )


def _public_model_route(route: dict) -> dict:
    return {
        **{key: route[key] for key in _PUBLIC_ROUTE_FIELDS},
        "recipient": dict(route["recipient"]),
    }


def notice_publication() -> dict | None:
    """Only a publisher-supplied, version-matching actual release can enable new grants."""
    try:
        record = json.loads(os.environ.get(NOTICE_PUBLICATION_ENV, ""))
        if not isinstance(record, dict) or set(record) != {
            "notice_version",
            "recipient_disclosure_version",
            "published_at",
        }:
            return None
        if (
            record["notice_version"] != NOTICE_VERSION
            or record["recipient_disclosure_version"] != RECIPIENT_DISCLOSURE_VERSION
            or not isinstance(record["published_at"], str)
        ):
            return None
        published = datetime.fromisoformat(record["published_at"].replace("Z", "+00:00"))
        if published.tzinfo is None or published > datetime.now(UTC):
            return None
        canonical = {**record, "published_at": published.astimezone(UTC).isoformat()}
        return {
            **canonical,
            "record_sha256": hashlib.sha256(
                json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    except (ValueError, TypeError):
        return None


def _covered_recipient(route: dict) -> bool:
    return (
        route.get("base") == _COVERED_RELAY
        and route.get("key_source") == "platform"
        and route.get("provider") == "xiaomi"
        and route.get("model") == "mimo-v2.6-flash"
        and isinstance(route.get("recipient"), dict)
        and route["recipient"] == {**_DISCLOSED_RECIPIENT, "provider": route.get("provider")}
    )


def _valid_model_snapshot(route: dict) -> bool:
    return all(
        isinstance(route.get(key), str) and 0 < len(route[key].strip()) <= limit
        for key, limit in (
            ("provider", 200),
            ("model", 200),
            ("key_source", 200),
            ("config_revision", 128),
        )
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
    if base != _COVERED_RELAY:
        return None
    async with httpx.AsyncClient(
        timeout=3.0, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        response = await client.get(f"{base}/api/llm/resolve-chat-default")
        response.raise_for_status()
        route = response.json()
    if not isinstance(route, dict) or not route.get("ok"):
        return None
    provider, model = route.get("provider"), route.get("model")
    if not isinstance(provider, str) or not isinstance(model, str):
        return None
    provider, model = provider.strip(), model.strip()
    if not 0 < len(provider) <= 200 or not 0 < len(model) <= 200:
        return None
    if not _valid_model_snapshot(route) or not _covered_recipient({**route, "base": base}):
        return None
    return {"base": base, **_public_model_route(route), "provider": provider, "model": model}


async def attach_login_notice(response: Response, result: dict, body: dict) -> Response:
    """Only an explicit successful credential login can establish this receipt."""
    if not result.get("success"):
        return response
    response.delete_cookie(NOTICE_COOKIE, path="/")
    publication = notice_publication()
    if not publication or body.get("data_processing_notice_version") != NOTICE_VERSION:
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
        if (
            not route
            or route.get("base") != _platform_url()
            or not _valid_model_snapshot(route)
            or not _covered_recipient(route)
        ):
            return response
        now = int(time.time())
        expires = min(identity["expires"], now + 12 * 3600)
        receipt = {
            "aud": _AUDIENCE,
            "iat": now,
            "exp": expires,
            "version": NOTICE_VERSION,
            "purpose": NOTICE_PURPOSE,
            "publication": publication,
            "recipient_disclosure_version": RECIPIENT_DISCLOSURE_VERSION,
            "data_categories": list(_DATA_CATEGORIES),
            "session": _session_digest(session_id),
            "owner": identity["owner"],
            "tenant": identity["tenant"],
            "route": {"base": route["base"], **_public_model_route(route)},
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
    except _LOGIN_NOTICE_ERRORS as exc:
        logger.info("ELT login notice receipt unavailable error_type=%s", type(exc).__name__)
    return response


def login_notice_grant(
    request: Request, tenant_id: int, owner_id: int, operation: str = "template_candidates"
) -> dict | None:
    """The caller must already have authenticated and checked the current account."""
    from app.application.reviewed_excel_template import configured_template_llm_provider
    from app.infrastructure.auth.dependencies import session_id_from_request

    publication = notice_publication()
    if not publication or operation not in notice_operation_scopes():
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
            or receipt.get("publication") != publication
            or receipt.get("recipient_disclosure_version") != RECIPIENT_DISCLOSURE_VERSION
            or receipt.get("data_categories") != list(_DATA_CATEGORIES)
            or receipt["owner"] != owner_id
            or receipt["tenant"] != tenant_id
            or not isinstance(receipt.get("scopes"), dict)
            or receipt["scopes"].get(operation) != notice_operation_scopes()[operation]
            or not isinstance(route, dict)
            or route.get("base") != _platform_url()
            or set(route) != {"base", "recipient", *_PUBLIC_ROUTE_FIELDS}
            or not _valid_model_snapshot(route)
            or not _covered_recipient(route)
        ):
            return None
        return _LoginNoticeGrant(receipt, session_id)
    except _NOTICE_VERIFY_ERRORS:
        return None


def login_notice_status(
    request: Request, tenant_id: int, owner_id: int, operation: str = "template_candidates"
) -> dict:
    grant = login_notice_grant(request, tenant_id, owner_id, operation)
    return {
        "status": "authorized"
        if grant
        else "login_notice_required"
        if notice_publication()
        else "notice_not_published",
        "version": NOTICE_VERSION,
        "purpose": NOTICE_PURPOSE,
        "recipient_disclosure_version": RECIPIENT_DISCLOSURE_VERSION,
        "operation": operation,
        "scope": notice_operation_scopes().get(operation),
        **(_public_model_route(grant["route"]) if grant else {}),
    }


def login_notice_identity(request: Request, tenant_id: int, owner_id: int) -> dict:
    authorization = login_notice_status(request, tenant_id, owner_id, "classification")
    authorization["operations"] = {
        operation: login_notice_status(request, tenant_id, owner_id, operation)["status"]
        for operation in notice_operation_scopes()
    }
    authorization["scopes"] = notice_operation_scopes()
    return {"actor": f"{tenant_id}:{owner_id}", "login_authorization": authorization}


def classification_login_status(
    request: Request, tenant_id: int, owner_id: int, enabled: bool
) -> dict:
    return (
        {"login_authorization": login_notice_status(request, tenant_id, owner_id, "classification")}
        if enabled
        else {}
    )


def require_login_notice_grant(
    request: Request, tenant_id: int, owner_id: int, operation: str = "template_candidates"
) -> dict:
    grant = login_notice_grant(request, tenant_id, owner_id, operation)
    if not grant:
        message = (
            "缺少有效的本次文件分类授权，请核对登录状态。"
            if operation == "classification"
            else "缺少有效的本次模型处理授权，请核对登录状态。"
        )
        raise HTTPException(status_code=403, detail=message)
    return grant


def notice_document_scope(grant: dict | None, selected_region: dict) -> dict:
    if not grant:
        return {}
    return {
        "notice_version": grant["version"],
        "notice_accepted_at": grant["iat"],
        "notice_publication": dict(grant["publication"]),
        "recipient_disclosure_version": grant["recipient_disclosure_version"],
        "data_categories": list(grant["data_categories"]),
        "model_route": _public_model_route(grant["route"]),
        "classification_id": selected_region.get("classification_id"),
        "classification_version": selected_region.get("version"),
        "document": {
            key: selected_region[key]
            for key in ("sheet", "range", "fragments", "auto_slice_index")
            if key in selected_region
        },
    }


def template_model_authorization(
    grant: dict | None,
    tenant_id: int,
    owner_id: int,
    own_file: bool,
    derived_sha256: str,
    selected_region: dict,
    *,
    feedback: bool = False,
) -> dict:
    from app.application.elt.service_support import utcnow
    from app.application.reviewed_excel_template import configured_template_llm_provider

    return {
        "kind": "owner_file" if own_file else "authorized_sample",
        "provider": configured_template_llm_provider(),
        "tenant_id": tenant_id,
        "owner_user_id": owner_id,
        "source_sha256": selected_region.get("source_sha256", derived_sha256),
        "derived_sha256": derived_sha256,
        "scope": "this_document_bounded_cells_and_feedback"
        if feedback
        else "this_document_bounded_cells_and_structure",
        "authorized_at": utcnow().isoformat(),
        **notice_document_scope(grant, selected_region),
    }


def classification_notice_scope(grant: dict | None, classification_id: str, version: str) -> dict:
    if not grant:
        return {}
    return {
        **notice_document_scope(
            grant, {"classification_id": classification_id, "version": version}
        ),
        "notice_operation": "classification",
        "notice_scope": grant["scopes"]["classification"],
    }


def validate_classification_notice(checkpoint: dict | None, grant: dict) -> None:
    if checkpoint and (
        checkpoint.get("authorization", {}).get("notice_version") != grant["version"]
        or checkpoint.get("authorization", {}).get("notice_publication") != grant["publication"]
        or checkpoint.get("authorization", {}).get("recipient_disclosure_version")
        != grant["recipient_disclosure_version"]
        or checkpoint.get("authorization", {}).get("data_categories") != grant["data_categories"]
        or checkpoint.get("authorization", {}).get("model_route")
        != _public_model_route(grant["route"])
        or checkpoint.get("authorization", {}).get("notice_scope")
        != grant["scopes"]["classification"]
    ):
        raise HTTPException(status_code=409, detail="登录授权范围已改变，请核对已有批次")


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


def assert_login_notice_route(
    base: str,
    provider: str,
    model: str,
    *,
    key_source: str | None = None,
    config_revision: str | None = None,
    recipient: dict | None = None,
) -> None:
    expected = _route_scope.get()
    actual = {
        "base": base,
        "provider": provider,
        "model": model,
        "key_source": key_source,
        "config_revision": config_revision,
        "recipient": recipient,
    }
    if expected is not None and (
        not _valid_model_snapshot(actual) or not _covered_recipient(actual) or expected != actual
    ):
        from app.application.reviewed_excel_audit import ModelRequestNotSent

        raise ModelRequestNotSent("平台模型目的地已变化；当前登录授权不适用，未调用模型")
