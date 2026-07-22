"""工作流定义种子：发票 → 入库 → 审批 → 月报 端到端编排

创建一条 ``WorkflowDefinition``，描述 OCR 识别发票后自动触发的完整业务链路：

1. ``ocr.completed``（doc_type=invoice）→ 触发自动编排
2. ``inventory.auto_inbound_requested`` → 调用 ``PurchaseService.create_purchase_inbound``
3. ``finance.approval_requested`` → 调用 ``ApprovalService.create_approval_request``
4. ``finance.approval_completed`` → 调用 ``PurchaseService.update_inbound_approval_status``
5. ``report.monthly_summary_requested`` → 调用 ``generate_monthly_finance_summary``

事件实际由 ``app/neuro_bus/domains/*_domain_handlers.py`` 中的 handler 消费并
编排；本 ``WorkflowDefinition`` 主要用于可视化 / 运维追溯 / 工作流引擎触发
（``start_run``），不直接驱动 handler 注册。

幂等：以 ``name`` 为业务键去重；已存在同 name 的 active 定义时跳过创建。
"""

from __future__ import annotations

import logging
from typing import Any

from app.db.models.workflow import WorkflowTriggerType
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


SEED_WORKFLOW_NAME = "发票→入库→审批→月报 自动编排"


def _build_nodes() -> list[dict[str, Any]]:
    """构造端到端编排的 5 个节点。

    节点 ``tool_id`` / ``action`` 与 ``app/neuro_bus/domains/*_domain_handlers.py``
    中订阅的事件类型对齐，便于工作流引擎后续接入时直接派发 NeuroBus 事件。
    """
    return [
        {
            "node_id": "ocr_completed",
            "tool_id": "ocr",
            "action": "completed",
            "params": {"doc_type": "invoice"},
            "risk": "low",
            "idempotent": True,
            "description": "OCR 识别发票完成（触发条件）",
            "depends_on": [],
        },
        {
            "node_id": "auto_inbound_requested",
            "tool_id": "inventory",
            "action": "auto_inbound_requested",
            "params": {"source_event": "ocr.completed"},
            "risk": "medium",
            "idempotent": True,
            "description": "自动创建采购入库单",
            "depends_on": ["ocr_completed"],
        },
        {
            "node_id": "approval_requested",
            "tool_id": "finance",
            "action": "approval_requested",
            "params": {"business_type": "purchase_inbound"},
            "risk": "medium",
            "idempotent": True,
            "description": "推送财务审批",
            "depends_on": ["auto_inbound_requested"],
        },
        {
            "node_id": "approval_completed",
            "tool_id": "finance",
            "action": "approval_completed",
            "params": {"decisions": ["approved", "rejected"]},
            "risk": "low",
            "idempotent": True,
            "description": "审批完成回写入库单状态",
            "depends_on": ["approval_requested"],
        },
        {
            "node_id": "monthly_summary_requested",
            "tool_id": "report",
            "action": "monthly_summary_requested",
            "params": {"schedule": "monthly", "day_of_month": 1, "hour": 0, "minute": 30},
            "risk": "low",
            "idempotent": True,
            "description": "月底汇总财务月报",
            "depends_on": ["approval_completed"],
        },
    ]


def _build_edges(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """从 ``depends_on`` 反推边列表（便于前端 DAG 可视化）。"""
    edges: list[dict[str, str]] = []
    for node in nodes:
        for dep in node.get("depends_on") or []:
            edges.append({"from": dep, "to": node["node_id"]})
    return edges


def _build_trigger_config() -> dict[str, Any]:
    """事件触发配置：OCR 完成且 doc_type=invoice 时启动编排。"""
    return {"event": "ocr.completed", "doc_type": "invoice"}


def seed_invoice_to_inbound_to_approval_to_report_workflow(
    *,
    tenant_id: int | None = None,
    created_by: int | None = None,
    session_factory=None,
) -> dict[str, Any] | None:
    """幂等创建「发票→入库→审批→月报」工作流定义。

    Args:
        tenant_id: 租户 ID（None 表示全局共享）
        created_by: 创建者用户 ID
        session_factory: 可选的 session 工厂（测试注入用）

    Returns:
        创建成功的 ``WorkflowDefinition.to_dict()``；若已存在同 name 的 active
        定义则返回 None（幂等跳过）。
    """
    from app.application.workflow_definition_app_service import (
        WorkflowDefinitionAppService,
    )
    from app.db.models.workflow import WorkflowDefinition
    from app.db.session import get_db

    # 幂等检查：同 name 的 active 定义已存在则跳过
    try:
        with get_db() as db:
            existing = (
                db.query(WorkflowDefinition)
                .filter(
                    WorkflowDefinition.name == SEED_WORKFLOW_NAME,
                    WorkflowDefinition.is_active.is_(True),
                )
                .first()
            )
            if existing is not None:
                logger.info(
                    "[Seed] 工作流定义已存在 (id=%s, version=%s)，跳过创建: %s",
                    existing.id,
                    existing.version,
                    SEED_WORKFLOW_NAME,
                )
                return None
    except RECOVERABLE_ERRORS as exc:
        logger.warning("[Seed] 幂等检查失败，继续尝试创建: %s", exc)

    service = WorkflowDefinitionAppService(session_factory=session_factory)
    nodes = _build_nodes()
    edges = _build_edges(nodes)

    try:
        result = service.create_definition(
            tenant_id=tenant_id,
            name=SEED_WORKFLOW_NAME,
            description=(
                "OCR 识别发票后自动创建采购入库单、推送财务审批，"
                "月底汇总月度财务报表的端到端编排链路。"
                "事件由 NeuroBus domain handlers 消费，本定义用于工作流引擎追溯。"
            ),
            trigger_type=WorkflowTriggerType.EVENT.value,
            trigger_config=_build_trigger_config(),
            nodes=nodes,
            edges=edges,
            created_by=created_by,
        )
        logger.info(
            "[Seed] 工作流定义创建成功 id=%s name=%s",
            result.get("id"),
            SEED_WORKFLOW_NAME,
        )
        return result
    except RECOVERABLE_ERRORS as exc:
        logger.exception("[Seed] 工作流定义创建失败: %s", exc)
        raise


def run_all_seeds(
    *,
    tenant_id: int | None = None,
    created_by: int | None = None,
    session_factory=None,
) -> dict[str, Any]:
    """运行所有工作流定义种子（供运维脚本 / init_db 调用）。"""
    results: dict[str, Any] = {"workflow_definitions": []}

    try:
        wf_result = seed_invoice_to_inbound_to_approval_to_report_workflow(
            tenant_id=tenant_id,
            created_by=created_by,
            session_factory=session_factory,
        )
        results["workflow_definitions"].append(
            {
                "name": SEED_WORKFLOW_NAME,
                "created": wf_result is not None,
                "definition": wf_result,
            }
        )
    except RECOVERABLE_ERRORS as exc:
        results["workflow_definitions"].append(
            {"name": SEED_WORKFLOW_NAME, "created": False, "error": str(exc)}
        )

    return results


__all__ = [
    "SEED_WORKFLOW_NAME",
    "seed_invoice_to_inbound_to_approval_to_report_workflow",
    "run_all_seeds",
]
