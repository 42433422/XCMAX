"""``WorkflowPlanStore`` — 动态工作流计划的数据库持久化与跨会话恢复。

工作流规划产出的 ``PlanGraph``（含节点/条件边/待办）序列化后按 ``plan_id`` 落库到
``workflow_plans`` 表。配合 DB 化的 checkpoint（``DatabaseWorkflowCheckpointer``），
进程重启或用户换会话后，可凭 ``plan_id`` 载入计划并从最新 checkpoint 续跑，实现
真正的长任务跨会话续跑。

与 ``DatabaseWorkflowCheckpointer`` 一致的会话模式：每次操作独立开会话、惰性建表
（幂等 ``create_all checkfirst``）、保存失败仅告警不阻断主流程。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application.workflow.types import PlanGraph, plan_from_dict, plan_to_dict
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 生命周期状态常量。
STATUS_RUNNING = "running"
STATUS_PENDING = "pending_awaiting"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# 可视为「待续跑」的终态/非终态集合。
_ACTIVE_STATUSES = {STATUS_RUNNING, STATUS_PENDING}


def _dump_json(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


class WorkflowPlanStore:
    """持久化动态工作流计划，支持按计划/用户查询与状态流转。"""

    def __init__(self, session_factory=None) -> None:
        # 测试可注入自定义 session_factory（返回一个 SQLAlchemy Session）
        self._session_factory = session_factory
        self._schema_ensured = False

    def _ensure_schema(self, session) -> None:
        if self._schema_ensured:
            return
        try:
            from app.db.base import Base
            from app.db.models.workflow import WorkflowPlan

            Base.metadata.create_all(
                bind=session.get_bind(), tables=[WorkflowPlan.__table__], checkfirst=True
            )
        except Exception:  # noqa: BLE001 - 建表失败不阻断主流程，仅告警
            logger.warning("workflow_plans 建表失败，计划持久化降级", exc_info=True)
        finally:
            self._schema_ensured = True

    def _get_session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from app.db import SessionLocal

        return SessionLocal()

    def save(
        self,
        *,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        status: str = STATUS_RUNNING,
        user_id: str | None = None,
        session_id: str | None = None,
        message: str | None = None,
    ) -> str:
        """按 ``plan.plan_id`` upsert 计划快照，返回 ``plan_id``。"""
        plan_id = plan.plan_id
        session = self._get_session()
        try:
            from sqlalchemy.exc import IntegrityError

            from app.db.models.workflow import WorkflowPlan

            self._ensure_schema(session)
            row = session.query(WorkflowPlan).filter(WorkflowPlan.plan_id == plan_id).first()
            if row is None:
                row = WorkflowPlan(plan_id=plan_id)
                session.add(row)
            row.session_id = session_id or row.session_id
            row.user_id = user_id or row.user_id
            row.intent = plan.intent or row.intent
            row.plan_json = _dump_json(plan_to_dict(plan))
            row.runtime_context = _dump_json(dict(runtime_context or {}))
            row.status = status
            if message is not None:
                row.message = message
            try:
                session.commit()
            except IntegrityError:
                # 并发 upsert 竞态：退避重查一次后更新。
                session.rollback()
                row = session.query(WorkflowPlan).filter(WorkflowPlan.plan_id == plan_id).first()
                if row is not None:
                    row.plan_json = _dump_json(plan_to_dict(plan))
                    row.runtime_context = _dump_json(dict(runtime_context or {}))
                    row.status = status
                    session.commit()
        except RECOVERABLE_ERRORS:
            session.rollback()
            logger.warning("workflow_plan 保存失败 plan=%s（主流程继续）", plan_id)
        finally:
            session.close()
        return plan_id

    def load(self, plan_id: str) -> dict[str, Any] | None:
        """按 ``plan_id`` 载入计划快照 dict；不存在返回 ``None``。"""
        session = self._get_session()
        try:
            from app.db.models.workflow import WorkflowPlan

            row = session.query(WorkflowPlan).filter(WorkflowPlan.plan_id == plan_id).first()
            return row.to_dict() if row is not None else None
        finally:
            session.close()

    def load_plan(self, plan_id: str) -> PlanGraph | None:
        """按 ``plan_id`` 载入并还原 ``PlanGraph``；不存在返回 ``None``。"""
        data = self.load(plan_id)
        if not data:
            return None
        return plan_from_dict(data.get("plan") or {})

    def list_active(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """列出某用户的可续跑计划（running / pending_awaiting），按最近更新倒序。"""
        session = self._get_session()
        try:
            from app.db.models.workflow import WorkflowPlan

            rows = (
                session.query(WorkflowPlan)
                .filter(
                    WorkflowPlan.user_id == user_id,
                    WorkflowPlan.status.in_(list(_ACTIVE_STATUSES)),
                )
                .order_by(WorkflowPlan.updated_at.desc())
                .limit(max(1, limit))
                .all()
            )
            return [row.to_dict() for row in rows]
        finally:
            session.close()

    def update_status(
        self, plan_id: str, status: str, message: str | None = None
    ) -> None:
        """更新计划终态/状态；计划不存在则忽略。"""
        session = self._get_session()
        try:
            from app.db.models.workflow import WorkflowPlan

            row = session.query(WorkflowPlan).filter(WorkflowPlan.plan_id == plan_id).first()
            if row is None:
                return
            row.status = status
            if message is not None:
                row.message = message
            session.commit()
        except RECOVERABLE_ERRORS:
            session.rollback()
            logger.warning("workflow_plan 状态更新失败 plan=%s", plan_id)
        finally:
            session.close()