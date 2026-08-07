"""WorkflowCheckpointer — Checkpoint + 断点续跑 + 重放（AI 时间旅行）。

对标 LangGraph checkpointer / replay：在工作流执行过程中按步记录运行时快照，
支持从任意 checkpoint 恢复执行（``resume``，不重复执行已完成节点）与只读回放
输出历史（``replay``，不真正再执行工具）。

- ``WorkflowCheckpointer``：纯内存存储（便于测试与短生命周期会话），不依赖数据库。
- ``DatabaseWorkflowCheckpointer``：把快照持久化到 ``workflow_checkpoints`` 表，
  支持跨进程断点续跑与重放；保存失败时降级为不阻断工作流（仅告警）。
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class WorkflowCheckpointer:
    """以 ``plan_id`` 为命名空间、``checkpoint_id`` 为键的运行时快照存储。

    快照内容：``runtime_context``（深层拷贝）、``executed_nodes``（已执行节点集合）、
    ``blocked``（条件边屏蔽的分支目标）、``step_index``（执行进度）。
    """

    def __init__(self) -> None:
        # plan_id -> {checkpoint_id: snapshot}
        self._store: dict[str, dict[str, dict[str, Any]]] = {}

    def save_checkpoint(
        self,
        plan_id: str,
        step_index: int,
        runtime_context: dict[str, Any],
        executed_nodes: list[str] | set[str],
        *,
        blocked: list[str] | set[str] | None = None,
    ) -> str:
        """记录一次 checkpoint，返回唯一 ``checkpoint_id``。"""
        executed = list(executed_nodes or [])
        checkpoint_id = f"cp-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{len(executed)}"
        data: dict[str, Any] = {
            "plan_id": plan_id,
            "checkpoint_id": checkpoint_id,
            "step_index": step_index,
            "runtime_context": copy.deepcopy(dict(runtime_context or {})),
            "executed_nodes": sorted(executed),
            "blocked": sorted(blocked or []),
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._store.setdefault(plan_id, {})[checkpoint_id] = copy.deepcopy(data)
        return checkpoint_id

    def get_checkpoint(self, plan_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        """按 ``checkpoint_id`` 取回快照；不存在返回 ``None``。"""
        data = self._store.get(plan_id, {}).get(checkpoint_id)
        return copy.deepcopy(data) if data is not None else None

    def list_checkpoints(self, plan_id: str) -> list[dict[str, Any]]:
        """列出某 plan 的逐步 checkpoint（按 ``step_index`` 升序）。"""
        checkpoints = self._store.get(plan_id, {})
        ordered = sorted(checkpoints.values(), key=lambda cp: int(cp.get("step_index", 0)))
        return [copy.deepcopy(cp) for cp in ordered]

    def latest_checkpoint(self, plan_id: str) -> dict[str, Any] | None:
        """返回最新（进度最大）的 checkpoint；无则返回 ``None``。"""
        checkpoints = self.list_checkpoints(plan_id)
        return checkpoints[-1] if checkpoints else None


def _dump_json(value: Any) -> str:
    """安全 JSON 序列化（``None`` 与 str 透传，其余 default=str 兜底）。"""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


class DatabaseWorkflowCheckpointer:
    """DB 持久化的 Checkpointer：把运行时快照写入 ``workflow_checkpoints`` 表。

    与 ``WorkflowCheckpointer`` 保持同一接口（``save_checkpoint`` /
    ``get_checkpoint`` / ``list_checkpoints`` / ``latest_checkpoint``），使引擎的断点
    续跑与重放逻辑无需改动即可切换到数据库存储。

    每次操作独立打开会话（与 ``WorkflowDefinitionAppService`` 一致），短生命周期、
    无共享状态，可安全地在 ``_run_workflow_with_state_updates`` 每次调用时新建。
    保存失败（如 DB 不可用）时记录告警并返回 ``checkpoint_id``，不阻断工作流执行。
    """

    def __init__(self, session_factory=None) -> None:
        # 测试可注入自定义 session_factory（返回一个 SQLAlchemy Session）
        self._session_factory = session_factory
        # 惰性建表开关：首次写库时确保 ``workflow_checkpoints`` 表存在（幂等 checkfirst）
        self._schema_ensured = False

    def _ensure_schema(self, session) -> None:
        """首次写库前确保 ``workflow_checkpoints`` 表存在（幂等，不覆盖已有表）。"""
        if self._schema_ensured:
            return
        try:
            from app.db.base import Base
            from app.db.models.workflow import WorkflowCheckpoint

            Base.metadata.create_all(
                bind=session.get_bind(), tables=[WorkflowCheckpoint.__table__], checkfirst=True
            )
        except Exception:  # noqa: BLE001 - 建表失败不阻断工作流，仅告警
            logger.warning(
                "workflow_checkpoints 建表失败，checkpoint 将记录告警降级", exc_info=True
            )
        finally:
            # 无论成败只尝试一次，避免每次工作流执行都重复 DDL。
            self._schema_ensured = True

    def _get_session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from app.db import SessionLocal

        return SessionLocal()

    def save_checkpoint(
        self,
        plan_id: str,
        step_index: int,
        runtime_context: dict[str, Any],
        executed_nodes: list[str] | set[str],
        *,
        blocked: list[str] | set[str] | None = None,
    ) -> str:
        executed = list(executed_nodes or [])
        checkpoint_id = f"cp-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{len(executed)}"
        session = self._get_session()
        try:
            from app.db.models.workflow import WorkflowCheckpoint

            self._ensure_schema(session)
            session.add(
                WorkflowCheckpoint(
                    plan_id=plan_id,
                    checkpoint_id=checkpoint_id,
                    step_index=int(step_index),
                    runtime_context=_dump_json(dict(runtime_context or {})),
                    executed_nodes=_dump_json(sorted(executed)),
                    blocked=_dump_json(sorted(blocked or [])),
                )
            )
            session.commit()
        except RECOVERABLE_ERRORS:
            session.rollback()
            logger.warning(
                "DB checkpoint 保存失败 plan=%s step=%s（工作流继续执行）", plan_id, step_index
            )
        finally:
            session.close()
        return checkpoint_id

    def get_checkpoint(self, plan_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        session = self._get_session()
        try:
            from app.db.models.workflow import WorkflowCheckpoint

            row = (
                session.query(WorkflowCheckpoint)
                .filter(
                    WorkflowCheckpoint.plan_id == plan_id,
                    WorkflowCheckpoint.checkpoint_id == checkpoint_id,
                )
                .first()
            )
            return row.to_dict() if row is not None else None
        finally:
            session.close()

    def list_checkpoints(self, plan_id: str) -> list[dict[str, Any]]:
        session = self._get_session()
        try:
            from app.db.models.workflow import WorkflowCheckpoint

            rows = (
                session.query(WorkflowCheckpoint)
                .filter(WorkflowCheckpoint.plan_id == plan_id)
                .order_by(WorkflowCheckpoint.step_index.asc())
                .all()
            )
            return [row.to_dict() for row in rows]
        finally:
            session.close()

    def latest_checkpoint(self, plan_id: str) -> dict[str, Any] | None:
        checkpoints = self.list_checkpoints(plan_id)
        return checkpoints[-1] if checkpoints else None
