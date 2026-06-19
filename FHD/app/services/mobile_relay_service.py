"""Cloud relay binding and task queue for mobile-to-desktop dispatch."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.db.session import get_db


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _utc_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(60, int(seconds)))).replace(
        microsecond=0
    ).isoformat()


def _epoch_from_iso(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return int(time.time())


def _json_dumps(value: Any) -> str:
    return json.dumps(value if isinstance(value, (dict, list)) else {}, ensure_ascii=False)


def _json_loads(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_dict(row: Any) -> dict[str, Any]:
    data = dict(row or {})
    for key in ("capabilities_json", "payload_json", "result_json"):
        if key in data:
            data[key.removesuffix("_json")] = _json_loads(data.pop(key))
    return data


def _public_base_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        value = "https://xiu-ci.com/fhd-api"
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/") + "/"


class MobileRelayService:
    """Small SQL-backed relay used by phones and desktop runtimes."""

    def ensure_tables(self, db) -> None:
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

    def register_desktop(
        self,
        *,
        label: str,
        device_id: str,
        capabilities: dict[str, Any] | None = None,
        relay_base_url: str = "",
        ttl_seconds: int = 24 * 3600,
    ) -> dict[str, Any]:
        relay_id = uuid.uuid4().hex
        desktop_token = secrets.token_urlsafe(32)
        pairing_code = self._fresh_pairing_code()
        now = _utc_now()
        expires_at = _utc_after(ttl_seconds)
        normalized_base = _public_base_url(relay_base_url)
        with get_db() as db:
            self.ensure_tables(db)
            db.execute(
                text(
                    """
                    INSERT INTO mobile_relay_desktops (
                        relay_id, pairing_code, desktop_token_hash, desktop_label,
                        device_id, relay_base_url, status, capabilities_json,
                        expires_at, created_at, updated_at
                    ) VALUES (
                        :relay_id, :pairing_code, :desktop_token_hash, :desktop_label,
                        :device_id, :relay_base_url, 'pending', :capabilities_json,
                        :expires_at, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "relay_id": relay_id,
                    "pairing_code": pairing_code,
                    "desktop_token_hash": _token_hash(desktop_token),
                    "desktop_label": (label or "XCAGI 桌面执行端").strip()[:200],
                    "device_id": (device_id or "").strip()[:128],
                    "relay_base_url": normalized_base,
                    "capabilities_json": _json_dumps(capabilities or {}),
                    "expires_at": expires_at,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        return {
            "relay_id": relay_id,
            "desktop_token": desktop_token,
            "pairing_code": pairing_code,
            "expires_at": expires_at,
            "exp": _epoch_from_iso(expires_at),
            "relay_base_url": normalized_base,
            "qr_json": {
                "v": 3,
                "kind": "xcagi_relay_pairing",
                "relay_id": relay_id,
                "code": pairing_code,
                "t": pairing_code,
                "relay_base_url": normalized_base,
            },
        }

    def confirm_mobile(
        self,
        *,
        user_id: int,
        username: str,
        relay_id: str,
        code: str,
    ) -> dict[str, Any] | None:
        now = _utc_now()
        with get_db() as db:
            self.ensure_tables(db)
            row = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_relay_desktops
                        WHERE relay_id = :relay_id AND pairing_code = :code
                        """
                    ),
                    {"relay_id": relay_id.strip(), "code": code.strip()},
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            data = _row_dict(row)
            if data.get("status") == "revoked":
                return None
            if data.get("status") == "pending" and str(data.get("expires_at") or "") < now:
                return None
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET status = 'paired',
                        mobile_user_id = :user_id,
                        mobile_username = :username,
                        updated_at = :updated_at
                    WHERE relay_id = :relay_id
                    """
                ),
                {
                    "relay_id": relay_id.strip(),
                    "user_id": int(user_id),
                    "username": username.strip()[:200],
                    "updated_at": now,
                },
            )
            data.update(
                {
                    "status": "paired",
                    "mobile_user_id": int(user_id),
                    "mobile_username": username.strip()[:200],
                    "updated_at": now,
                }
            )
            return self._public_desktop(data)

    def confirm_mobile_by_code(
        self,
        *,
        user_id: int,
        username: str,
        code: str,
    ) -> dict[str, Any] | None:
        clean_code = code.strip()
        if not clean_code:
            return None
        now = _utc_now()
        with get_db() as db:
            self.ensure_tables(db)
            row = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_relay_desktops
                        WHERE pairing_code = :code
                          AND status IN ('pending', 'paired')
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"code": clean_code},
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            data = _row_dict(row)
            if data.get("status") == "pending" and str(data.get("expires_at") or "") < now:
                return None
            relay_id = str(data.get("relay_id") or "").strip()
            if not relay_id:
                return None
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET status = 'paired',
                        mobile_user_id = :user_id,
                        mobile_username = :username,
                        updated_at = :updated_at
                    WHERE relay_id = :relay_id
                    """
                ),
                {
                    "relay_id": relay_id,
                    "user_id": int(user_id),
                    "username": username.strip()[:200],
                    "updated_at": now,
                },
            )
            data.update(
                {
                    "status": "paired",
                    "mobile_user_id": int(user_id),
                    "mobile_username": username.strip()[:200],
                    "updated_at": now,
                }
            )
            return self._public_desktop(data)

    def list_desktops(self, *, user_id: int) -> list[dict[str, Any]]:
        with get_db() as db:
            self.ensure_tables(db)
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
            return [self._public_desktop(_row_dict(row)) for row in rows]

    def create_task(
        self,
        *,
        user_id: int,
        relay_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self._desktop_belongs_to_user(user_id=user_id, relay_id=relay_id):
            return None
        task_id = uuid.uuid4().hex
        now = _utc_now()
        safe_kind = (kind or "codex.invoke").strip()[:64] or "codex.invoke"
        with get_db() as db:
            self.ensure_tables(db)
            db.execute(
                text(
                    """
                    INSERT INTO mobile_relay_tasks (
                        task_id, relay_id, kind, payload_json, status,
                        result_json, created_by_user_id, created_at, updated_at
                    ) VALUES (
                        :task_id, :relay_id, :kind, :payload_json, 'queued',
                        '{}', :created_by_user_id, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "task_id": task_id,
                    "relay_id": relay_id.strip(),
                    "kind": safe_kind,
                    "payload_json": _json_dumps(payload or {}),
                    "created_by_user_id": int(user_id),
                    "created_at": now,
                    "updated_at": now,
                },
            )
        return self.get_task(user_id=user_id, task_id=task_id)

    def get_task(self, *, user_id: int, task_id: str) -> dict[str, Any] | None:
        with get_db() as db:
            self.ensure_tables(db)
            row = (
                db.execute(
                    text(
                        """
                        SELECT t.* FROM mobile_relay_tasks t
                        JOIN mobile_relay_desktops d ON d.relay_id = t.relay_id
                        WHERE t.task_id = :task_id
                          AND d.mobile_user_id = :user_id
                          AND d.status = 'paired'
                        """
                    ),
                    {"task_id": task_id.strip(), "user_id": int(user_id)},
                )
                .mappings()
                .first()
            )
            return _row_dict(row) if row else None

    def poll_desktop(
        self,
        *,
        relay_id: str,
        desktop_token: str,
        max_tasks: int = 5,
    ) -> dict[str, Any] | None:
        now = _utc_now()
        with get_db() as db:
            self.ensure_tables(db)
            desktop = self._desktop_for_token(db, relay_id=relay_id, desktop_token=desktop_token)
            if not desktop:
                return None
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET last_seen_at = :now, updated_at = :now
                    WHERE relay_id = :relay_id
                    """
                ),
                {"now": now, "relay_id": relay_id.strip()},
            )
            rows = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_relay_tasks
                        WHERE relay_id = :relay_id AND status = 'queued'
                        ORDER BY created_at ASC
                        LIMIT :limit
                        """
                    ),
                    {"relay_id": relay_id.strip(), "limit": max(1, min(20, int(max_tasks)))},
                )
                .mappings()
                .all()
            )
            tasks = [_row_dict(row) for row in rows]
            for task in tasks:
                db.execute(
                    text(
                        """
                        UPDATE mobile_relay_tasks
                        SET status = 'running', claimed_at = :now, updated_at = :now
                        WHERE task_id = :task_id AND status = 'queued'
                        """
                    ),
                    {"task_id": task["task_id"], "now": now},
                )
                task["status"] = "running"
                task["claimed_at"] = now
        return {
            "desktop": self._public_desktop(desktop),
            "tasks": tasks,
            "task_count": len(tasks),
        }

    def complete_desktop_task(
        self,
        *,
        relay_id: str,
        desktop_token: str,
        task_id: str,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = _utc_now()
        final_status = status if status in {"done", "failed"} else "done"
        with get_db() as db:
            self.ensure_tables(db)
            desktop = self._desktop_for_token(db, relay_id=relay_id, desktop_token=desktop_token)
            if not desktop:
                return None
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_tasks
                    SET status = :status,
                        result_json = :result_json,
                        completed_at = :now,
                        updated_at = :now
                    WHERE task_id = :task_id AND relay_id = :relay_id
                    """
                ),
                {
                    "status": final_status,
                    "result_json": _json_dumps(result or {}),
                    "now": now,
                    "task_id": task_id.strip(),
                    "relay_id": relay_id.strip(),
                },
            )
            row = (
                db.execute(
                    text("SELECT * FROM mobile_relay_tasks WHERE task_id = :task_id"),
                    {"task_id": task_id.strip()},
                )
                .mappings()
                .first()
            )
            return _row_dict(row) if row else None

    def _fresh_pairing_code(self) -> str:
        with get_db() as db:
            self.ensure_tables(db)
            for _ in range(100):
                code = str(secrets.randbelow(900000) + 100000)
                exists = (
                    db.execute(
                        text("SELECT 1 FROM mobile_relay_desktops WHERE pairing_code = :code"),
                        {"code": code},
                    )
                    .first()
                    is not None
                )
                if not exists:
                    return code
        return str(secrets.randbelow(900000) + 100000)

    def _desktop_belongs_to_user(self, *, user_id: int, relay_id: str) -> bool:
        with get_db() as db:
            self.ensure_tables(db)
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

    def _desktop_for_token(self, db, *, relay_id: str, desktop_token: str) -> dict[str, Any] | None:
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

    def _public_desktop(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "relay_id": data.get("relay_id"),
            "label": data.get("desktop_label") or "XCAGI 桌面执行端",
            "device_id": data.get("device_id") or "",
            "status": data.get("status") or "pending",
            "relay_base_url": data.get("relay_base_url") or "",
            "capabilities": data.get("capabilities") or {},
            "last_seen_at": data.get("last_seen_at") or "",
            "created_at": data.get("created_at") or "",
            "updated_at": data.get("updated_at") or "",
        }
