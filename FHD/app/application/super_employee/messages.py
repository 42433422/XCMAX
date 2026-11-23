"""Reconcile persisted dispatcher messages with scheduler results and direct replies."""

from __future__ import annotations

from typing import Any

from app.application.message_repository import MessageRepository

from .common import (
    DISPATCHER_MESSAGE_KIND,
    PARA_TERMINAL_TASK_STATUSES,
    TASK_ID_RE,
    _coerce_list,
    _utc_now,
)
from .profiles import SuperEmployeeToolProfile
from .protocols import MessageSyncPorts


class MessageSynchronizer:
    def __init__(
        self,
        profile: SuperEmployeeToolProfile,
        repository: MessageRepository,
        ports: MessageSyncPorts,
    ) -> None:
        self._p, self._repository, self._ports = profile, repository, ports

    def read_dispatch_receipt(
        self, *, user_id: int, request_id: str, task_id: str
    ) -> dict[str, Any] | None:
        """Read one owned original dispatch without message backfills or execution."""
        if not request_id:
            return None
        rows = [
            row
            for row in self._ports.read_rows()
            if int(row.get("user_id") or 0) == int(user_id)
            and row.get("dispatch_request_id") == request_id
            and row.get("kind") == DISPATCHER_MESSAGE_KIND
            and (not task_id or row.get("task_id") == task_id)
        ]
        if len(rows) > 1:
            return None
        original_id = str(rows[0].get("task_id") or "") if rows else ""
        with self._repository.dispatch_lock(user_id, request_id):
            request = self._repository.read_dispatch_request(user_id, request_id)
            receipt = request.get("dispatch_receipt") if request else None
            if request and isinstance(receipt, dict) and receipt.get("dispatcher") == "para_api":
                if request.get("employee_id") != self._p.employee_id:
                    return None
                if receipt.get("pending_request_id") or receipt.get("status") in {
                    "dispatching",
                    "dispatch_unknown",
                    "dispatch_pending",
                }:
                    receipt = self._ports.reconcile_dispatch(request)
                original_id = str(receipt.get("task_id") or original_id)
                if task_id and task_id != original_id:
                    return None
                if receipt.get("accepted") is not True:
                    return {
                        "dispatch": {
                            "request_id": request_id,
                            "task_id": original_id,
                            "status": receipt.get("status", "dispatch_unknown"),
                        },
                        "assistant_message": {"body": self._ports.dispatch_reply(receipt)},
                    }
        if not original_id:
            return None
        task = self._ports.fetch_task(original_id)
        if not task or str(task.get("id") or task.get("task_id") or "") != original_id:
            return None
        state = str(task.get("status") or "unknown")
        state = {"merged": "completed", "merge_conflict": "blocked"}.get(state, state)
        return {
            "dispatch": {
                "request_id": request_id,
                "task_id": original_id,
                "status": state,
            },
            "assistant_message": {"body": self._ports.task_reply(task)},
        }

    def _reconcile_pending_dispatches(self, *, user_id: int, rows: list[dict[str, Any]]) -> None:
        changed = False
        pending = [
            row
            for row in rows
            if int(row.get("user_id") or 0) == int(user_id)
            and row.get("kind") == DISPATCHER_MESSAGE_KIND
            and row.get("dispatcher") == "para_api"
            and row.get("status") in {"dispatching", "dispatch_unknown", "dispatch_pending"}
        ]
        for row in pending[-8:]:
            recovered = self.read_dispatch_receipt(
                user_id=user_id,
                request_id=str(row.get("dispatch_request_id") or ""),
                task_id=str(row.get("task_id") or ""),
            )
            if recovered is None:
                continue
            dispatch = recovered["dispatch"]
            uncertain = dispatch["status"] in {
                "dispatching",
                "dispatch_unknown",
                "dispatch_pending",
            }
            row.update(
                task_id=dispatch["task_id"],
                status=dispatch["status"],
                reconciliation_required=uncertain,
                body=recovered["assistant_message"]["body"],
            )
            changed = True
        if changed:
            self._ports.write_rows(rows)

    def sync_para_task_updates(self, *, user_id: int, rows: list[dict[str, Any]]) -> None:
        self._reconcile_pending_dispatches(user_id=user_id, rows=rows)
        changed = False
        synced = 0
        direct_request_ids = {
            str(item.get("dispatch_request_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and str(item.get("kind") or "") == self._p.direct_kind
        }
        result_request_ids = {
            str(item.get("dispatch_request_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and str(item.get("kind") or "") == self._p.result_kind
        }
        result_task_ids = {
            str(item.get("task_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and str(item.get("kind") or "") == self._p.result_kind
        }
        for row in reversed(list(rows)):
            if int(row.get("user_id") or 0) != int(user_id):
                continue
            changed = self.upgrade_legacy_dispatcher_row(row) or changed
            if str(row.get("kind") or "") != DISPATCHER_MESSAGE_KIND:
                continue
            task_id = str(row.get("task_id") or "").strip()
            if not task_id:
                continue
            request_id = str(row.get("dispatch_request_id") or "")
            if request_id and request_id in direct_request_ids:
                continue
            task_status = str(row.get("task_status") or row.get("status") or "").strip()
            if task_status in PARA_TERMINAL_TASK_STATUSES and (
                request_id and request_id in result_request_ids or task_id in result_task_ids
            ):
                continue
            if synced >= 8:
                break
            task = self._ports.fetch_task(task_id)
            synced += 1
            if not task:
                continue
            changed = self._ports.refresh(row, task) or changed
            changed = (
                self._ports.upsert_result(
                    user_id=int(user_id), dispatch_row=row, task=task, rows=rows
                )
                or changed
            )
        if changed:
            self._ports.write_rows(rows)

    def upgrade_legacy_dispatcher_row(self, row: dict[str, Any]) -> bool:
        if str(row.get("kind") or "") in {
            DISPATCHER_MESSAGE_KIND,
            self._p.direct_kind,
            self._p.result_kind,
        } or row.get("cli_execution"):
            return False
        if str(row.get("role") or "") != "assistant":
            return False
        body = str(row.get("body") or "")
        if not self.is_dispatcher_ack_body(body):
            return False
        row["role"] = "system"
        row["kind"] = DISPATCHER_MESSAGE_KIND
        task_id = self.extract_task_id_from_body(body)
        if task_id and (not row.get("task_id")):
            row["task_id"] = task_id
        return True

    def is_dispatcher_ack_body(self, body: str) -> bool:
        markers = (
            "多设备调度器",
            "调用队列",
            "调度通道",
            f"未发现在线可用 {self._p.display_tool} 设备",
            "任务已派发到",
            f"Para/{self._p.display_tool}",
        )
        return any(marker in body for marker in markers)

    def extract_task_id_from_body(self, body: str) -> str:
        match = TASK_ID_RE.search(body)
        return match.group(1).strip() if match else ""

    def upsert_direct_reply_messages(self, *, user_id: int, rows: list[dict[str, Any]]) -> bool:
        """Rebuild static presentation only; reading history never starts another CLI call."""
        request_ids_with_reply = {
            str(item.get("dispatch_request_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and (
                str(item.get("kind") or "") in {self._p.direct_kind, self._p.result_kind}
                or (
                    str(item.get("role") or "") == "assistant"
                    and str(item.get("kind") or "") != DISPATCHER_MESSAGE_KIND
                )
            )
        }
        request_ids_with_reply.update(
            str(item.get("dispatch_request_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and (
                item.get("reconciliation_required")
                or item.get("status") in {"dispatching", "dispatch_unknown"}
                or item.get("dispatcher") in {"para_api", "webhook"}
            )
        )
        changed = False
        for item in list(rows):
            if int(item.get("user_id") or 0) != int(user_id):
                continue
            if str(item.get("role") or "") != "user":
                continue
            request_id = str(item.get("dispatch_request_id") or "")
            if not request_id or request_id in request_ids_with_reply:
                continue
            text = str(item.get("body") or "")
            body = self._ports.direct_reply(text)
            failure = None  # History rebuild is static; never start another CLI call.
            if not body:
                continue
            rows.append(
                self._repository.message_row(
                    user_id=int(user_id),
                    role="assistant",
                    body=body,
                    created_at=_utc_now(),
                    request_id=request_id,
                    status="failed" if failure else "completed",
                    extra={
                        "kind": self._p.direct_kind,
                        **({"cli_execution": failure.receipt} if failure else {}),
                    },
                )
            )
            request_ids_with_reply.add(request_id)
            changed = True
        return changed

    def refresh_dispatcher_row(self, row: dict[str, Any], task: dict[str, Any]) -> bool:
        task_id = str(task.get("id") or row.get("task_id") or "")
        task_status = str(task.get("status") or "").strip()
        body = self.para_task_status_reply(task)
        patch = {
            "body": body,
            "status": "dispatch_unknown"
            if row.get("reconciliation_required")
            else task_status or str(row.get("status") or ""),
            "task_id": task_id,
            "task_status": task_status,
        }
        changed = False
        for key, value in patch.items():
            if value and row.get(key) != value:
                row[key] = value
                changed = True
        return changed

    def para_task_status_reply(self, task: dict[str, Any]) -> str:
        task_id = str(task.get("id") or "").strip()
        status = str(task.get("status") or "").strip()
        tool = self._p.display_tool
        subtasks = self.task_subtasks(task)
        total = len(subtasks)
        completed = sum(1 for item in subtasks if str(item.get("status") or "") == "completed")
        failed = sum(1 for item in subtasks if str(item.get("status") or "") == "failed")
        progress_values = [
            int(item.get("progress") or 0)
            for item in subtasks
            if isinstance(item.get("progress"), (int, float))
        ]
        progress = round(sum(progress_values) / len(progress_values)) if progress_values else 0
        if status in {"completed", "merged"}:
            head = f"Para 任务已完成，{tool} 执行结果已回传。"
        elif status in {"failed", "merge_conflict"} or failed:
            head = f"Para 任务需要处理，{tool} 错误或冲突信息已回传。"
        elif total:
            head = f"Para 任务运行中：{completed}/{total} 个子任务完成，进度 {progress}%。"
        else:
            head = f"Para 任务已创建，等待 {tool} 工作设备回传。"
        return f"{head}{(f'任务 ID：{task_id}' if task_id else '')}"

    def upsert_result_messages(
        self,
        *,
        user_id: int,
        dispatch_row: dict[str, Any],
        task: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> bool:
        changed = False
        task_id = str(task.get("id") or dispatch_row.get("task_id") or "")
        for subtask in self.task_subtasks(task):
            status = str(subtask.get("status") or "").strip()
            if status not in {"completed", "failed"}:
                continue
            body = self.result_body(task, subtask)
            if not body:
                continue
            subtask_id = str(subtask.get("id") or "")
            existing = next(
                (
                    item
                    for item in rows
                    if int(item.get("user_id") or 0) == int(user_id)
                    and str(item.get("kind") or "") == self._p.result_kind
                    and (str(item.get("task_id") or "") == task_id)
                    and (str(item.get("subtask_id") or "") == subtask_id)
                ),
                None,
            )
            if existing:
                patch = {
                    "body": body,
                    "status": status,
                    "task_status": str(task.get("status") or ""),
                    "device_name": str(subtask.get("device_name") or ""),
                }
                for key, value in patch.items():
                    if value and existing.get(key) != value:
                        existing[key] = value
                        changed = True
                continue
            rows.append(
                self._repository.message_row(
                    user_id=int(user_id),
                    role="assistant",
                    body=body,
                    created_at=str(subtask.get("completed_at") or _utc_now()),
                    request_id=str(dispatch_row.get("dispatch_request_id") or ""),
                    status=status,
                    extra={
                        "kind": self._p.result_kind,
                        "task_id": task_id,
                        "task_status": str(task.get("status") or ""),
                        "subtask_id": subtask_id,
                        "device_name": str(subtask.get("device_name") or ""),
                    },
                )
            )
            changed = True
        return changed

    def task_subtasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        subtasks = _coerce_list(task.get("subTasks")) or _coerce_list(task.get("subtasks"))
        return [item for item in subtasks if isinstance(item, dict)]

    def result_body(self, task: dict[str, Any], subtask: dict[str, Any]) -> str:
        logs = [
            str(log.get("content") or "").strip()
            for log in _coerce_list(subtask.get("logs"))
            if isinstance(log, dict) and str(log.get("content") or "").strip()
        ]
        meaningful = [item for item in logs if not self.is_dispatcher_log(item)]
        tail = self.dedupe_log_tail(meaningful or logs)
        status = str(subtask.get("status") or "").strip()
        tool = self._p.display_tool
        device_name = str(subtask.get("device_name") or subtask.get("device_id") or "").strip()
        title = str(subtask.get("title") or task.get("title") or "").strip()
        prefix = f"{device_name} / {title}".strip(" /")
        if tail:
            return f"{prefix}\n\n{tail}".strip()
        if status == "completed":
            return f"{prefix}\n\n{tool} 已完成该子任务。".strip()
        if status == "failed":
            last_error = str(subtask.get("last_error") or "").strip()
            return f"{prefix}\n\n{tool} 执行失败。{last_error}".strip()
        return ""

    def is_dispatcher_log(self, content: str) -> bool:
        prefixes = ("子任务「", "子任务未派发", "链路不可用", "设备连接已断开", "手动")
        return content.startswith(prefixes)

    def dedupe_log_tail(self, logs: list[str], *, max_items: int = 5, max_chars: int = 4000) -> str:
        seen: set[str] = set()
        unique: list[str] = []
        for item in logs:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return "\n\n".join(unique[-max_items:])[-max_chars:].strip()
