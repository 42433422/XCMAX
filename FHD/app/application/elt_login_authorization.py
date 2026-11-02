"""Current account model sessions and the bundled policy publication record."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, Request

NOTICE_VERSION = "2026-11-01"
RECIPIENT_DISCLOSURE_VERSION = "2026-11-01"
NOTICE_PUBLICATION_ENV = "FHD_ELT_NOTICE_PUBLICATION"
_NOTICE_PUBLICATION_FILE = (
    Path(__file__).resolve().parents[2] / "config/elt_notice_publication.json"
)
_session_scope: ContextVar[tuple[str, int] | None] = ContextVar("elt_model_session", default=None)


class _ModelSession(dict):
    """Keep the credential selector out of responses, logs and persisted metadata."""

    __slots__ = ("_session_id",)

    def __init__(self, session_id: str, tenant_id: int, owner_id: int):
        super().__init__(owner=owner_id, tenant=tenant_id)
        self._session_id = session_id


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


def notice_publication() -> dict | None:
    """Validate the actual publication record for packaging and policy checks."""
    try:
        if NOTICE_PUBLICATION_ENV in os.environ:
            raw_record = os.environ[NOTICE_PUBLICATION_ENV]
        else:
            if (
                _NOTICE_PUBLICATION_FILE.is_symlink()
                or _NOTICE_PUBLICATION_FILE.stat().st_size > 4096
            ):
                return None
            raw_record = _NOTICE_PUBLICATION_FILE.read_text(encoding="utf-8")
        record = json.loads(raw_record)
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
    except (OSError, ValueError, TypeError):
        return None


def require_model_session(request: Request, tenant_id: int, owner_id: int) -> _ModelSession:
    """Use the authenticated account session without a separate ELT consent credential."""
    from app.fastapi_routes.market_account import session_market_token
    from app.infrastructure.auth.dependencies import session_id_from_request

    session_id = session_id_from_request(request)
    identity = _active_session(session_id) if session_id else None
    if not identity:
        raise HTTPException(status_code=401, detail="请先登录有效账户")
    if identity["owner"] != owner_id or identity["tenant"] != tenant_id:
        raise HTTPException(status_code=403, detail="登录账户或租户已改变，请刷新页面")
    if not session_market_token(session_id):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "model_configuration_error",
                "message": "当前账户的平台模型连接不可用，未调用模型。",
                "retryable": True,
            },
        )
    return _ModelSession(session_id, tenant_id, owner_id)


def model_session_identity(request: Request, tenant_id: int, owner_id: int) -> dict:
    try:
        require_model_session(request, tenant_id, owner_id)
        status = "available"
    except HTTPException:
        status = "market_login_required"
    return {"actor": f"{tenant_id}:{owner_id}", "model_access": {"status": status}}


@contextmanager
def bind_model_session(session: _ModelSession):
    """Carry the exact authenticated session through the model worker thread."""
    if not isinstance(session, _ModelSession):
        from app.application.reviewed_excel_audit import ModelRequestNotSent

        raise ModelRequestNotSent("模型账户会话无法核实，未调用模型")
    token = _session_scope.set((session._session_id, session["owner"]))
    try:
        yield
    finally:
        _session_scope.reset(token)


def current_model_session_id(owner_id: int) -> str | None:
    scoped = _session_scope.get()
    return None if scoped is None else scoped[0] if scoped[1] == owner_id else ""


def template_model_authorization(
    session: _ModelSession,
    tenant_id: int,
    owner_id: int,
    derived_sha256: str,
    selected_region: dict,
    *,
    feedback: bool = False,
) -> dict:
    from app.application.elt.service_support import utcnow
    from app.application.reviewed_excel_template import configured_template_llm_provider

    return {
        "kind": "account_session",
        "provider": configured_template_llm_provider(),
        "tenant_id": tenant_id,
        "owner_user_id": owner_id,
        "source_sha256": selected_region.get("source_sha256", derived_sha256),
        "derived_sha256": derived_sha256,
        "scope": "this_document_bounded_cells_and_feedback"
        if feedback
        else "this_document_bounded_cells_and_structure",
        "requested_at": utcnow().isoformat(),
    }
