"""Cloud relay binding and task queue for mobile-to-desktop dispatch."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

from app.db.session import get_db
from app.infrastructure.topology import FHD_API_BASE_URL

logger = logging.getLogger(__name__)

_SUPER_EMPLOYEE_TOOLS: dict[str, str] = {
    "codex-super-employee": "codex",
    "claude-super-employee": "claude",
    "cursor-super-employee": "cursor",
    "trae-super-employee": "trae",
}
_TOOL_EMPLOYEES = {tool: employee for employee, tool in _SUPER_EMPLOYEE_TOOLS.items()}
_ACTIVE_TASK_STATUSES = {"queued", "running", "assigned", "processing", "in_progress"}
_TASK_LIST_DEFAULT_LIMIT = 50
_TASK_LIST_MAX_PAGE_LIMIT = 200
_TASK_LIST_MAX_REQUESTED_LIMIT = 300
_TASK_LIST_MAX_RESPONSE_BYTES = 1024 * 1024
_TASK_SUMMARY_MESSAGE_MAX_CHARS = 320
_TASK_SUMMARY_RESULT_MAX_CHARS = 1200
_TASK_SUMMARY_BRANCH_MAX_CHARS = 256
_TASK_SUMMARY_CODE_MAX_CHARS = 128
_RELAY_TASK_COLUMN_DDL = {
    (
        "mobile_relay_tasks",
        "thread_id",
        "VARCHAR(64) NOT NULL DEFAULT ''",
    ): "ALTER TABLE mobile_relay_tasks ADD COLUMN thread_id VARCHAR(64) NOT NULL DEFAULT ''",
    (
        "mobile_relay_tasks",
        "work_item_id",
        "VARCHAR(64) NOT NULL DEFAULT ''",
    ): "ALTER TABLE mobile_relay_tasks ADD COLUMN work_item_id VARCHAR(64) NOT NULL DEFAULT ''",
    (
        "mobile_relay_tasks",
        "employee_id",
        "VARCHAR(80) NOT NULL DEFAULT ''",
    ): "ALTER TABLE mobile_relay_tasks ADD COLUMN employee_id VARCHAR(80) NOT NULL DEFAULT ''",
    (
        "mobile_relay_tasks",
        "attempt_no",
        "INTEGER NOT NULL DEFAULT 1",
    ): "ALTER TABLE mobile_relay_tasks ADD COLUMN attempt_no INTEGER NOT NULL DEFAULT 1",
}


def _thread_list_statement(*, filter_employee: bool, only_unarchived: bool):
    if filter_employee and only_unarchived:
        return text(
            """
            SELECT * FROM mobile_super_employee_threads
            WHERE user_id = :user_id
              AND employee_id = :employee_id
              AND archived_at IS NULL
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        )
    if filter_employee:
        return text(
            """
            SELECT * FROM mobile_super_employee_threads
            WHERE user_id = :user_id AND employee_id = :employee_id
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        )
    if only_unarchived:
        return text(
            """
            SELECT * FROM mobile_super_employee_threads
            WHERE user_id = :user_id AND archived_at IS NULL
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        )
    return text(
        """
        SELECT * FROM mobile_super_employee_threads
        WHERE user_id = :user_id
        ORDER BY updated_at DESC
        LIMIT :limit
        """
    )


def _task_list_statement(*, filter_thread: bool, active_only: bool):
    if filter_thread and active_only:
        return text(
            """
            SELECT t.* FROM mobile_relay_tasks t
            JOIN mobile_relay_desktops d ON d.relay_id = t.relay_id
            WHERE d.mobile_user_id = :user_id
              AND d.status = 'paired'
              AND t.thread_id = :thread_id
              AND t.status IN ('queued', 'running', 'assigned', 'processing', 'in_progress')
            ORDER BY t.created_at DESC
            LIMIT :limit
            OFFSET :offset
            """
        )
    if filter_thread:
        return text(
            """
            SELECT t.* FROM mobile_relay_tasks t
            JOIN mobile_relay_desktops d ON d.relay_id = t.relay_id
            WHERE d.mobile_user_id = :user_id
              AND d.status = 'paired'
              AND t.thread_id = :thread_id
            ORDER BY t.created_at DESC
            LIMIT :limit
            OFFSET :offset
            """
        )
    if active_only:
        return text(
            """
            SELECT t.* FROM mobile_relay_tasks t
            JOIN mobile_relay_desktops d ON d.relay_id = t.relay_id
            WHERE d.mobile_user_id = :user_id
              AND d.status = 'paired'
              AND t.status IN ('queued', 'running', 'assigned', 'processing', 'in_progress')
            ORDER BY t.created_at DESC
            LIMIT :limit
            OFFSET :offset
            """
        )
    return text(
        """
        SELECT t.* FROM mobile_relay_tasks t
        JOIN mobile_relay_desktops d ON d.relay_id = t.relay_id
        WHERE d.mobile_user_id = :user_id AND d.status = 'paired'
        ORDER BY t.created_at DESC
        LIMIT :limit
        OFFSET :offset
        """
    )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _utc_after(seconds: int) -> str:
    return (
        (datetime.now(UTC) + timedelta(seconds=max(60, int(seconds))))
        .replace(microsecond=0)
        .isoformat()
    )


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
    for key in ("capabilities_json", "payload_json", "result_json", "context_json"):
        if key in data:
            data[key.removesuffix("_json")] = _json_loads(data.pop(key))
    return data


def _bounded_text(value: Any, max_chars: int) -> str:
    text_value = str(value or "").strip()
    if not text_value or max_chars <= 0:
        return ""
    if len(text_value) <= max_chars:
        return text_value
    if max_chars == 1:
        return "…"
    return text_value[: max_chars - 1].rstrip() + "…"


def _object_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_text(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(mapping.get(key) or "").strip()
        if value:
            return value
    return ""


def _task_list_summary(task: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded allow-list used by the mobile execution-review list.

    Relay results can contain complete CLI transcripts, dispatch envelopes and
    tool-call payloads.  Those belong to the task-detail endpoint; returning
    them for every row made a 200-item phone request several megabytes large.
    Build the list row from scratch so future result fields cannot accidentally
    bypass the summary contract.
    """

    payload = _object_value(task.get("payload"))
    result = _object_value(task.get("result"))
    nested = _object_value(result.get("codex"))
    assistant = _object_value(nested.get("assistant_message"))
    session = _object_value(result.get("session")) or _object_value(nested.get("session"))

    message = _first_text(payload, "message", "body", "prompt")
    error = _first_text(result, "error", "error_message")
    assistant_body = _first_text(assistant, "body")
    reply = _first_text(result, "reply")
    result_text = error or assistant_body or reply
    branch = _first_text(session, "branch")

    result_summary: dict[str, Any] = {}
    bounded_result = _bounded_text(result_text, _TASK_SUMMARY_RESULT_MAX_CHARS)
    if error and bounded_result:
        result_summary["error"] = bounded_result
    elif assistant_body and bounded_result:
        result_summary["codex"] = {"assistant_message": {"body": bounded_result}}
    elif bounded_result:
        result_summary["reply"] = bounded_result

    error_code = _bounded_text(result.get("error_code"), _TASK_SUMMARY_CODE_MAX_CHARS)
    if error_code:
        result_summary["error_code"] = error_code
    if isinstance(result.get("ok"), bool):
        result_summary["ok"] = result["ok"]
    elapsed = result.get("elapsed_seconds")
    if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
        result_summary["elapsed_seconds"] = elapsed
    if branch:
        result_summary["session"] = {
            "branch": _bounded_text(branch, _TASK_SUMMARY_BRANCH_MAX_CHARS)
        }

    summary = {
        key: task.get(key)
        for key in (
            "task_id",
            "relay_id",
            "thread_id",
            "work_item_id",
            "employee_id",
            "attempt_no",
            "kind",
            "status",
            "created_by_user_id",
            "created_at",
            "updated_at",
            "claimed_at",
            "completed_at",
            "source",
        )
        if task.get(key) is not None
    }
    summary.update(
        {
            "payload": (
                {"message": _bounded_text(message, _TASK_SUMMARY_MESSAGE_MAX_CHARS)}
                if message
                else {}
            ),
            "result": result_summary,
            "summary_only": True,
            "summary_truncated": (
                len(message) > _TASK_SUMMARY_MESSAGE_MAX_CHARS
                or len(result_text) > _TASK_SUMMARY_RESULT_MAX_CHARS
                or len(branch) > _TASK_SUMMARY_BRANCH_MAX_CHARS
            ),
        }
    )
    return summary


def _public_base_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        value = FHD_API_BASE_URL
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/") + "/"


class MobileRelayService:
    """Small SQL-backed relay used by phones and desktop runtimes."""

    task_list_default_limit = _TASK_LIST_DEFAULT_LIMIT
    task_list_max_page_limit = _TASK_LIST_MAX_PAGE_LIMIT
    task_list_max_requested_limit = _TASK_LIST_MAX_REQUESTED_LIMIT
    task_list_max_response_bytes = _TASK_LIST_MAX_RESPONSE_BYTES
    task_summary_message_max_chars = _TASK_SUMMARY_MESSAGE_MAX_CHARS
    task_summary_result_max_chars = _TASK_SUMMARY_RESULT_MAX_CHARS
    task_summary_branch_max_chars = _TASK_SUMMARY_BRANCH_MAX_CHARS

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
                    thread_id VARCHAR(64) NOT NULL DEFAULT '',
                    work_item_id VARCHAR(64) NOT NULL DEFAULT '',
                    employee_id VARCHAR(80) NOT NULL DEFAULT '',
                    attempt_no INTEGER NOT NULL DEFAULT 1,
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
                """
                CREATE TABLE IF NOT EXISTS mobile_super_employee_threads (
                    thread_id VARCHAR(64) PRIMARY KEY,
                    relay_id VARCHAR(64) NOT NULL,
                    user_id INTEGER NOT NULL,
                    employee_id VARCHAR(80) NOT NULL,
                    tool VARCHAR(32) NOT NULL,
                    title VARCHAR(200) NOT NULL DEFAULT '',
                    status VARCHAR(32) NOT NULL DEFAULT 'idle',
                    cli_session_id VARCHAR(160) NOT NULL DEFAULT '',
                    workspace_root VARCHAR(1024) NOT NULL DEFAULT '',
                    branch VARCHAR(256) NOT NULL DEFAULT '',
                    last_task_id VARCHAR(64) NOT NULL DEFAULT '',
                    context_json TEXT NOT NULL DEFAULT '{}',
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    archived_at VARCHAR(64)
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS mobile_super_employee_work_items (
                    work_item_id VARCHAR(64) PRIMARY KEY,
                    thread_id VARCHAR(64) NOT NULL,
                    user_id INTEGER NOT NULL,
                    title VARCHAR(240) NOT NULL DEFAULT '',
                    status VARCHAR(32) NOT NULL DEFAULT 'queued',
                    last_run_id VARCHAR(64) NOT NULL DEFAULT '',
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    completed_at VARCHAR(64)
                )
                """
            )
        )
        # 兼容已经存在的 relay 数据库。SQLAlchemy inspector 同时覆盖 SQLite/PostgreSQL，
        # 避免直接执行重复 ALTER 导致 PostgreSQL 事务进入 aborted 状态。
        self._ensure_column(
            db, "mobile_relay_tasks", "thread_id", "VARCHAR(64) NOT NULL DEFAULT ''"
        )
        self._ensure_column(
            db, "mobile_relay_tasks", "work_item_id", "VARCHAR(64) NOT NULL DEFAULT ''"
        )
        self._ensure_column(
            db, "mobile_relay_tasks", "employee_id", "VARCHAR(80) NOT NULL DEFAULT ''"
        )
        self._ensure_column(db, "mobile_relay_tasks", "attempt_no", "INTEGER NOT NULL DEFAULT 1")
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
        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_mobile_relay_tasks_thread "
                "ON mobile_relay_tasks(thread_id, created_at)"
            )
        )
        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_mobile_super_threads_user_tool "
                "ON mobile_super_employee_threads(user_id, employee_id, updated_at)"
            )
        )

    @staticmethod
    def _ensure_column(db, table: str, column: str, ddl: str) -> None:
        # Inspect through the session's existing connection.  Inspecting the
        # Engine can open a second PostgreSQL connection while this transaction
        # still owns CREATE/ALTER metadata locks, which deadlocks the first
        # mobile relay poll and stalls the whole async API worker.
        connection = db.connection()
        columns = {
            str(item.get("name") or "") for item in sa_inspect(connection).get_columns(table)
        }
        if column not in columns:
            statement = _RELAY_TASK_COLUMN_DDL.get((table, column, ddl))
            if statement is None:
                raise ValueError("unsupported relay schema migration")
            db.execute(text(statement))

    @staticmethod
    def _tool_for_employee(employee_id: str) -> str:
        return _SUPER_EMPLOYEE_TOOLS.get((employee_id or "").strip(), "")

    @staticmethod
    def _employee_for_kind(kind: str) -> str:
        tool = (kind or "").strip().split(".", 1)[0]
        return _TOOL_EMPLOYEES.get(tool, "")

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

    def bind_mobile_by_account(
        self,
        *,
        user_id: int,
        username: str,
        relay_id: str = "",
    ) -> dict[str, Any] | None:
        """Bind a desktop relay to the authenticated mobile account.

        The phone obtains ``relay_id`` from the LAN pairing exchange. Cloud
        binding is then authorized by the logged-in mobile account instead of a
        QR/short-code secret, which prevents stale QR relay IDs from becoming
        the source of truth.
        """
        clean_relay_id = relay_id.strip()
        if not clean_relay_id:
            return None
        now = _utc_now()
        with get_db() as db:
            self.ensure_tables(db)
            row = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_relay_desktops
                        WHERE relay_id = :relay_id
                          AND status IN ('pending', 'paired')
                        """
                    ),
                    {"relay_id": clean_relay_id},
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            data = _row_dict(row)
            if data.get("status") == "pending" and str(data.get("expires_at") or "") < now:
                return None
            owner_id = int(data.get("mobile_user_id") or 0)
            if owner_id > 0 and owner_id != int(user_id):
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
                    "relay_id": clean_relay_id,
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

    def create_thread(
        self,
        *,
        user_id: int,
        relay_id: str,
        employee_id: str,
        title: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Create a real, resumable mobile conversation for one super employee."""
        clean_employee = (employee_id or "").strip()
        tool = self._tool_for_employee(clean_employee)
        if not tool or not self._desktop_belongs_to_user(user_id=user_id, relay_id=relay_id):
            return None
        now = _utc_now()
        thread_id = uuid.uuid4().hex
        clean_title = (title or f"{tool.title()} 新对话").strip()[:200]
        with get_db() as db:
            self.ensure_tables(db)
            db.execute(
                text(
                    """
                    INSERT INTO mobile_super_employee_threads (
                        thread_id, relay_id, user_id, employee_id, tool, title,
                        status, context_json, created_at, updated_at
                    ) VALUES (
                        :thread_id, :relay_id, :user_id, :employee_id, :tool, :title,
                        'idle', :context_json, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "thread_id": thread_id,
                    "relay_id": relay_id.strip(),
                    "user_id": int(user_id),
                    "employee_id": clean_employee,
                    "tool": tool,
                    "title": clean_title,
                    "context_json": _json_dumps(context or {}),
                    "created_at": now,
                    "updated_at": now,
                },
            )
        return self.get_thread(user_id=user_id, thread_id=thread_id)

    def get_thread(self, *, user_id: int, thread_id: str) -> dict[str, Any] | None:
        with get_db() as db:
            self.ensure_tables(db)
            row = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_super_employee_threads
                        WHERE thread_id = :thread_id AND user_id = :user_id
                        """
                    ),
                    {"thread_id": thread_id.strip(), "user_id": int(user_id)},
                )
                .mappings()
                .first()
            )
            return _row_dict(row) if row else None

    def list_threads(
        self,
        *,
        user_id: int,
        employee_id: str = "",
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "user_id": int(user_id),
            "limit": max(1, min(300, int(limit))),
        }
        if employee_id.strip():
            params["employee_id"] = employee_id.strip()
        with get_db() as db:
            self.ensure_tables(db)
            rows = (
                db.execute(
                    _thread_list_statement(
                        filter_employee=bool(employee_id.strip()),
                        only_unarchived=not include_archived,
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            return [_row_dict(row) for row in rows]

    def archive_thread(self, *, user_id: int, thread_id: str) -> dict[str, Any] | None:
        now = _utc_now()
        with get_db() as db:
            self.ensure_tables(db)
            db.execute(
                text(
                    """
                    UPDATE mobile_super_employee_threads
                    SET status = 'archived', archived_at = :now, updated_at = :now
                    WHERE thread_id = :thread_id AND user_id = :user_id
                    """
                ),
                {"thread_id": thread_id.strip(), "user_id": int(user_id), "now": now},
            )
        return self.get_thread(user_id=user_id, thread_id=thread_id)

    def create_task(
        self,
        *,
        user_id: int,
        relay_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        thread_id: str = "",
        work_item_id: str = "",
    ) -> dict[str, Any] | None:
        if not self._desktop_belongs_to_user(user_id=user_id, relay_id=relay_id):
            return None
        task_id = uuid.uuid4().hex
        now = _utc_now()
        safe_kind = (kind or "codex.invoke").strip()[:64] or "codex.invoke"
        employee_id = self._employee_for_kind(safe_kind)
        clean_thread_id = (thread_id or "").strip()
        thread: dict[str, Any] | None = None
        if clean_thread_id:
            thread = self.get_thread(user_id=user_id, thread_id=clean_thread_id)
            if (
                not thread
                or str(thread.get("relay_id") or "") != relay_id.strip()
                or str(thread.get("employee_id") or "") != employee_id
                or thread.get("archived_at")
            ):
                return None
        safe_payload = dict(payload or {})
        context = (
            safe_payload.get("context") if isinstance(safe_payload.get("context"), dict) else {}
        )
        if clean_thread_id:
            context = {
                **context,
                "thread_id": clean_thread_id,
                "conversation_id": clean_thread_id,
                "persistent_conversation": True,
            }
            safe_payload["context"] = context
            safe_payload["thread_id"] = clean_thread_id
        clean_work_item_id = (work_item_id or "").strip() or uuid.uuid4().hex
        with get_db() as db:
            self.ensure_tables(db)
            attempt_no = 1
            if work_item_id.strip():
                previous = db.execute(
                    text(
                        "SELECT MAX(attempt_no) FROM mobile_relay_tasks "
                        "WHERE work_item_id = :work_item_id"
                    ),
                    {"work_item_id": clean_work_item_id},
                ).scalar()
                attempt_no = int(previous or 0) + 1
            title = str(
                safe_payload.get("message")
                or safe_payload.get("body")
                or safe_payload.get("prompt")
                or safe_kind
            ).strip()[:240]
            db.execute(
                text(
                    """
                    INSERT INTO mobile_super_employee_work_items (
                        work_item_id, thread_id, user_id, title, status,
                        last_run_id, created_at, updated_at
                    ) VALUES (
                        :work_item_id, :thread_id, :user_id, :title, 'queued',
                        :last_run_id, :created_at, :updated_at
                    )
                    ON CONFLICT(work_item_id) DO UPDATE SET
                        status = 'queued', last_run_id = :last_run_id, updated_at = :updated_at,
                        completed_at = NULL
                    """
                ),
                {
                    "work_item_id": clean_work_item_id,
                    "thread_id": clean_thread_id,
                    "user_id": int(user_id),
                    "title": title,
                    "last_run_id": task_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            db.execute(
                text(
                    """
                    INSERT INTO mobile_relay_tasks (
                        task_id, relay_id, thread_id, work_item_id, employee_id,
                        attempt_no, kind, payload_json, status,
                        result_json, created_by_user_id, created_at, updated_at
                    ) VALUES (
                        :task_id, :relay_id, :thread_id, :work_item_id, :employee_id,
                        :attempt_no, :kind, :payload_json, 'queued',
                        '{}', :created_by_user_id, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "task_id": task_id,
                    "relay_id": relay_id.strip(),
                    "thread_id": clean_thread_id,
                    "work_item_id": clean_work_item_id,
                    "employee_id": employee_id,
                    "attempt_no": attempt_no,
                    "kind": safe_kind,
                    "payload_json": _json_dumps(safe_payload),
                    "created_by_user_id": int(user_id),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            if clean_thread_id:
                db.execute(
                    text(
                        """
                        UPDATE mobile_super_employee_threads
                        SET status = 'queued', last_task_id = :task_id, updated_at = :now
                        WHERE thread_id = :thread_id AND user_id = :user_id
                        """
                    ),
                    {
                        "task_id": task_id,
                        "thread_id": clean_thread_id,
                        "user_id": int(user_id),
                        "now": now,
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

    def list_tasks(
        self,
        *,
        user_id: int,
        thread_id: str = "",
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "user_id": int(user_id),
            "limit": max(1, min(300, int(limit))),
            "offset": max(0, int(offset)),
        }
        if thread_id.strip():
            params["thread_id"] = thread_id.strip()
        with get_db() as db:
            self.ensure_tables(db)
            rows = (
                db.execute(
                    _task_list_statement(
                        filter_thread=bool(thread_id.strip()),
                        active_only=active_only,
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            return [_row_dict(row) for row in rows]

    def list_task_summaries(
        self,
        *,
        user_id: int,
        thread_id: str = "",
        active_only: bool = False,
        limit: int = _TASK_LIST_DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return [
            _task_list_summary(task)
            for task in self.list_tasks(
                user_id=user_id,
                thread_id=thread_id,
                active_only=active_only,
                limit=limit,
                offset=offset,
            )
        ]

    def retry_task(self, *, user_id: int, task_id: str) -> dict[str, Any] | None:
        previous = self.get_task(user_id=user_id, task_id=task_id)
        if not previous or str(previous.get("status") or "") in _ACTIVE_TASK_STATUSES:
            return None
        return self.create_task(
            user_id=user_id,
            relay_id=str(previous.get("relay_id") or ""),
            kind=str(previous.get("kind") or "codex.invoke"),
            payload=previous.get("payload") if isinstance(previous.get("payload"), dict) else {},
            thread_id=str(previous.get("thread_id") or ""),
            work_item_id=str(previous.get("work_item_id") or ""),
        )

    def cancel_task(self, *, user_id: int, task_id: str) -> dict[str, Any] | None:
        """手机端取消任务：仅 queued/running 可取消，标记为 cancelled。"""
        now = _utc_now()
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
            if not row:
                return None
            cur_status = str(row.get("status") or "").strip()
            if cur_status not in {"queued", "running"}:
                return _row_dict(row)
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_tasks
                    SET status = 'cancelled',
                        completed_at = :now,
                        updated_at = :now
                    WHERE task_id = :task_id AND status IN ('queued', 'running')
                    """
                ),
                {"task_id": task_id.strip(), "now": now},
            )
            thread_id = str(row.get("thread_id") or "")
            work_item_id = str(row.get("work_item_id") or "")
            if work_item_id:
                db.execute(
                    text(
                        """
                        UPDATE mobile_super_employee_work_items
                        SET status = 'cancelled', completed_at = :now, updated_at = :now
                        WHERE work_item_id = :work_item_id
                        """
                    ),
                    {"work_item_id": work_item_id, "now": now},
                )
            if thread_id:
                db.execute(
                    text(
                        """
                        UPDATE mobile_super_employee_threads
                        SET status = 'cancelled', updated_at = :now
                        WHERE thread_id = :thread_id AND user_id = :user_id
                        """
                    ),
                    {"thread_id": thread_id, "user_id": int(user_id), "now": now},
                )
            cancelled = _row_dict(row)
            cancelled.update(
                {
                    "status": "cancelled",
                    "completed_at": now,
                    "updated_at": now,
                }
            )
            return cancelled

    def poll_desktop(
        self,
        *,
        relay_id: str,
        desktop_token: str,
        max_tasks: int = 5,
        busy_tools: list[str] | None = None,
        inflight_task_ids: list[str] | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = _utc_now()
        with get_db() as db:
            self.ensure_tables(db)
            desktop = self._desktop_for_token(db, relay_id=relay_id, desktop_token=desktop_token)
            if not desktop:
                return None
            clean_capabilities = capabilities if isinstance(capabilities, dict) else {}
            existing_capabilities = (
                desktop.get("capabilities") if isinstance(desktop.get("capabilities"), dict) else {}
            )
            merged_capabilities = {**existing_capabilities, **clean_capabilities}
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_desktops
                    SET last_seen_at = :now,
                        updated_at = :now,
                        capabilities_json = CASE
                            WHEN :has_capabilities = 1 THEN :capabilities_json
                            ELSE capabilities_json
                        END
                    WHERE relay_id = :relay_id
                    """
                ),
                {
                    "now": now,
                    "relay_id": relay_id.strip(),
                    "has_capabilities": 1 if clean_capabilities else 0,
                    "capabilities_json": _json_dumps(merged_capabilities),
                },
            )
            # 孤儿回收：执行端中途死会把任务永久卡在 running（poll 只发 queued，无人再认领）。
            # 每次 poll 先把本 relay claimed_at 超 TTL 的 running 重置回 queued，活 relay 自动重认领，
            # 根治『永久卡 running』。同一 relay 仍在跑的任务由执行端 _INFLIGHT 去重，不会重复执行；
            # 真完成时 complete 覆盖 queued 态，无副作用。
            try:
                stale_ttl = max(60, int(os.environ.get("XCAGI_RELAY_RUNNING_TTL_SEC") or "900"))
            except (TypeError, ValueError):
                stale_ttl = 900
            stale_before = (
                (datetime.now(UTC) - timedelta(seconds=stale_ttl))
                .replace(microsecond=0)
                .isoformat()
            )
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_tasks
                    SET status = 'queued', claimed_at = NULL, updated_at = :now
                    WHERE relay_id = :relay_id AND status = 'running'
                      AND claimed_at IS NOT NULL AND claimed_at < :stale_before
                    """
                ),
                {"relay_id": relay_id.strip(), "now": now, "stale_before": stale_before},
            )
            # Cancellation delivery is scoped twice: the desktop token above must
            # authenticate this relay, and only task ids that the same desktop says
            # it is currently executing are echoed back.  A tenant cannot cancel or
            # signal another relay's process by guessing a task id.
            requested_inflight = {
                str(task_id or "").strip()
                for task_id in (inflight_task_ids or [])[:20]
                if str(task_id or "").strip()
            }
            cancelled_task_ids: list[str] = []
            if requested_inflight:
                cancelled_rows = (
                    db.execute(
                        text(
                            """
                            SELECT task_id FROM mobile_relay_tasks
                            WHERE relay_id = :relay_id AND status = 'cancelled'
                            ORDER BY updated_at DESC
                            LIMIT 100
                            """
                        ),
                        {"relay_id": relay_id.strip()},
                    )
                    .mappings()
                    .all()
                )
                cancelled_task_ids = [
                    str(row.get("task_id") or "")
                    for row in cancelled_rows
                    if str(row.get("task_id") or "") in requested_inflight
                ]
            rows = (
                db.execute(
                    text(
                        """
                        SELECT * FROM mobile_relay_tasks
                        WHERE relay_id = :relay_id AND status = 'queued'
                        ORDER BY created_at ASC
                        LIMIT 500
                        """
                    ),
                    {"relay_id": relay_id.strip()},
                )
                .mappings()
                .all()
            )
            # 每个超级员工只有一个执行槽：同一工具内部串行，不同工具可以并行。
            # 执行端把当前 busy_tools 传来，避免服务端把第二个 Codex 提前 claim 成 running。
            claimed_tools = {
                str(tool or "").strip().split(".", 1)[0]
                for tool in (busy_tools or [])
                if str(tool or "").strip()
            }
            limit = max(0, min(20, int(max_tasks)))
            tasks: list[dict[str, Any]] = []
            for row in rows if limit > 0 else []:
                task = _row_dict(row)
                tool = str(task.get("kind") or "").strip().split(".", 1)[0] or "unknown"
                if tool in claimed_tools:
                    continue
                claimed = db.execute(
                    text(
                        """
                        UPDATE mobile_relay_tasks
                        SET status = 'running', claimed_at = :now, updated_at = :now
                        WHERE task_id = :task_id AND status = 'queued'
                        """
                    ),
                    {"task_id": task["task_id"], "now": now},
                )
                # 多个 poll 请求重叠时只有一个能把 queued 原子切到 running；
                # 未抢到的请求不能把同一任务再次返回给另一个执行线程。
                if int(claimed.rowcount or 0) != 1:
                    continue
                tasks.append(task)
                claimed_tools.add(tool)
                task["status"] = "running"
                task["claimed_at"] = now
                thread_id = str(task.get("thread_id") or "")
                work_item_id = str(task.get("work_item_id") or "")
                if work_item_id:
                    db.execute(
                        text(
                            """
                            UPDATE mobile_super_employee_work_items
                            SET status = 'running', last_run_id = :task_id, updated_at = :now
                            WHERE work_item_id = :work_item_id
                            """
                        ),
                        {"work_item_id": work_item_id, "task_id": task["task_id"], "now": now},
                    )
                if thread_id:
                    db.execute(
                        text(
                            """
                            UPDATE mobile_super_employee_threads
                            SET status = 'running', last_task_id = :task_id, updated_at = :now
                            WHERE thread_id = :thread_id
                            """
                        ),
                        {"thread_id": thread_id, "task_id": task["task_id"], "now": now},
                    )
                if len(tasks) >= limit:
                    break
        return {
            "desktop": self._public_desktop(desktop),
            "tasks": tasks,
            "task_count": len(tasks),
            "cancelled_task_ids": cancelled_task_ids,
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
        requested_status = (status or "completed").strip().lower()
        if requested_status == "done":
            requested_status = "completed"
        final_status = (
            requested_status
            if requested_status in {"completed", "failed", "blocked", "cancelled"}
            else "completed"
        )
        with get_db() as db:
            self.ensure_tables(db)
            desktop = self._desktop_for_token(db, relay_id=relay_id, desktop_token=desktop_token)
            if not desktop:
                return None
            db.execute(
                text(
                    """
                    UPDATE mobile_relay_tasks
                    SET status = CASE WHEN status = 'cancelled' THEN status ELSE :status END,
                        result_json = CASE WHEN status = 'cancelled'
                            THEN result_json ELSE :result_json END,
                        completed_at = CASE WHEN status = 'cancelled'
                            THEN completed_at ELSE :now END,
                        updated_at = CASE WHEN status = 'cancelled'
                            THEN updated_at ELSE :now END
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
            task_row = _row_dict(row) if row else None
            if task_row:
                effective_status = str(task_row.get("status") or final_status).strip().lower()
                thread_id = str(task_row.get("thread_id") or "")
                work_item_id = str(task_row.get("work_item_id") or "")
                if work_item_id:
                    db.execute(
                        text(
                            """
                            UPDATE mobile_super_employee_work_items
                            SET status = :status, last_run_id = :task_id,
                                completed_at = :now, updated_at = :now
                            WHERE work_item_id = :work_item_id
                            """
                        ),
                        {
                            "status": effective_status,
                            "task_id": task_id.strip(),
                            "work_item_id": work_item_id,
                            "now": now,
                        },
                    )
                if thread_id:
                    runtime = (
                        {"cli_session_id": "", "workspace_root": "", "branch": ""}
                        if effective_status == "cancelled"
                        else self._thread_runtime_from_result(result or {})
                    )
                    db.execute(
                        text(
                            """
                            UPDATE mobile_super_employee_threads
                            SET status = :status, last_task_id = :task_id,
                                cli_session_id = CASE WHEN :cli_session_id <> ''
                                    THEN :cli_session_id ELSE cli_session_id END,
                                workspace_root = CASE WHEN :workspace_root <> ''
                                    THEN :workspace_root ELSE workspace_root END,
                                branch = CASE WHEN :branch <> '' THEN :branch ELSE branch END,
                                updated_at = :now
                            WHERE thread_id = :thread_id
                            """
                        ),
                        {
                            "status": effective_status,
                            "task_id": task_id.strip(),
                            "cli_session_id": runtime["cli_session_id"],
                            "workspace_root": runtime["workspace_root"],
                            "branch": runtime["branch"],
                            "thread_id": thread_id,
                            "now": now,
                        },
                    )
        # 终态主动推送创建者手机（FCM + 离线队列轮询补发）——在 DB 事务收尾后再发，
        # 不让推送网络耗时拖住 complete 回写。此前任务完成只写库，手机要等下次打开
        # App 轮询才知道结果，"超级员工干完活"对老板完全无感。
        if task_row:
            self._notify_task_creator(task_row)
        return task_row

    @staticmethod
    def _thread_runtime_from_result(result: dict[str, Any]) -> dict[str, str]:
        """Extract executor session/workspace metadata without coupling to one CLI result shape."""
        nested = result.get("codex") if isinstance(result.get("codex"), dict) else {}
        session = result.get("session") if isinstance(result.get("session"), dict) else {}
        nested_session = nested.get("session") if isinstance(nested.get("session"), dict) else {}
        merged = {**nested_session, **session}
        return {
            "cli_session_id": str(
                merged.get("session_id")
                or merged.get("cli_session_id")
                or result.get("session_id")
                or ""
            ).strip()[:160],
            "workspace_root": str(
                merged.get("workspace_root") or result.get("workspace_root") or ""
            ).strip()[:1024],
            "branch": str(merged.get("branch") or result.get("branch") or "").strip()[:256],
        }

    @staticmethod
    def _notify_task_creator(task: dict[str, Any]) -> None:
        """CLI 执行类任务(*.invoke)到达终态时推送创建者。

        git.merge/diff/discard 是人守在 App 里等结果的同步交互，事后补推只会
        变成噪音，跳过；cancelled 是用户自己取消的，也不推。推送失败仅记日志，
        绝不影响 complete 主流程。channel 必须用 App 已注册的通知渠道(xcagi_chat)。
        """
        try:
            uid = int(task.get("created_by_user_id") or 0)
        except (TypeError, ValueError):
            uid = 0
        kind = str(task.get("kind") or "").strip()
        status = str(task.get("status") or "").strip()
        title = {
            "completed": "✅ 超级员工任务完成",
            "failed": "❌ 超级员工任务失败",
            "blocked": "⏸️ 超级员工任务受阻",
        }.get(status)
        if uid <= 0 or not kind.endswith(".invoke") or not title:
            return
        # _row_dict 已把 result_json 解析进 "result"；直查裸行时兜底再解一次。
        result = task.get("result")
        if not isinstance(result, dict):
            try:
                result = json.loads(task.get("result_json") or "{}")
            except (TypeError, ValueError):
                result = {}
        body = ""
        if isinstance(result, dict):
            body = str(
                result.get("summary")
                or result.get("answer")
                or result.get("output")
                or result.get("error_message")
                or result.get("error")
                or ""
            ).strip()
        tool = kind.split(".", 1)[0]
        if not body:
            body = f"{tool} 已结束本次任务，打开对话查看详情。"
        try:
            from app.services.mobile_push import notify_user

            notify_user(
                uid,
                title=title,
                body=body[:200],
                data={
                    "channel": "xcagi_chat",
                    "type": "relay_task_done",
                    "route": "xcagi://chat",
                    "task_id": str(task.get("task_id") or ""),
                    "task_status": status,
                    "tool": tool,
                },
            )
        except Exception:  # noqa: BLE001 - 推送是尽力而为的旁路
            logger.warning(
                "relay task completion push failed task_id=%s", task.get("task_id"), exc_info=True
            )

    def _fresh_pairing_code(self) -> str:
        with get_db() as db:
            self.ensure_tables(db)
            for _ in range(100):
                code = str(secrets.randbelow(900000) + 100000)
                exists = (
                    db.execute(
                        text("SELECT 1 FROM mobile_relay_desktops WHERE pairing_code = :code"),
                        {"code": code},
                    ).first()
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
        capabilities = (
            data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {}
        )
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
        }
