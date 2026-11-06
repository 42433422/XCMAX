"""In-memory durable task ledger: queue, lease, approval, retry, and idempotency.

The ledger is the acceptance runtime for A19–A30. ``dump`` / ``load`` is the
persistence boundary a process restart crosses. Business modules do not assign
``status`` directly; they call the methods below.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from app.domain.task_lifecycle.machine import (
    DEFAULT_MAX_ATTEMPTS,
    NON_RETRYABLE_CODES,
    TERMINAL,
    retry_delay_seconds,
    transition_allowed,
)

_SOURCES = frozenset({"agent", "workflow", "employee", "ticket"})
_ID_PREFIX = "task_"
_PAYLOAD_TEXT_LIMIT = 8000
_NAME_LIMIT = 160
_DESCRIPTION_LIMIT = 4000


class TaskLifecycleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass
class _Task:
    task_id: str
    tenant_id: str
    user_id: str
    employee_id: str
    source_type: str
    name: str
    description: str
    status: str
    priority: int
    idempotency_key: str
    attempt_count: int
    max_attempts: int
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    approval_id: str = ""
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    timeout_at: str = ""
    next_retry_at: str = ""
    worker_id: str = ""
    lease_expires_at: str = ""
    version: int = 1
    progress: int = 0
    checkpoint: dict[str, Any] = field(default_factory=dict)
    needs_verification: bool = False
    cancel_reason: str = ""
    heartbeat_at: str = ""
    queued_at: str = ""
    available_at: str = ""
    timeout_seconds: float = 0.0
    parent_id: str = ""
    children: list[str] = field(default_factory=list)
    open_effects: list[str] = field(default_factory=list)
    applied_effects: list[str] = field(default_factory=list)
    deliveries: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    protected: bool = False
    completion_events: int = 0
    notifications: list[dict[str, Any]] = field(default_factory=list)
    fingerprint: str = ""
    seq: int = 0


class TaskLedger:
    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        max_running: int = 5,
        aging_seconds: float = 3600.0,
        lease_seconds: float = 30.0,
        approval_timeout_seconds: float = 3600.0,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        jitter_ratio: float = 0.2,
        idempotency_ttl_seconds: float | None = None,
        approvers: set[str] | None = None,
        admins: set[str] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self.max_running = max(1, int(max_running))
        self.aging_seconds = max(0.001, float(aging_seconds))
        self.lease_seconds = max(0.1, float(lease_seconds))
        self.approval_timeout_seconds = max(0.1, float(approval_timeout_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.jitter_ratio = max(0.0, float(jitter_ratio))
        self.idempotency_ttl_seconds = idempotency_ttl_seconds
        self.approvers = set(approvers or set())
        self.admins = set(admins or set())
        self._tasks: dict[str, _Task] = {}
        self._idem: dict[tuple[str, str], tuple[str, str]] = {}
        self._sequence = 0
        self._lock = threading.RLock()

    def now(self) -> datetime:
        moment = self._now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(UTC)

    def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        employee_id: str,
        source_type: str,
        name: str,
        description: str = "",
        payload: dict[str, Any] | None = None,
        priority: int = 100,
        idempotency_key: str = "",
        required: tuple[str, ...] = (),
        timeout_seconds: float = 0.0,
        max_attempts: int | None = None,
        auto_queue: bool = False,
    ) -> dict[str, Any]:
        body = self._validate_payload(payload, required)
        title = str(name or "").strip()
        if not title or len(title) > _NAME_LIMIT:
            raise TaskLifecycleError("invalid_params", "任务名称无效")
        text = str(description or "")
        if len(text) > _DESCRIPTION_LIMIT:
            raise TaskLifecycleError("invalid_params", "任务描述超长")
        if source_type not in _SOURCES:
            raise TaskLifecycleError("invalid_params", "任务来源无效")
        if not str(tenant_id or "").strip() or not str(user_id or "").strip():
            raise TaskLifecycleError("invalid_params", "任务必须归属租户和用户")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise TaskLifecycleError("invalid_params", "优先级必须是整数")
        fingerprint = _fingerprint(title, source_type, body)
        key = str(idempotency_key or "").strip()
        with self._lock:
            if key:
                reused = self._reuse_idem(str(tenant_id), key, fingerprint)
                if reused is not None:
                    return self._view(reused)
            moment = self.now()
            self._sequence += 1
            task = _Task(
                task_id=_ID_PREFIX + uuid.uuid4().hex,
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                employee_id=str(employee_id or ""),
                source_type=source_type,
                name=title,
                description=text,
                status="created",
                priority=priority,
                idempotency_key=key,
                attempt_count=0,
                max_attempts=self.max_attempts
                if max_attempts is None
                else max(1, int(max_attempts)),
                payload=body,
                created_at=_iso(moment),
                timeout_seconds=max(0.0, float(timeout_seconds)),
                fingerprint=fingerprint,
                seq=self._sequence,
            )
            self._event(task, "", "created", actor=task.user_id, reason="create")
            self._tasks[task.task_id] = task
            if key:
                self._idem[(task.tenant_id, key)] = (task.task_id, task.created_at)
            if auto_queue:
                self._enter_queue(task, actor=task.user_id, reason="create")
            return self._view(task)

    def enqueue(self, task_id: str, *, actor: str = "") -> dict[str, Any]:
        with self._lock:
            task = self._require(task_id)
            self._enter_queue(task, actor=actor or task.user_id, reason="enqueue")
            return self._view(task)

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._release_expired_leases()
            if self._running_count() >= self.max_running:
                return None
            moment = self.now()
            eligible = [
                task
                for task in self._tasks.values()
                if task.status == "queued"
                and not task.needs_verification
                and _parse(task.available_at) <= moment
            ]
            if not eligible:
                return None
            eligible.sort(key=lambda task: self._rank(task, moment))
            return self._start(eligible[0], worker_id)

    def claim_message(self, task_id: str, worker_id: str, message_id: str) -> dict[str, Any]:
        """Consume one queue delivery. A repeated message does not start another attempt."""
        with self._lock:
            task = self._require(task_id)
            marker = str(message_id or "")
            if not marker:
                raise TaskLifecycleError("invalid_params", "投递标识不能为空")
            if marker in task.deliveries:
                return self._view(task)
            if task.status != "queued":
                task.deliveries.append(marker)
                return self._view(task)
            task.deliveries.append(marker)
            self._release_expired_leases()
            if self._running_count() >= self.max_running:
                task.deliveries.pop()
                raise TaskLifecycleError("capacity", "并发执行数已满")
            return self._start(task, worker_id) or self._view(task)

    def heartbeat(self, task_id: str, worker_id: str) -> dict[str, Any]:
        with self._lock:
            task = self._owned_running(task_id, worker_id)
            moment = self.now()
            task.heartbeat_at = _iso(moment)
            task.lease_expires_at = _iso(moment + timedelta(seconds=self.lease_seconds))
            return self._view(task)

    def report_progress(
        self,
        task_id: str,
        worker_id: str,
        *,
        progress: int,
        checkpoint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            task = self._owned_running(task_id, worker_id)
            task.progress = max(0, min(100, int(progress)))
            if checkpoint:
                task.checkpoint.update(deepcopy(checkpoint))
            if task.attempts:
                task.attempts[-1]["progress"] = task.progress
            return self._view(task)

    def succeed(self, task_id: str, worker_id: str, result: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            task = self._require(task_id)
            if task.status == "succeeded":
                return self._view(task)
            self._require_live_owner(task, worker_id)
            if not transition_allowed(task.status, "succeeded"):
                raise TaskLifecycleError("illegal_transition", f"不能从 {task.status} 完成任务")
            task.result = deepcopy(result)
            task.completed_at = _iso(self.now())
            task.progress = 100
            self._close_attempt(task, "succeeded", "")
            self._move(task, "succeeded", actor=worker_id, reason="completed")
            if task.completion_events == 0:
                task.completion_events = 1
                task.notifications.append(
                    {"task_id": task.task_id, "status": "succeeded", "at": task.completed_at}
                )
            return self._view(task)

    def fail(
        self,
        task_id: str,
        worker_id: str,
        *,
        code: str,
        kind: str,
        message: str,
        stage: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            task = self._require(task_id)
            if task.status in TERMINAL:
                raise TaskLifecycleError("illegal_transition", f"终态 {task.status} 不能再失败")
            self._require_live_owner(task, worker_id)
            return self._fail_locked(
                task,
                code=code,
                kind=kind,
                message=message,
                stage=stage,
                actor=worker_id,
            )

    def cancel(self, task_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        with self._lock:
            task = self._require(task_id)
            self._authorize_actor(task, actor)
            if task.status == "cancelled":
                return self._view(task)
            if task.status in TERMINAL or not transition_allowed(task.status, "cancelled"):
                raise TaskLifecycleError("illegal_transition", f"不能取消 {task.status}")
            task.cancel_reason = str(reason or "")
            self._close_attempt(task, "cancelled", reason)
            self._move(task, "cancelled", actor=actor, reason=reason or "cancel")
            self._stop_children(task, actor=actor, reason="parent_cancelled")
            return self._view(task)

    def request_approval(
        self,
        task_id: str,
        worker_id: str,
        *,
        summary: str,
        risk: str,
    ) -> dict[str, Any]:
        with self._lock:
            task = self._owned_running(task_id, worker_id)
            task.checkpoint.setdefault("progress", task.progress)
            task.protected = True
            self._close_attempt(task, "waiting_approval", "")
            approval_id = f"appr_{uuid.uuid4().hex}"
            task.approval_id = approval_id
            moment = _iso(self.now())
            task.approvals.append(
                {
                    "approval_id": approval_id,
                    "task_id": task.task_id,
                    "summary": summary,
                    "risk": risk,
                    "params": deepcopy(task.payload),
                    "applicant": task.user_id,
                    "status": "pending",
                    "requested_at": moment,
                    "decided_at": "",
                    "actor": "",
                    "reason": "",
                }
            )
            self._move(task, "waiting_approval", actor=worker_id, reason="approval_required")
            task.worker_id = ""
            task.lease_expires_at = ""
            return self._view(task)

    def approve(self, task_id: str, *, actor: str) -> dict[str, Any]:
        with self._lock:
            task = self._require(task_id)
            if actor not in self.approvers:
                raise TaskLifecycleError("permission_denied", "无权审批")
            approval = self._pending_approval(task)
            if approval["status"] != "pending":
                return self._view(task)
            if task.status == "queued" and approval["status"] == "approved":
                return self._view(task)
            approval["status"] = "approved"
            approval["actor"] = actor
            approval["decided_at"] = _iso(self.now())
            self._move(task, "queued", actor=actor, reason="approved")
            self._enter_queue(task, actor=actor, reason="approved_resume", already_queued=True)
            task.protected = False
            return self._view(task)

    def reject(self, task_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        with self._lock:
            task = self._require(task_id)
            if actor not in self.approvers:
                raise TaskLifecycleError("permission_denied", "无权审批")
            if task.status == "rejected":
                return self._view(task)
            approval = self._pending_approval(task)
            if approval["status"] != "pending":
                return self._view(task)
            approval["status"] = "rejected"
            approval["actor"] = actor
            approval["reason"] = str(reason or "")
            approval["decided_at"] = _iso(self.now())
            task.error = {
                "code": "approval_rejected",
                "kind": "business",
                "message": str(reason or ""),
                "stage": "approval",
            }
            self._move(task, "rejected", actor=actor, reason=reason or "rejected")
            return self._view(task)

    def retry(self, task_id: str) -> dict[str, Any]:
        """Requeue a timed-out attempt when the old worker is gone and effects are closed."""
        with self._lock:
            task = self._require(task_id)
            if task.needs_verification or task.open_effects:
                raise TaskLifecycleError("needs_verification", "执行结果未核验，不能重试")
            if task.status != "timed_out":
                raise TaskLifecycleError(
                    "illegal_transition", f"不能从 {task.status} 按超时策略重试"
                )
            if task.attempt_count >= task.max_attempts:
                raise TaskLifecycleError("retries_exhausted", "已达到最大尝试次数")
            delay = self._delay(task, max(1, task.attempt_count))
            moment = self.now() + timedelta(seconds=delay)
            task.next_retry_at = _iso(moment)
            task.available_at = task.next_retry_at
            self._move(task, "queued", actor="scheduler", reason="timeout_retry", retryable=True)
            return self._view(task)

    def call_tool(self, task_id: str, worker_id: str, tool: str) -> dict[str, Any]:
        with self._lock:
            task = self._require(task_id)
            if task.status != "running" or task.protected:
                raise TaskLifecycleError("blocked", "当前状态不允许调用工具")
            self._require_owner(task, worker_id)
            allowed = task.payload.get("tools")
            if isinstance(allowed, list) and tool not in allowed:
                raise TaskLifecycleError("permission_denied", "工具不在授权范围")
            return {"tool": tool, "task_id": task.task_id, "attempt": task.attempt_count}

    def begin_effect(self, task_id: str, worker_id: str, key: str) -> str:
        with self._lock:
            task = self._owned_running(task_id, worker_id)
            if task.protected:
                raise TaskLifecycleError("blocked", "审批等待期间禁止副作用")
            marker = str(key or "")
            if marker in task.applied_effects:
                return "applied"
            if marker not in task.open_effects:
                task.open_effects.append(marker)
            return "opened"

    def finish_effect(self, task_id: str, worker_id: str, key: str) -> str:
        with self._lock:
            task = self._owned_running(task_id, worker_id)
            marker = str(key or "")
            if marker in task.applied_effects:
                return "applied"
            if marker in task.open_effects:
                task.open_effects.remove(marker)
            task.applied_effects.append(marker)
            return "applied"

    def write_file(self, task_id: str, worker_id: str, name: str, content: str) -> None:
        with self._lock:
            task = self._owned_running(task_id, worker_id)
            task.files[str(name)] = str(content)

    def read_file(self, task_id: str, tenant_id: str, name: str) -> str:
        with self._lock:
            task = self._visible(task_id, tenant_id)
            if name not in task.files:
                raise TaskLifecycleError("not_found", "文件不存在")
            return task.files[name]

    def add_child(self, parent_id: str, **kwargs: Any) -> dict[str, Any]:
        child = self.create(**kwargs)
        with self._lock:
            parent = self._require(parent_id)
            task = self._require(child["task_id"])
            task.parent_id = parent.task_id
            parent.children.append(task.task_id)
            return self._view(task)

    def tick(self) -> list[str]:
        """Apply approval timeouts, execution timeouts, and expired leases."""
        with self._lock:
            changed: list[str] = []
            moment = self.now()
            for task in list(self._tasks.values()):
                if task.status == "waiting_approval" and task.approvals:
                    requested = _parse(task.approvals[-1]["requested_at"])
                    if moment - requested >= timedelta(seconds=self.approval_timeout_seconds):
                        approval = task.approvals[-1]
                        if approval["status"] == "pending":
                            approval["status"] = "rejected"
                            approval["actor"] = "scheduler"
                            approval["reason"] = "approval_timeout"
                            approval["decided_at"] = _iso(moment)
                            task.error = {
                                "code": "approval_timeout",
                                "kind": "business",
                                "message": "审批超时，未默认批准",
                                "stage": "approval",
                            }
                            self._move(
                                task,
                                "rejected",
                                actor="scheduler",
                                reason="approval_timeout",
                            )
                            changed.append(task.task_id)
                elif (
                    task.status == "running"
                    and task.timeout_at
                    and _parse(task.timeout_at) <= moment
                ):
                    self._timeout_locked(task)
                    changed.append(task.task_id)
            changed.extend(self._release_expired_leases())
            return changed

    def read(self, task_id: str, *, tenant_id: str) -> dict[str, Any]:
        with self._lock:
            return self._view(self._visible(task_id, tenant_id))

    def get(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            return self._view(self._require(task_id))

    def list_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = [task for task in self._tasks.values() if task.tenant_id == tenant_id]
            rows.sort(key=lambda task: task.created_at)
            return [self._view(task) for task in rows]

    def scheduler_status(self, task_id: str) -> str:
        return str(self.get(task_id)["status"])

    def ui_status(self, task_id: str) -> str:
        return str(self.get(task_id)["status"])

    def mutate_payload(
        self, task_id: str, *, actor: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            task = self._require(task_id)
            if task.status in {"rejected", "waiting_approval", *TERMINAL}:
                raise TaskLifecycleError("blocked", "不能绕过审批修改参数")
            self._authorize_actor(task, actor)
            task.payload = self._validate_payload(payload, ())
            return self._view(task)

    def dump(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tasks": [asdict(task) for task in self._tasks.values()],
                "idem": [
                    {"tenant_id": tenant, "key": key, "task_id": task_id, "created_at": created}
                    for (tenant, key), (task_id, created) in self._idem.items()
                ],
            }

    def load(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._tasks = {}
            self._idem = {}
            for raw in snapshot.get("tasks") or []:
                task = _Task(**raw)
                self._tasks[task.task_id] = task
            self._sequence = max((task.seq for task in self._tasks.values()), default=0)
            for row in snapshot.get("idem") or []:
                self._idem[(row["tenant_id"], row["key"])] = (row["task_id"], row["created_at"])

    def start(self) -> list[str]:
        """Scheduler boot: classify leftover running work without replaying effects."""
        with self._lock:
            return self._release_expired_leases(force=True)

    def _start(self, task: _Task, worker_id: str) -> dict[str, Any]:
        if task.status != "queued":
            return self._view(task)
        moment = self.now()
        self._move(task, "running", actor=worker_id, reason="claim")
        task.worker_id = str(worker_id)
        task.attempt_count += 1
        task.started_at = task.started_at or _iso(moment)
        task.heartbeat_at = _iso(moment)
        task.lease_expires_at = _iso(moment + timedelta(seconds=self.lease_seconds))
        task.next_retry_at = ""
        if task.timeout_seconds > 0:
            task.timeout_at = _iso(moment + timedelta(seconds=task.timeout_seconds))
        attempt_id = f"attempt_{uuid.uuid4().hex}"
        task.attempts.append(
            {
                "attempt_id": attempt_id,
                "status": "running",
                "worker_id": task.worker_id,
                "started_at": _iso(moment),
                "finished_at": "",
                "error": "",
                "progress": task.progress,
            }
        )
        return self._view(task)

    def _fail_locked(
        self,
        task: _Task,
        *,
        code: str,
        kind: str,
        message: str,
        stage: str,
        actor: str,
    ) -> dict[str, Any]:
        if not transition_allowed(task.status, "failed"):
            raise TaskLifecycleError("illegal_transition", f"不能从 {task.status} 进入 failed")
        normalized_kind = kind if kind in {"business", "system"} else "system"
        task.error = {
            "code": code,
            "kind": normalized_kind,
            "message": message,
            "stage": stage,
        }
        self._close_attempt(task, "failed", message)
        self._move(task, "failed", actor=actor, reason=code)
        retryable = (
            normalized_kind == "system"
            and code not in NON_RETRYABLE_CODES
            and task.attempt_count < task.max_attempts
            and task.status == "failed"
        )
        if retryable and transition_allowed("failed", "queued", retryable=True):
            delay = self._delay(task, task.attempt_count)
            moment = self.now() + timedelta(seconds=delay)
            task.next_retry_at = _iso(moment)
            task.available_at = task.next_retry_at
            self._move(task, "queued", actor="scheduler", reason="retry", retryable=True)
            task.worker_id = ""
            task.lease_expires_at = ""
            task.queued_at = _iso(self.now())
        return self._view(task)

    def _timeout_locked(self, task: _Task) -> None:
        if not transition_allowed(task.status, "timed_out"):
            return
        task.error = {
            "code": "timed_out",
            "kind": "system",
            "message": "执行超时",
            "stage": task.attempts[-1]["status"] if task.attempts else "running",
        }
        self._close_attempt(task, "timed_out", "timed_out")
        self._move(task, "timed_out", actor="scheduler", reason="timeout")
        task.worker_id = ""
        task.lease_expires_at = ""
        self._stop_children(task, actor="scheduler", reason="parent_timed_out")
        if task.open_effects:
            task.needs_verification = True

    def _release_expired_leases(self, *, force: bool = False) -> list[str]:
        moment = self.now()
        changed: list[str] = []
        for task in list(self._tasks.values()):
            if task.status != "running" or task.needs_verification:
                continue
            expired = force or (
                bool(task.lease_expires_at) and _parse(task.lease_expires_at) <= moment
            )
            if not expired:
                continue
            if task.open_effects:
                task.needs_verification = True
                task.worker_id = ""
                task.lease_expires_at = ""
                self._event(
                    task,
                    "running",
                    "running",
                    actor="scheduler",
                    reason="needs_verification",
                )
            else:
                self._close_attempt(task, "interrupted", "lease_expired")
                if task.attempt_count > 0:
                    task.attempt_count -= 1
                task.worker_id = ""
                task.lease_expires_at = ""
                task.heartbeat_at = ""
                task.status = "queued"
                task.version += 1
                moment_text = _iso(moment)
                task.queued_at = moment_text
                task.available_at = moment_text
                task.next_retry_at = ""
                self._event(task, "running", "queued", actor="scheduler", reason="lease_reclaimed")
            changed.append(task.task_id)
        return changed

    def _stop_children(self, task: _Task, *, actor: str, reason: str) -> None:
        for child_id in list(task.children):
            child = self._tasks.get(child_id)
            if child is None or child.status in TERMINAL:
                continue
            if transition_allowed(child.status, "cancelled"):
                child.cancel_reason = reason
                self._close_attempt(child, "cancelled", reason)
                self._move(child, "cancelled", actor=actor, reason=reason)

    def _enter_queue(
        self,
        task: _Task,
        *,
        actor: str,
        reason: str,
        already_queued: bool = False,
    ) -> None:
        if task.status == "queued" and already_queued:
            moment = _iso(self.now())
            task.queued_at = moment
            task.available_at = task.next_retry_at or moment
            task.worker_id = ""
            return
        if task.status != "created":
            raise TaskLifecycleError("illegal_transition", f"不能从 {task.status} 入队")
        self._move(task, "queued", actor=actor, reason=reason)
        moment = _iso(self.now())
        task.queued_at = moment
        task.available_at = moment

    def _move(
        self,
        task: _Task,
        target: str,
        *,
        actor: str,
        reason: str,
        retryable: bool = False,
    ) -> None:
        current = task.status
        if not transition_allowed(current, target, retryable=retryable):
            raise TaskLifecycleError("illegal_transition", f"非法转换 {current} → {target}")
        task.status = target
        task.version += 1
        if target in TERMINAL:
            task.completed_at = task.completed_at or _iso(self.now())
            task.worker_id = ""
            task.lease_expires_at = ""
            task.protected = False
        self._event(task, current, target, actor=actor, reason=reason)

    def _event(self, task: _Task, current: str, target: str, *, actor: str, reason: str) -> None:
        task.events.append(
            {
                "at": _iso(self.now()),
                "actor": actor,
                "from": current,
                "to": target,
                "reason": reason,
                "version": task.version,
            }
        )

    def _close_attempt(self, task: _Task, status: str, error: str) -> None:
        if not task.attempts:
            return
        current = task.attempts[-1]
        if current["status"] != "running":
            return
        current["status"] = status
        current["finished_at"] = _iso(self.now())
        current["error"] = error

    def _owned_running(self, task_id: str, worker_id: str) -> _Task:
        task = self._require(task_id)
        if task.status != "running":
            raise TaskLifecycleError("illegal_transition", f"任务不在执行中: {task.status}")
        self._require_owner(task, worker_id)
        if task.lease_expires_at and _parse(task.lease_expires_at) <= self.now():
            raise TaskLifecycleError("lease_expired", "执行租约已过期")
        return task

    def _require_owner(self, task: _Task, worker_id: str) -> None:
        if task.worker_id != worker_id:
            raise TaskLifecycleError("lease_mismatch", "执行者与租约不一致")

    def _require_live_owner(self, task: _Task, worker_id: str) -> None:
        self._require_owner(task, worker_id)
        if task.lease_expires_at and _parse(task.lease_expires_at) <= self.now():
            raise TaskLifecycleError("lease_expired", "执行租约已过期")

    def _authorize_actor(self, task: _Task, actor: str) -> None:
        if actor != task.user_id and actor not in self.admins:
            raise TaskLifecycleError("permission_denied", "无权操作该任务")

    def _pending_approval(self, task: _Task) -> dict[str, Any]:
        if not task.approvals:
            raise TaskLifecycleError("not_found", "没有审批记录")
        return task.approvals[-1]

    def _visible(self, task_id: str, tenant_id: str) -> _Task:
        task = self._require(task_id)
        if task.tenant_id != tenant_id:
            raise TaskLifecycleError("not_found", "任务不存在")
        return task

    def _require(self, task_id: str) -> _Task:
        task = self._tasks.get(str(task_id or ""))
        if task is None:
            raise TaskLifecycleError("not_found", "任务不存在")
        return task

    def _running_count(self) -> int:
        return sum(
            1
            for task in self._tasks.values()
            if task.status == "running" and not task.needs_verification
        )

    def _rank(self, task: _Task, moment: datetime) -> tuple[float, str, str]:
        waited = max(0.0, (moment - _parse(task.queued_at or task.created_at)).total_seconds())
        aged = float(task.priority) - (waited / self.aging_seconds)
        return (aged, task.created_at, f"{task.seq:08d}", task.task_id)

    def _delay(self, task: _Task, retry_number: int) -> float:
        base = retry_delay_seconds(retry_number)
        if self.jitter_ratio <= 0:
            return base
        digest = hashlib.sha256(f"{task.task_id}:{retry_number}".encode()).digest()
        unit = int.from_bytes(digest[:2], "big") / 65535
        factor = 1 + (unit * 2 - 1) * self.jitter_ratio
        return base * factor

    def _reuse_idem(self, tenant_id: str, key: str, fingerprint: str) -> _Task | None:
        found = self._idem.get((tenant_id, key))
        if found is None:
            return None
        task_id, created_at = found
        if self.idempotency_ttl_seconds is not None:
            age = self.now() - _parse(created_at)
            if age.total_seconds() > float(self.idempotency_ttl_seconds):
                self._idem.pop((tenant_id, key), None)
                return None
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.fingerprint != fingerprint:
            raise TaskLifecycleError("idempotency_conflict", "幂等键已绑定不同任务内容")
        return task

    def _validate_payload(
        self,
        payload: dict[str, Any] | None,
        required: tuple[str, ...],
    ) -> dict[str, Any]:
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise TaskLifecycleError("invalid_params", "payload 必须是对象")
        missing = [key for key in required if key not in payload]
        if missing:
            raise TaskLifecycleError("invalid_params", f"缺少必要参数: {', '.join(missing)}")
        for value in payload.values():
            if isinstance(value, str) and len(value) > _PAYLOAD_TEXT_LIMIT:
                raise TaskLifecycleError("invalid_params", "参数内容超长")
            if not isinstance(value, (str, int, float, bool, type(None), dict, list)):
                raise TaskLifecycleError("invalid_params", "参数类型无效")
        return deepcopy(payload)

    def _view(self, task: _Task) -> dict[str, Any]:
        data = asdict(task)
        data.pop("fingerprint", None)
        return data


def _fingerprint(name: str, source_type: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {"name": name, "source": source_type, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()
