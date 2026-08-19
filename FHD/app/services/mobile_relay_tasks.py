"""Task queue workflows for :class:`MobileRelayService`."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.services.mobile_relay_utils import _json_dumps, _row_dict, _utc_now


class MobileRelayTaskMixin:
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

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
        with self._get_db() as db:
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
        with self._get_db() as db:
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

    def cancel_task(self, *, user_id: int, task_id: str) -> dict[str, Any] | None:
        """手机端取消任务：仅 queued/running 可取消，标记为 cancelled。"""
        now = _utc_now()
        with self._get_db() as db:
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
            return _row_dict(row)

    def poll_desktop(
        self,
        *,
        relay_id: str,
        desktop_token: str,
        max_tasks: int = 5,
    ) -> dict[str, Any] | None:
        now = _utc_now()
        with self._get_db() as db:
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
        requested_status = (status or "completed").strip().lower()
        if requested_status == "done":
            requested_status = "completed"
        final_status = (
            requested_status
            if requested_status in {"completed", "failed", "blocked", "cancelled"}
            else "completed"
        )
        with self._get_db() as db:
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
            task_row = _row_dict(row) if row else None
        # 终态主动推送创建者手机（FCM + 离线队列轮询补发）——在 DB 事务收尾后再发，
        # 不让推送网络耗时拖住 complete 回写。此前任务完成只写库，手机要等下次打开
        # App 轮询才知道结果，"超级员工干完活"对老板完全无感。
        if task_row:
            self._notify_task_creator(task_row)
        return task_row
