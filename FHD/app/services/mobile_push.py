"""移动端推送：FCM（可选）+ 自建推送（在线 WS 下发 + 离线队列）。极光 JPush 已移除。"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

MOBILE_NOTIFICATION_AUDIENCES = frozenset({"enterprise", "management"})
_notification_schema_lock = threading.RLock()
MOBILE_PUSH_ERRORS = RECOVERABLE_ERRORS + (SQLAlchemyError,)


def normalize_notification_audience(value: str | None) -> str:
    """Return a fail-closed, server-owned mobile notification audience."""

    normalized = str(value or "").strip().lower()
    if normalized not in MOBILE_NOTIFICATION_AUDIENCES:
        raise ValueError("invalid mobile notification audience")
    return normalized


def normalize_notification_tenant_id(value: Any) -> int:
    """Canonicalize global/tenantless users to tenant 0."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return 0
    tenant_id = int(value)
    if tenant_id < 0:
        raise ValueError("invalid mobile notification tenant")
    return tenant_id


def notification_scope_for_user(user: Any) -> tuple[str, int]:
    """Derive notification isolation from the authenticated principal.

    Pairing projects an administrator into an enterprise-only principal before
    this helper runs.  A client supplied SKU is deliberately not consulted.
    """

    token_scope = str(getattr(user, "token_scope", "") or "").strip()
    role = str(getattr(user, "role", "") or "").strip().lower()
    tier = str(getattr(user, "tier", "") or "").strip().lower()
    audience = (
        "management"
        if token_scope == "management_pairing"
        or role in {"admin", "admin_portal", "super_admin", "owner"}
        or tier == "admin"
        else "enterprise"
    )
    return audience, normalize_notification_tenant_id(getattr(user, "tenant_id", None))


def ensure_mobile_notification_schema(db: Any) -> None:
    """Upgrade SQLite desktop databases that intentionally skip Alembic.

    Production databases use the matching Alembic revision.  Desktop/LAN
    deployments use ``create_all`` and may retain an older SQLite file, so the
    two authorization columns must also be added idempotently at runtime.
    """

    try:
        bind = db.get_bind()
    except (AttributeError, TypeError):
        return
    # PostgreSQL and other production databases must be upgraded by Alembic.
    # Runtime DDL exists only for retained desktop SQLite files.
    if str(getattr(getattr(bind, "dialect", None), "name", "")) != "sqlite":
        return
    with _notification_schema_lock:
        from app.db.models.mobile_device import MobileDeviceToken
        from app.db.models.mobile_notification import MobileNotificationOutbox

        # BEGIN IMMEDIATE serializes schema upgrades across desktop processes.
        # Inspect and mutate through the same connection so a caller rollback
        # cannot leave a cached half-upgraded schema behind.
        with bind.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                inspector = sa_inspect(connection)
                user_columns = (
                    {str(column["name"]) for column in inspector.get_columns("users")}
                    if inspector.has_table("users")
                    else set()
                )
                models = (MobileDeviceToken, MobileNotificationOutbox)
                for model in models:
                    table = model.__tablename__
                    if not inspector.has_table(table):
                        model.__table__.create(connection, checkfirst=True)
                        continue
                    column_rows = list(inspector.get_columns(table))
                    columns = {str(column["name"]) for column in column_rows}
                    indexes = {
                        str(index["name"])
                        for index in inspector.get_indexes(table)
                        if index.get("name")
                    }
                    if "notification_audience" not in columns:
                        connection.execute(
                            text(
                                f"ALTER TABLE {table} ADD COLUMN notification_audience "
                                "VARCHAR(32) NOT NULL DEFAULT 'enterprise'"
                            )
                        )
                    tenant_was_missing = "tenant_id" not in columns
                    if tenant_was_missing:
                        connection.execute(
                            text(
                                f"ALTER TABLE {table} ADD COLUMN tenant_id "
                                "INTEGER NOT NULL DEFAULT 0"
                            )
                        )
                    if (
                        table == MobileNotificationOutbox.__tablename__
                        and "event_id" not in columns
                    ):
                        connection.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN event_id VARCHAR(256)")
                        )
                    tenant_is_nullable = any(
                        column["name"] == "tenant_id"
                        and bool(column.get("nullable", True))
                        for column in column_rows
                    )
                    if tenant_was_missing or tenant_is_nullable:
                        if "tenant_id" in user_columns:
                            predicate = "1 = 1" if tenant_was_missing else "tenant_id IS NULL"
                            connection.execute(
                                text(
                                    f"UPDATE {table} SET tenant_id = COALESCE("
                                    f"(SELECT users.tenant_id FROM users "
                                    f"WHERE users.id = {table}.user_id), 0) "
                                    f"WHERE {predicate}"
                                )
                            )
                        else:
                            connection.execute(
                                text(
                                    f"UPDATE {table} SET tenant_id = 0 "
                                    "WHERE tenant_id IS NULL"
                                )
                            )
                    audience_index = f"ix_{table}_notification_audience"
                    if audience_index not in indexes:
                        connection.execute(
                            text(
                                f"CREATE INDEX IF NOT EXISTS {audience_index} "
                                f"ON {table} (notification_audience)"
                            )
                        )
                    tenant_index = f"ix_{table}_tenant_id"
                    if tenant_index not in indexes:
                        connection.execute(
                            text(
                                f"CREATE INDEX IF NOT EXISTS {tenant_index} "
                                f"ON {table} (tenant_id)"
                            )
                        )
                outbox_indexes = {
                    str(index["name"])
                    for index in inspector.get_indexes(
                        MobileNotificationOutbox.__tablename__
                    )
                    if index.get("name")
                }
                outbox_uniques = {
                    str(constraint["name"])
                    for constraint in inspector.get_unique_constraints(
                        MobileNotificationOutbox.__tablename__
                    )
                    if constraint.get("name")
                }
                if "uq_mobile_outbox_scope_event" not in outbox_indexes | outbox_uniques:
                    connection.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS "
                            "uq_mobile_outbox_scope_event ON mobile_notification_outbox "
                            "(user_id, notification_audience, tenant_id, event_id)"
                        )
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def _fcm_enabled() -> bool:
    return bool(
        os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    )


def send_fcm(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    if not tokens or not _fcm_enabled():
        return False
    try:
        import google.oauth2.service_account
        from google.auth.transport.requests import Request
    except ImportError:
        logger.warning("google-auth not installed; skip FCM")
        return False

    cred_path = (
        os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        or ""
    ).strip()
    if not cred_path or not os.path.isfile(cred_path):
        logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON not a file: %s", cred_path)
        return False

    try:
        creds = google.oauth2.service_account.Credentials.from_service_account_file(
            cred_path,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        creds.refresh(Request())
        access_token = creds.token
        project_id = json.load(open(cred_path, encoding="utf-8")).get("project_id")
        if not project_id:
            return False
        url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        ok_any = False
        str_data = {k: str(v) for k, v in (data or {}).items()}
        for token in tokens[:500]:
            msg = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": str_data,
                }
            }
            r = httpx.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=msg,
                timeout=15.0,
            )
            if r.status_code < 400:
                ok_any = True
            else:
                logger.warning("fcm token fail: %s", r.text[:300])
        return ok_any
    except RECOVERABLE_ERRORS as exc:
        logger.warning("fcm error: %s", exc)
        return False


def send_to_user_devices(
    devices: List[Dict[str, Any]],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, bool]:
    """devices: rows with push_provider, push_token (or legacy fcm_token)."""
    fcm_tokens: List[str] = []
    for d in devices:
        tok = (d.get("push_token") or d.get("fcm_token") or "").strip()
        if not tok:
            continue
        # 极光已移除；非 FCM 设备走自建推送（见 notify_user 的离线队列入账），不在此处发。
        provider = (d.get("push_provider") or "fcm").strip().lower()
        if provider in ("fcm", ""):
            fcm_tokens.append(tok)
    return {
        "fcm": send_fcm(fcm_tokens, title, body, data),
    }


def _normalized_event_id(payload: dict[str, Any]) -> str | None:
    event_id = str(payload.get("event_id") or "").strip()
    if not event_id:
        return None
    if len(event_id) <= 256:
        return event_id
    import hashlib

    return f"sha256:{hashlib.sha256(event_id.encode('utf-8')).hexdigest()}"


def _enqueue_outbox(
    user_id: int,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    audience: str = "enterprise",
    tenant_id: int | None = None,
) -> tuple[bool, bool]:
    """Write the scoped outbox row and return ``(durable, created)``."""
    from app.db.models.mobile_notification import MobileNotificationOutbox
    from app.db.session import get_db

    payload = data or {}
    encoded_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    event_id = _normalized_event_id(payload)
    try:
        normalized_audience = normalize_notification_audience(audience)
        normalized_tenant = normalize_notification_tenant_id(tenant_id)
        with get_db() as db:
            ensure_mobile_notification_schema(db)
            if event_id:
                existing = (
                    db.query(MobileNotificationOutbox.id)
                    .filter(
                        MobileNotificationOutbox.user_id == int(user_id),
                        MobileNotificationOutbox.notification_audience == normalized_audience,
                        MobileNotificationOutbox.tenant_id == normalized_tenant,
                        MobileNotificationOutbox.event_id == event_id,
                    )
                    .first()
                )
                if existing is not None:
                    return True, False
            db.add(
                MobileNotificationOutbox(
                    user_id=int(user_id),
                    notification_audience=normalized_audience,
                    tenant_id=normalized_tenant,
                    event_id=event_id,
                    title=(title or "")[:200],
                    body=(body or "")[:4000],
                    route=str(payload.get("route") or "")[:300],
                    channel=str(payload.get("channel") or "")[:64],
                    data_json=encoded_payload,
                )
            )
        return True, True
    except IntegrityError as exc:
        if event_id:
            try:
                with get_db() as db:
                    existing = (
                        db.query(MobileNotificationOutbox.id)
                        .filter(
                            MobileNotificationOutbox.user_id == int(user_id),
                            MobileNotificationOutbox.notification_audience
                            == normalized_audience,
                            MobileNotificationOutbox.tenant_id == normalized_tenant,
                            MobileNotificationOutbox.event_id == event_id,
                        )
                        .first()
                    )
                if existing is not None:
                    logger.info("mobile outbox event already exists: %s", event_id)
                    return True, False
            except MOBILE_PUSH_ERRORS:
                pass
        logger.warning("enqueue_outbox integrity error: %s", exc)
        return False, False
    except MOBILE_PUSH_ERRORS as exc:
        logger.warning("enqueue_outbox error: %s", exc)
        return False, False


def enqueue_outbox(
    user_id: int,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    audience: str = "enterprise",
    tenant_id: int | None = None,
) -> bool:
    """Persist one scoped notification, deduplicated by its event id."""

    durable, _created = _enqueue_outbox(
        user_id,
        title,
        body,
        data,
        audience=audience,
        tenant_id=tenant_id,
    )
    return durable


def _authoritative_notification_tenant(db: Any, user_id: int) -> int:
    from app.db.models import User

    row = db.query(User).filter(User.id == int(user_id)).first()
    if row is None or not bool(getattr(row, "is_active", False)):
        raise ValueError("notification recipient is missing or inactive")
    return normalize_notification_tenant_id(getattr(row, "tenant_id", None))


def notify_user(
    user_id: int,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    audience: str = "enterprise",
    tenant_id: int | None = None,
) -> Dict[str, bool]:
    from app.db.models.mobile_device import MobileDeviceToken
    from app.db.session import get_db

    try:
        normalized_audience = normalize_notification_audience(audience)
        with get_db() as db:
            ensure_mobile_notification_schema(db)
            authoritative_tenant = _authoritative_notification_tenant(db, user_id)
        if tenant_id is not None:
            requested_tenant = normalize_notification_tenant_id(tenant_id)
            if requested_tenant != authoritative_tenant:
                raise ValueError("notification tenant does not match recipient")
        scoped_data = {
            **(data or {}),
            "notification_audience": normalized_audience,
            "tenant_id": str(authoritative_tenant),
        }
        durable, created = _enqueue_outbox(
            user_id,
            title,
            body,
            scoped_data,
            audience=normalized_audience,
            tenant_id=authoritative_tenant,
        )
        if not durable:
            return {"fcm": False, "outbox": False}
        if not created:
            return {"fcm": False, "outbox": True, "deduplicated": True}

        with get_db() as db:
            ensure_mobile_notification_schema(db)
            rows = (
                db.query(MobileDeviceToken)
                .filter(
                    MobileDeviceToken.user_id == int(user_id),
                    MobileDeviceToken.notification_audience == normalized_audience,
                    MobileDeviceToken.tenant_id == authoritative_tenant,
                )
                .all()
            )
            devices = [
                {
                    "push_provider": getattr(row, "push_provider", None) or "fcm",
                    "push_token": getattr(row, "push_token", None) or row.fcm_token,
                    "fcm_token": row.fcm_token,
                }
                for row in rows
            ]
        result = send_to_user_devices(devices, title, body, scoped_data)
        result["outbox"] = True
        return result
    except MOBILE_PUSH_ERRORS as exc:
        logger.warning("notify_user scope/delivery error: %s", exc)
        return {"fcm": False, "outbox": False}
