"""SQL schema, device authentication and public projections for the cloud relay."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.mobile_relay_ports import Database, Projection, Schema
from app.services.mobile_relay_utils import _row_dict, _token_hash


def ensure_tables(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS mobile_relay_desktops (
                relay_id VARCHAR(64) PRIMARY KEY,
                pairing_code VARCHAR(16) UNIQUE NOT NULL,
                desktop_token_hash VARCHAR(128) NOT NULL,
                desktop_label VARCHAR(200) NOT NULL DEFAULT '',
                device_id VARCHAR(128) NOT NULL DEFAULT '',
                relay_base_url VARCHAR(512) NOT NULL DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                mobile_user_id INTEGER,
                mobile_username VARCHAR(200) NOT NULL DEFAULT '',
                capabilities_json TEXT NOT NULL DEFAULT '{}',
                last_seen_at VARCHAR(64),
                expires_at VARCHAR(64) NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS mobile_relay_tasks (
                task_id VARCHAR(64) PRIMARY KEY,
                relay_id VARCHAR(64) NOT NULL,
                kind VARCHAR(64) NOT NULL DEFAULT 'codex.invoke',
                payload_json TEXT NOT NULL DEFAULT '{}',
                status VARCHAR(32) NOT NULL DEFAULT 'queued',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_by_user_id INTEGER,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                claimed_at VARCHAR(64),
                completed_at VARCHAR(64)
            )
            """
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_mobile_relay_desktops_user "
            "ON mobile_relay_desktops(mobile_user_id)"
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_mobile_relay_tasks_relay_status "
            "ON mobile_relay_tasks(relay_id, status, created_at)"
        )
    )


def list_desktops(
    *, user_id: int, database: Database, ensure_schema: Schema, project: Projection
) -> list[dict[str, Any]]:
    with database() as db:
        ensure_schema(db)
        rows = (
            db.execute(
                text(
                    """
                    SELECT * FROM mobile_relay_desktops
                    WHERE mobile_user_id = :user_id AND status = 'paired'
                    ORDER BY updated_at DESC
                    """
                ),
                {"user_id": int(user_id)},
            )
            .mappings()
            .all()
        )
        return [project(_row_dict(row)) for row in rows]


def fresh_pairing_code(db: Session) -> str:
    for _ in range(100):
        code = str(secrets.randbelow(900000) + 100000)
        if not db.execute(
            text("SELECT 1 FROM mobile_relay_desktops WHERE pairing_code = :code"),
            {"code": code},
        ).first():
            return code
    raise RuntimeError("No unused relay pairing code is available")


def desktop_belongs_to_user(
    *, user_id: int, relay_id: str, database: Database, ensure_schema: Schema
) -> bool:
    with database() as db:
        ensure_schema(db)
        return (
            db.execute(
                text(
                    """
                    SELECT 1 FROM mobile_relay_desktops
                    WHERE relay_id = :relay_id
                      AND mobile_user_id = :user_id
                      AND status = 'paired'
                    """
                ),
                {"relay_id": relay_id.strip(), "user_id": int(user_id)},
            ).first()
            is not None
        )


def desktop_for_token(db: Session, *, relay_id: str, desktop_token: str) -> dict[str, Any] | None:
    token = (desktop_token or "").strip()
    if not token:
        return None
    row = (
        db.execute(
            text(
                """
                SELECT * FROM mobile_relay_desktops
                WHERE relay_id = :relay_id
                  AND desktop_token_hash = :token_hash
                  AND status IN ('pending', 'paired')
                """
            ),
            {"relay_id": relay_id.strip(), "token_hash": _token_hash(token)},
        )
        .mappings()
        .first()
    )
    return _row_dict(row) if row else None


def public_desktop(data: dict[str, Any]) -> dict[str, Any]:
    capabilities = data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {}
    if not isinstance(capabilities, dict):
        capabilities = {}
    host = str(capabilities.get("host") or "").strip()
    port = int(capabilities.get("port") or 0)
    local_base_url = ""
    if host and host not in {"0.0.0.0", "::"}:
        local_base_url = f"http://{host}{f':{port}' if port > 0 else ''}"
    status = data.get("status") or "pending"
    return {
        "relay_id": data.get("relay_id"),
        "label": data.get("desktop_label") or "XCAGI 桌面执行端",
        "device_id": data.get("device_id") or "",
        "status": status,
        "relay_base_url": data.get("relay_base_url") or "",
        "local_base_url": local_base_url,
        "paired_at": data.get("updated_at") if status == "paired" else "",
        "capabilities": capabilities,
        "last_seen_at": data.get("last_seen_at") or "",
        "created_at": data.get("created_at") or "",
        "updated_at": data.get("updated_at") or "",
        # 已绑定手机的账号名；供桌面端设置页展示「已连接：xxx 的手机」，与手机端「服务」文案对齐。
        "mobile_username": data.get("mobile_username") or "",
    }
