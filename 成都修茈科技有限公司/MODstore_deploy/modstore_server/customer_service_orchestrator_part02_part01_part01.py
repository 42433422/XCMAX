# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def _enrich_cs_context(
    user: _facade().User,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    *,
    db: _facade().Optional[_facade().Session] = None,
) -> _facade().Dict[str, _facade().Any]:
    """会话 context 写入可信用户身份（不信任前端伪造的 user_id）。"""
    ctx = dict(context or {})
    try:
        from modstore_server.xiaoc_cs_ssot import resolve_user_identity

        ident = resolve_user_identity(user, db=db, source="market_cs")
        ctx["user_id"] = ident.user_id
        ctx["display_name"] = ident.display_name
        ctx["membership"] = ident.membership
        ctx["account_role"] = ident.account_role
        if ident.plan_id:
            ctx["plan_id"] = ident.plan_id
        if ident.email_hint:
            ctx["email_hint"] = ident.email_hint
    except RECOVERABLE_ERRORS:
        ctx["user_id"] = getattr(user, "id", None)
        name = str(getattr(user, "username", None) or "").strip()
        if name:
            ctx["display_name"] = name[:32]
    return ctx


def ensure_session(
    db: _facade().Session,
    *,
    user: _facade().User,
    session_id: _facade().Optional[int] = None,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().CustomerServiceSession:
    enriched = _facade()._enrich_cs_context(user, context, db=db)
    if session_id:
        row = (
            db.query(_facade().CustomerServiceSession)
            .filter(
                _facade().CustomerServiceSession.id == session_id,
                _facade().CustomerServiceSession.user_id == user.id,
            )
            .first()
        )
        if row:
            try:
                prev = _facade().json_loads(row.context_json) if row.context_json else {}
                if not isinstance(prev, dict):
                    prev = {}
                merged = {
                    **prev,
                    **{k: v for (k, v) in enriched.items() if v is not None},
                }
                row.context_json = _facade().json_dumps(merged)
            except RECOVERABLE_ERRORS:
                pass
            return row
    row = _facade().CustomerServiceSession(
        user_id=user.id,
        channel=str(enriched.get("channel") or "web")[:32],
        status="open",
        title="AI 客服会话",
        context_json=_facade().json_dumps(enriched),
    )
    db.add(row)
    db.flush()
    _facade().audit(
        db,
        event_type="session_created",
        session_id=row.id,
        actor=user,
        detail={"channel": row.channel, "context": context or {}},
    )
    return row
