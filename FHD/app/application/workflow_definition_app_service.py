"""工作流定义 CRUD + 运行管理应用服务。

提供 ``WorkflowDefinition`` 的完整生命周期管理（创建/更新/查询/删除/启停）以及
``WorkflowRun`` 的启动/查询/取消。``LLMWorkflowPlanner`` 可通过 ``persist=True``
将生成的 ``PlanGraph`` 持久化为 ``WorkflowDefinition``。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional, cast

from app.application.workflow_definition_serialization import (
    coerce_serializable as _coerce_serializable,
)
from app.db.models.workflow import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunStep,
    WorkflowRunStepStatus,
    WorkflowTriggerSource,
    WorkflowTriggerType,
)
from app.errors import AppError, WorkflowError
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _dump_json(value: Any) -> str:
    """安全 JSON 序列化：``None`` 与字符串透传。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _load_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _node_id_of(node: Any) -> Optional[str]:
    if isinstance(node, dict):
        nid = node.get("node_id") or node.get("id")
        return str(nid) if nid is not None else None
    return getattr(node, "node_id", None)


class WorkflowDefinitionAppService:
    """工作流定义与运行的应用编排层。

    设计要点：
    - 不直接耦合 ``PlanGraph`` dataclass，通过 dict/JSON 序列化交互，便于跨进程持久化。
    - ``update_definition`` 自增 ``version``，实现乐观并发控制（同一时间多人编辑可检测）。
    - ``start_run`` 在创建 ``WorkflowRun`` 时冻结 ``steps_snapshot``，确保历史运行可追溯。
    """

    def __init__(self, session_factory=None) -> None:
        # 延迟导入避免循环依赖；测试可注入自定义 session_factory
        self._session_factory = session_factory

    def _get_session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from app.db import SessionLocal

        return SessionLocal()

    # ── 定义 CRUD ──────────────────────────────────────────────

    def create_definition(
        self,
        *,
        tenant_id: int | None,
        name: str,
        description: str | None = None,
        trigger_type: str = WorkflowTriggerType.MANUAL.value,
        trigger_config: dict[str, Any] | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        created_by: int | None = None,
    ) -> dict[str, Any]:
        """创建工作流定义。"""
        if not name or not str(name).strip():
            raise WorkflowError(message="工作流定义名称不能为空", status_code=422)
        if trigger_type not in {t.value for t in WorkflowTriggerType}:
            raise WorkflowError(
                message=f"未知触发类型: {trigger_type}",
                status_code=422,
            )
        if nodes is None:
            nodes = []
        if edges is None:
            edges = []

        definition = WorkflowDefinition(
            tenant_id=tenant_id,
            name=str(name).strip(),
            description=description,
            trigger_type=trigger_type,
            trigger_config=_dump_json(trigger_config or {}),
            nodes=_dump_json(nodes),
            edges=_dump_json(edges),
            version=1,
            is_active=True,
            created_by=created_by,
        )
        session = self._get_session()
        try:
            session.add(definition)
            session.commit()
            session.refresh(definition)
            return definition.to_dict()
        except RECOVERABLE_ERRORS as exc:
            session.rollback()
            logger.exception("创建工作流定义失败")
            raise WorkflowError(message=f"创建工作流定义失败: {exc}") from exc
        finally:
            session.close()

    def update_definition(
        self,
        definition_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        trigger_type: str | None = None,
        trigger_config: dict[str, Any] | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        """更新工作流定义；每次更新自增 version。"""
        if trigger_type is not None and trigger_type not in {t.value for t in WorkflowTriggerType}:
            raise WorkflowError(
                message=f"未知触发类型: {trigger_type}",
                status_code=422,
            )

        session = self._get_session()
        try:
            definition = session.get(WorkflowDefinition, definition_id)
            if definition is None:
                raise WorkflowError(
                    message=f"工作流定义不存在: {definition_id}",
                    status_code=404,
                )

            if name is not None:
                if not str(name).strip():
                    raise WorkflowError(message="工作流定义名称不能为空", status_code=422)
                definition.name = str(name).strip()
            if description is not None:
                definition.description = description
            if trigger_type is not None:
                definition.trigger_type = trigger_type
            if trigger_config is not None:
                definition.trigger_config = _dump_json(trigger_config)
            if nodes is not None:
                definition.nodes = _dump_json(nodes)
            if edges is not None:
                definition.edges = _dump_json(edges)
            if is_active is not None:
                definition.is_active = bool(is_active)
            definition.version = (definition.version or 1) + 1

            session.commit()
            session.refresh(definition)
            return cast("dict[str, Any]", definition.to_dict())
        except AppError:
            session.rollback()
            raise
        except RECOVERABLE_ERRORS as exc:
            session.rollback()
            logger.exception("更新工作流定义失败")
            raise WorkflowError(message=f"更新工作流定义失败: {exc}") from exc
        finally:
            session.close()

    def get_definition(self, definition_id: int) -> dict[str, Any]:
        """按 ID 获取工作流定义。"""
        session = self._get_session()
        try:
            definition = session.get(WorkflowDefinition, definition_id)
            if definition is None:
                raise WorkflowError(
                    message=f"工作流定义不存在: {definition_id}",
                    status_code=404,
                )
            return cast("dict[str, Any]", definition.to_dict())
        finally:
            session.close()

    def list_definitions(
        self,
        *,
        tenant_id: int | None = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """列出工作流定义；可按租户和启用状态过滤。"""
        session = self._get_session()
        try:
            query = session.query(WorkflowDefinition)
            if tenant_id is not None:
                query = query.filter(WorkflowDefinition.tenant_id == tenant_id)
            if active_only:
                query = query.filter(WorkflowDefinition.is_active.is_(True))
            rows = query.order_by(WorkflowDefinition.id.desc()).limit(max(1, limit)).all()
            return [row.to_dict() for row in rows]
        finally:
            session.close()

    def delete_definition(self, definition_id: int) -> None:
        """删除工作流定义（级联删除运行与单步）。"""
        session = self._get_session()
        try:
            definition = session.get(WorkflowDefinition, definition_id)
            if definition is None:
                raise WorkflowError(
                    message=f"工作流定义不存在: {definition_id}",
                    status_code=404,
                )
            session.delete(definition)
            session.commit()
        except AppError:
            session.rollback()
            raise
        except RECOVERABLE_ERRORS as exc:
            session.rollback()
            logger.exception("删除工作流定义失败")
            raise WorkflowError(message=f"删除工作流定义失败: {exc}") from exc
        finally:
            session.close()

    def activate_definition(self, definition_id: int) -> dict[str, Any]:
        """启用工作流定义。"""
        return self.update_definition(definition_id, is_active=True)

    def deactivate_definition(self, definition_id: int) -> dict[str, Any]:
        """停用工作流定义。"""
        return self.update_definition(definition_id, is_active=False)

    # ── 运行管理 ───────────────────────────────────────────────

    def start_run(
        self,
        definition_id: int,
        *,
        triggered_by: str = WorkflowTriggerSource.USER.value,
        trigger_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """启动工作流运行：从 definition 加载 nodes，创建 WorkflowRun + WorkflowRunStep。

        运行创建后状态为 ``pending``；实际执行由调度器/引擎消费（本服务只负责记账）。
        """
        if triggered_by not in {t.value for t in WorkflowTriggerSource}:
            raise WorkflowError(
                message=f"未知触发来源: {triggered_by}",
                status_code=422,
            )

        session = self._get_session()
        try:
            definition = session.get(WorkflowDefinition, definition_id)
            if definition is None:
                raise WorkflowError(
                    message=f"工作流定义不存在: {definition_id}",
                    status_code=404,
                )
            if not definition.is_active:
                raise WorkflowError(
                    message=f"工作流定义已停用，无法启动运行: {definition_id}",
                    status_code=409,
                )

            nodes_snapshot = _load_json(definition.nodes, [])
            run = WorkflowRun(
                definition_id=definition.id,
                tenant_id=definition.tenant_id,
                status=WorkflowRunStatus.PENDING.value,
                triggered_by=triggered_by,
                trigger_payload=_dump_json(trigger_payload or {}),
                steps_snapshot=_dump_json(nodes_snapshot),
            )
            session.add(run)
            session.flush()  # 拿到 run.id

            # 为每个 node 创建 pending WorkflowRunStep
            for node in nodes_snapshot:
                node_id = _node_id_of(node)
                if not node_id:
                    continue
                step = WorkflowRunStep(
                    run_id=run.id,
                    node_id=str(node_id),
                    status=WorkflowRunStepStatus.PENDING.value,
                )
                session.add(step)

            session.commit()
            session.refresh(run)
            return run.to_dict()
        except AppError:
            session.rollback()
            raise
        except RECOVERABLE_ERRORS as exc:
            session.rollback()
            logger.exception("启动工作流运行失败")
            raise WorkflowError(message=f"启动工作流运行失败: {exc}") from exc
        finally:
            session.close()

    def get_run(self, run_id: int) -> dict[str, Any]:
        """获取运行详情（含 steps）。"""
        session = self._get_session()
        try:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                raise WorkflowError(
                    message=f"工作流运行不存在: {run_id}",
                    status_code=404,
                )
            data = run.to_dict()
            data["steps"] = [step.to_dict() for step in run.steps]
            return cast("dict[str, Any]", data)
        finally:
            session.close()

    def list_runs(
        self,
        definition_id: int,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """列出某定义下的最近运行。"""
        session = self._get_session()
        try:
            rows = (
                session.query(WorkflowRun)
                .filter(WorkflowRun.definition_id == definition_id)
                .order_by(WorkflowRun.id.desc())
                .limit(max(1, limit))
                .all()
            )
            return [row.to_dict() for row in rows]
        finally:
            session.close()

    def cancel_run(self, run_id: int) -> dict[str, Any]:
        """取消运行：将 pending/running 状态置为 cancelled，并标记未完成 step 为 skipped。"""
        session = self._get_session()
        try:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                raise WorkflowError(
                    message=f"工作流运行不存在: {run_id}",
                    status_code=404,
                )
            terminal = {
                WorkflowRunStatus.SUCCEEDED.value,
                WorkflowRunStatus.FAILED.value,
                WorkflowRunStatus.CANCELLED.value,
            }
            if run.status in terminal:
                raise WorkflowError(
                    message=f"运行已处于终态，无法取消: {run.status}",
                    status_code=409,
                )
            run.status = WorkflowRunStatus.CANCELLED.value
            run.finished_at = datetime.utcnow()
            # 未完成 step 标 skipped
            for step in run.steps:
                if step.status not in {
                    WorkflowRunStepStatus.SUCCEEDED.value,
                    WorkflowRunStepStatus.FAILED.value,
                }:
                    step.status = WorkflowRunStepStatus.SKIPPED.value
                    step.finished_at = datetime.utcnow()
            session.commit()
            session.refresh(run)
            return cast("dict[str, Any]", run.to_dict())
        except AppError:
            session.rollback()
            raise
        except RECOVERABLE_ERRORS as exc:
            session.rollback()
            logger.exception("取消工作流运行失败")
            raise WorkflowError(message=f"取消工作流运行失败: {exc}") from exc
        finally:
            session.close()

    # ── PlanGraph 适配 ─────────────────────────────────────────

    def create_definition_from_plan_graph(
        self,
        plan_graph: Any,
        *,
        tenant_id: int | None,
        name: str,
        description: str | None = None,
        trigger_type: str = WorkflowTriggerType.ONE_TIME.value,
        trigger_config: dict[str, Any] | None = None,
        created_by: int | None = None,
    ) -> dict[str, Any]:
        """从 ``PlanGraph`` dataclass 持久化为 ``WorkflowDefinition``。

        将 ``plan_graph.nodes`` 转换为 JSON-serializable dict 列表；``edges`` 由
        ``depends_on`` 反推生成。
        """
        nodes_data: list[dict[str, Any]] = []
        edges_data: list[dict[str, Any]] = []
        for node in getattr(plan_graph, "nodes", []) or []:
            node_dict = self._node_to_dict(node)
            nodes_data.append(node_dict)
            for dep in node_dict.get("depends_on") or []:
                edges_data.append({"from": dep, "to": node_dict["node_id"]})

        return self.create_definition(
            tenant_id=tenant_id,
            name=name,
            description=description or getattr(plan_graph, "intent", None),
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            nodes=nodes_data,
            edges=edges_data,
            created_by=created_by,
        )

    @staticmethod
    def _node_to_dict(node: Any) -> dict[str, Any]:
        if isinstance(node, dict):
            return dict(node)
        # dataclass / pydantic
        if hasattr(node, "__dict__"):
            return {
                k: _coerce_serializable(v)
                for k, v in node.__dict__.items()
                if not k.startswith("_")
            }
        # fallback：尝试 asdict
        try:
            from dataclasses import asdict

            return asdict(node)
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - 兜底序列化，所有异常都退化为 node_id 字符串
            return {"node_id": str(node)}


# ── 单例工厂 ────────────────────────────────────────────────

_workflow_definition_app_service: WorkflowDefinitionAppService | None = None


def get_workflow_definition_app_service() -> WorkflowDefinitionAppService:
    """返回进程级单例（生产/路由层使用）。测试可直接构造新实例注入 session。"""
    global _workflow_definition_app_service
    if _workflow_definition_app_service is None:
        _workflow_definition_app_service = WorkflowDefinitionAppService()
    return _workflow_definition_app_service


def reset_workflow_definition_app_service() -> None:
    """重置单例（测试清理用）。"""
    global _workflow_definition_app_service
    _workflow_definition_app_service = None


__all__ = [
    "WorkflowDefinitionAppService",
    "get_workflow_definition_app_service",
    "reset_workflow_definition_app_service",
]
