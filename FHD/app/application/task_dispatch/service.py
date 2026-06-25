"""派工编排服务（TaskDispatchService）。

把 路由 → 建工单 → 派工(二级/三级) → 回收结果 → 状态流转 → 持久化 串成一条闭环，
并返回供小C"收口"的统一摘要。所有协作方均可注入，便于离线测试。

- 二级超级员工：``SuperEmployeeService.invoke``（Claude / Codex CLI 中继）。
- 三级平台员工：``execute_employee_task_local``（进程内 employee_runtime，同步执行）。

当前为同步派工：工单已持久化（可查询/可被未来的异步 worker 抽干），
但执行在请求线程内完成，便于小C在同一轮对话里收口汇报。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.application.task_dispatch.repository import WorkOrderRepository, get_work_order_repository
from app.application.task_dispatch.router import DispatchRouter, RoutingDecision
from app.application.task_dispatch.status import WorkOrderStatus
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_RESULT_JSON_CAP = 20000


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_int(user_id: Any) -> int:
    try:
        return int(str(user_id).strip())
    except (TypeError, ValueError):
        return 0


def _default_super_factory(assignee_id: str) -> Any:
    """超级员工 id → 对应 CLI 中继服务实例（claude / codex / cursor）。"""
    aid = str(assignee_id or "").lower()
    if "codex" in aid:
        from app.application.codex_super_employee_service import CodexSuperEmployeeService

        return CodexSuperEmployeeService()
    if "cursor" in aid:
        from app.application.cursor_super_employee_service import CursorSuperEmployeeService

        return CursorSuperEmployeeService()
    from app.application.claude_super_employee_service import ClaudeSuperEmployeeService

    return ClaudeSuperEmployeeService()


def _default_platform_executor(employee_id: str, task: str, *, user_id: int = 0) -> dict[str, Any]:
    from app.application.employee_runtime.executor import execute_employee_task_local

    return execute_employee_task_local(employee_id, task, user_id=user_id)


class TaskDispatchService:
    def __init__(
        self,
        *,
        repository: WorkOrderRepository | None = None,
        router: DispatchRouter | None = None,
        super_employee_factory: Callable[[str], Any] | None = None,
        platform_executor: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._repo = repository or get_work_order_repository()
        self._router = router or DispatchRouter()
        self._super_factory = super_employee_factory or _default_super_factory
        self._platform_executor = platform_executor or _default_platform_executor

    # ── 对外入口 ────────────────────────────────────────────────────────
    def route(self, message: str, context: dict[str, Any] | None = None) -> RoutingDecision | None:
        return self._router.route(message, context)

    def handle_chat_dispatch(
        self, *, user_id: str, message: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """聊天主链路入口：能派则**入队**（异步 worker 执行），否则 None 让普通流程接管。

        入队后立即返回"已受理"，不阻塞对话；执行结果由后台 worker 写回工单，
        并（tier-2）回流 AI 交流圈。
        """
        decision = self.route(message, context)
        if decision is None:
            return None
        record = self.enqueue(decision, message=message, requester_user_id=user_id)
        _notify_worker()
        return {
            "work_order": record,
            "status": record.get("status"),
            "queued": True,
            "ok": False,
            "result_summary": (
                f"已派工给「{decision.assignee_name}」，正在后台执行，"
                "完成后结果会回到 AI 交流圈，也可按工单号查询进度。"
            ),
        }

    def list_pending(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """待执行工单（pending/dispatched）。供 worker 抽干。"""
        return self._repo.list_pending(limit=limit)

    def enqueue(
        self, decision: RoutingDecision, *, message: str, requester_user_id: str
    ) -> dict[str, Any]:
        """落一张 pending 工单（不执行）。worker 或 :meth:`dispatch` 负责抽干。"""
        return self._repo.create(
            work_order_id=uuid.uuid4().hex,
            requester="xiaoc",
            requester_user_id=str(requester_user_id),
            assignee_tier=decision.assignee_tier,
            assignee_id=decision.assignee_id,
            assignee_name=decision.assignee_name,
            title=decision.title or message[:40],
            instruction=message,
            status=WorkOrderStatus.PENDING.value,
            dispatch_mode=decision.dispatch_mode,
        )

    def dispatch(
        self,
        decision: RoutingDecision,
        *,
        message: str,
        requester_user_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """同步派工：入队后立刻执行。供测试与需要同轮收口的程序化调用。"""
        record = self.enqueue(decision, message=message, requester_user_id=requester_user_id)
        result = self.execute_work_order(record["work_order_id"])
        return result or {
            "work_order": record,
            "status": record.get("status"),
            "ok": False,
            "result_summary": "工单已入队但执行未返回。",
            "raw": {},
        }

    def execute_work_order(
        self, work_order_id: str, *, max_attempts: int = 2
    ) -> dict[str, Any] | None:
        """抽干一张工单：认领→执行(异常重试)→分类→落库→(tier-2)回流交流圈。

        幂等：仅认领 pending/dispatched 的工单；已 running/终态直接返回现状，避免重复执行。
        """
        record = self._repo.get(work_order_id)
        if record is None:
            return None
        status = record.get("status")
        if status not in (WorkOrderStatus.PENDING.value, WorkOrderStatus.DISPATCHED.value):
            return {
                "work_order": record,
                "status": status,
                "ok": status == WorkOrderStatus.SUCCEEDED.value,
                "result_summary": record.get("result_summary") or "",
                "raw": {},
            }

        decision = RoutingDecision(
            assignee_tier=record["assignee_tier"],
            assignee_id=record["assignee_id"],
            assignee_name=record.get("assignee_name") or record["assignee_id"],
            title=record.get("title") or "",
            reason="from-queue",
            dispatch_mode=record.get("dispatch_mode") or "auto",
        )
        message = record["instruction"]
        requester_user_id = record["requester_user_id"]
        self._repo.update(
            work_order_id, status=WorkOrderStatus.RUNNING.value, dispatched_at=_utc_now()
        )

        raw: dict[str, Any] = {}
        result_status = WorkOrderStatus.FAILED.value
        summary = ""
        last_exc: Exception | None = None
        for attempt in range(1, max(1, max_attempts) + 1):
            try:
                if decision.assignee_tier == "super":
                    raw = self._dispatch_super(
                        decision, message, requester_user_id, conversation_id=work_order_id
                    )
                else:
                    raw = self._dispatch_platform(decision, message, requester_user_id)
                result_status, summary = self._classify(decision.assignee_tier, raw)
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 — 执行失败落 failed 工单，可重试，不冒泡
                last_exc = exc
                logger.exception(
                    "派工执行异常 work_order=%s attempt=%s/%s",
                    work_order_id,
                    attempt,
                    max_attempts,
                )
        if last_exc is not None:
            raw = {"error": str(last_exc)}
            result_status = WorkOrderStatus.FAILED.value
            summary = f"派给「{decision.assignee_name}」执行时出错：{last_exc}"

        terminal = result_status in (WorkOrderStatus.SUCCEEDED.value, WorkOrderStatus.FAILED.value)
        self._repo.update(
            work_order_id,
            status=result_status,
            result_summary=summary,
            result_json=json.dumps(raw, ensure_ascii=False, default=str)[:_RESULT_JSON_CAP],
            request_id=self._request_id(raw),
            error=summary if result_status == WorkOrderStatus.FAILED.value else None,
            completed_at=_utc_now() if terminal else None,
        )
        record = self._repo.get(work_order_id) or {}
        # 结果回流 AI 交流圈：仅 tier-2（tier-3 由 EmployeeAgent.run 自身已发帖，避免重复）。
        if terminal and decision.assignee_tier == "super":
            self._post_to_circle(record, success=result_status == WorkOrderStatus.SUCCEEDED.value)
        return {
            "work_order": record,
            "result_summary": summary,
            "status": result_status,
            "ok": result_status == WorkOrderStatus.SUCCEEDED.value,
            "raw": raw,
        }

    # ── 各层派工 ────────────────────────────────────────────────────────
    def _dispatch_super(
        self,
        decision: RoutingDecision,
        message: str,
        requester_user_id: str,
        *,
        conversation_id: str = "",
    ) -> dict[str, Any]:
        service = self._super_factory(decision.assignee_id)
        return service.invoke(
            user_id=_as_int(requester_user_id),
            message=message,
            context={
                "source": "xiaoc_dispatch",
                "dispatch_mode": decision.dispatch_mode,
                # 每工单一独立会话/工作区（隔离），避免并发派工串台。
                "conversation_id": conversation_id,
            },
        )

    def _dispatch_platform(
        self, decision: RoutingDecision, message: str, requester_user_id: str
    ) -> dict[str, Any]:
        return self._platform_executor(
            decision.assignee_id, message, user_id=_as_int(requester_user_id)
        )

    # ── 结果归类 + 摘要 ─────────────────────────────────────────────────
    def _classify(self, tier: str, raw: dict[str, Any]) -> tuple[str, str]:
        if tier == "super":
            return self._classify_super(raw)
        return self._classify_platform(raw)

    @staticmethod
    def _classify_super(raw: dict[str, Any]) -> tuple[str, str]:
        dispatch = (raw.get("dispatch") or {}) if isinstance(raw, dict) else {}
        status_text = str(dispatch.get("status") or "")
        body = ""
        assistant_msg = raw.get("assistant_message") if isinstance(raw, dict) else None
        if isinstance(assistant_msg, dict):
            body = str(assistant_msg.get("body") or "").strip()
        if status_text == "completed":
            return WorkOrderStatus.SUCCEEDED.value, body or "超级员工已完成并返回结果。"
        if dispatch.get("accepted") is True or status_text == "queued":
            return (
                WorkOrderStatus.RUNNING.value,
                body or "已派工给超级员工，正在执行，稍后回写结果。",
            )
        return WorkOrderStatus.FAILED.value, body or "超级员工派工未被接受。"

    @staticmethod
    def _classify_platform(raw: dict[str, Any]) -> tuple[str, str]:
        if not isinstance(raw, dict):
            return WorkOrderStatus.SUCCEEDED.value, str(raw)
        if raw.get("blocked_by_risk_gate"):
            return WorkOrderStatus.FAILED.value, "被风险门拦截，需审批后执行。"
        ok = bool(raw.get("success", True))
        result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        texts: list[str] = []
        for out in result.get("outputs") or []:
            if isinstance(out, dict) and out.get("output"):
                texts.append(str(out["output"]).strip())
        summary = "\n".join(t for t in texts if t) or str(result.get("summary") or "").strip()
        if not summary:
            summary = "员工已执行完成。" if ok else str(result.get("error") or "员工执行失败。")
        return (
            WorkOrderStatus.SUCCEEDED.value if ok else WorkOrderStatus.FAILED.value,
            summary,
        )

    @staticmethod
    def _request_id(raw: dict[str, Any]) -> str | None:
        if not isinstance(raw, dict):
            return None
        dispatch = raw.get("dispatch") or {}
        if isinstance(dispatch, dict) and dispatch.get("request_id"):
            return str(dispatch["request_id"])
        return None

    @staticmethod
    def _post_to_circle(record: dict[str, Any], *, success: bool) -> None:
        """工单收口回流 AI 交流圈（复用员工活动发帖）。"""
        try:
            from app.application.ai_circle_service import record_employee_activity

            record_employee_activity(
                str(record.get("assignee_id") or ""),
                success=success,
                task=str(record.get("title") or record.get("instruction") or ""),
                summary=str(record.get("result_summary") or ""),
            )
        except RECOVERABLE_ERRORS:
            logger.warning("工单结果回流交流圈失败（不阻断）", exc_info=True)


def _notify_worker() -> None:
    """唤醒后台 worker 立刻抽干新入队的工单（best-effort）。"""
    try:
        from app.application.task_dispatch.worker import notify_work_order_worker

        notify_work_order_worker()
    except RECOVERABLE_ERRORS:
        logger.debug("worker 通知跳过", exc_info=True)


_task_dispatch_service: TaskDispatchService | None = None


def get_task_dispatch_service() -> TaskDispatchService:
    global _task_dispatch_service
    if _task_dispatch_service is None:
        _task_dispatch_service = TaskDispatchService()
    return _task_dispatch_service
