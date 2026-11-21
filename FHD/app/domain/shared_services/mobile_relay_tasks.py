"""Task queue workflows for :class:`MobileRelayService`."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult

from app.application.mobile_relay_ports import TaskPorts
from app.domain.shared_services.mobile_relay_utils import _json_dumps, _row_dict, _utc_now

ENVELOPE_ALG = "x25519-hkdf-sha256-aesgcm"


def is_e2ee_envelope(value: Any, *, require_epk: bool = True) -> bool:
    """手机↔桌面端到端加密信封：云端只做密文中转，不接触明文。"""
    if not isinstance(value, dict):
        return False
    if int(value.get("v") or 0) != 1:
        return False
    alg = str(value.get("alg") or ENVELOPE_ALG)
    if alg != ENVELOPE_ALG:
        return False
    fields = ("epk", "nonce", "ct") if require_epk else ("nonce", "ct")
    return all(isinstance(value.get(field), str) and value.get(field) for field in fields)


def is_e2ee_error(value: Any) -> bool:
    """桌面端无法解密时只回传错误标记，不回传任何内容。"""
    return isinstance(value, dict) and value.get("e2ee_error") is True


@dataclass(frozen=True, eq=False)
class RelayTaskQueue:
    ports: TaskPorts

    def create_task(
        self,
        *,
        user_id: int,
        relay_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.ports.desktop_belongs_to_user(user_id=user_id, relay_id=relay_id):
            return None
        # 桌面端已登记公钥时必须走端到端加密；旧版未登记公钥的执行端暂时保持兼容。
        if self.ports.desktop_public_key(user_id=user_id, relay_id=relay_id) and not (
            is_e2ee_envelope(payload)
        ):
            raise ValueError("relay payload must be end-to-end encrypted")
        task_id = uuid.uuid4().hex
        now = _utc_now()
        safe_kind = (kind or "codex.invoke").strip()[:64] or "codex.invoke"
        with self.ports.database() as db:
            self.ports.ensure_tables(db)
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
        return self.ports.get_task(user_id=user_id, task_id=task_id)

    def get_task(self, *, user_id: int, task_id: str) -> dict[str, Any] | None:
        with self.ports.database() as db:
            self.ports.ensure_tables(db)
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

    def cancel_task(self, *, user_id: int, task_id: str) -> dict[str, Any] | None:
        """Only an unclaimed task can be cancelled without a desktop receipt."""
        now = _utc_now()
        with self.ports.database() as db:
            self.ports.ensure_tables(db)
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
                    SET status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE 'unknown' END,
                        completed_at = CASE WHEN status = 'queued' THEN :now ELSE NULL END,
                        updated_at = :now
                    WHERE task_id = :task_id AND status IN ('queued', 'running')
                    """
                ),
                {"task_id": task_id.strip(), "now": now},
            )
            updated = (
                db.execute(
                    text("SELECT * FROM mobile_relay_tasks WHERE task_id = :task_id"),
                    {"task_id": task_id.strip()},
                )
                .mappings()
                .first()
            )
            return _row_dict(updated) if updated else None

    def _purge_expired(self, db) -> None:
        """终态任务只保留短周期密文；排队任务最多 7 天，避免云端长期堆积。"""
        try:
            hours = max(1, int(os.environ.get("XCAGI_RELAY_RETENTION_HOURS") or "24"))
        except (TypeError, ValueError):
            hours = 24
        current = datetime.now(UTC).replace(microsecond=0)
        cutoff = (current - timedelta(hours=hours)).isoformat()
        queued_cutoff = (current - timedelta(days=7)).isoformat()
        db.execute(
            text(
                "DELETE FROM mobile_relay_tasks WHERE status IN ('completed', 'failed', 'cancelled') AND updated_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        # Erase expired ciphertext without losing the only address for an
        # unresolved execution. Clearing payloads never authorizes replay.
        db.execute(
            text(
                "UPDATE mobile_relay_tasks SET status = 'unknown', payload_json = '{}', "
                "result_json = '{}', completed_at = NULL, updated_at = :now "
                "WHERE status NOT IN ('queued', 'completed', 'failed', 'cancelled') "
                "AND updated_at < :cutoff"
            ),
            {"cutoff": cutoff, "now": current.isoformat()},
        )
        db.execute(
            text("DELETE FROM mobile_relay_tasks WHERE status = 'queued' AND created_at < :cutoff"),
            {"cutoff": queued_cutoff},
        )

    def poll_desktop(
        self,
        *,
        relay_id: str,
        desktop_token: str,
        max_tasks: int = 5,
    ) -> dict[str, Any] | None:
        now = _utc_now()
        with self.ports.database() as db:
            self.ports.ensure_tables(db)
            desktop = self.ports.desktop_for_token(
                db, relay_id=relay_id, desktop_token=desktop_token
            )
            if not desktop:
                return None
            # 加密前提下只保留短周期密文：终态任务按 TTL 删除，排队任务最长保留 7 天。
            self._purge_expired(db)
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
            # A missing desktop receipt cannot prove that a side effect did not happen.
            # Keep the same task addressable; process-local _INFLIGHT is not a replay fence.
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
                    SET status = 'unknown', updated_at = :now
                    WHERE relay_id = :relay_id AND status = 'running'
                      AND claimed_at IS NOT NULL AND claimed_at < :stale_before
                    """
                ),
                {"relay_id": relay_id.strip(), "now": now, "stale_before": stale_before},
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
            tasks = []
            for row in rows:
                task = _row_dict(row)
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
                if cast(CursorResult[Any], claimed).rowcount != 1:
                    continue
                task["status"] = "running"
                task["claimed_at"] = now
                tasks.append(task)
        return {
            "desktop": self.ports.public_desktop(desktop),
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
        requested_status = (status or "unknown").strip().lower()
        if requested_status == "done":
            requested_status = "completed"
        final_status = (
            requested_status
            if requested_status in {"completed", "failed", "blocked", "cancelled", "unknown"}
            else "unknown"
        )
        with self.ports.database() as db:
            self.ports.ensure_tables(db)
            desktop = self.ports.desktop_for_token(
                db, relay_id=relay_id, desktop_token=desktop_token
            )
            if not desktop:
                return None
            if str(desktop.get("desktop_public_key") or "").strip() and not (
                is_e2ee_envelope(result, require_epk=False) or is_e2ee_error(result)
            ):
                raise ValueError("relay result must be end-to-end encrypted")
            updated = db.execute(
                text(
                    """
                    UPDATE mobile_relay_tasks
                    SET status = :status,
                        result_json = :result_json,
                        completed_at = :completed_at,
                        updated_at = :now
                    WHERE task_id = :task_id AND relay_id = :relay_id
                      AND status NOT IN ('completed', 'failed', 'cancelled')
                    """
                ),
                {
                    "status": final_status,
                    "result_json": _json_dumps(result or {}),
                    "now": now,
                    "completed_at": now
                    if final_status in {"completed", "failed", "cancelled"}
                    else None,
                    "task_id": task_id.strip(),
                    "relay_id": relay_id.strip(),
                },
            )
            changed = cast(CursorResult[Any], updated).rowcount == 1
            row = (
                db.execute(
                    text(
                        "SELECT * FROM mobile_relay_tasks WHERE task_id = :task_id AND relay_id = :relay_id"
                    ),
                    {"task_id": task_id.strip(), "relay_id": relay_id.strip()},
                )
                .mappings()
                .first()
            )
            task_row = _row_dict(row) if row else None
            if not changed:
                return (
                    task_row
                    if task_row and task_row.get("status") in {"completed", "failed", "cancelled"}
                    else None
                )
        # 终态主动推送创建者手机（FCM + 离线队列轮询补发）——在 DB 事务收尾后再发，
        # 不让推送网络耗时拖住 complete 回写。此前任务完成只写库，手机要等下次打开
        # App 轮询才知道结果，"超级员工干完活"对老板完全无感。
        if task_row:
            self.ports.notify_task_creator(task_row)
        return task_row
