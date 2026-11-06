"""Acceptance tool catalog and the workflow plan it produces."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from app.application.agent_orchestrator.tool_spec import validate_schema_object
from app.application.workflow.tool_turn_runtime import (
    ToolDef,
    TurnState,
    _ordered_steps,
    classify_intent,
    select_tools,
)


def acceptance_tools() -> list[ToolDef]:
    """Tools used by the order, export, and customer acceptance cases."""
    order_query = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"},
            "region": {"type": "string", "maxLength": 32},
            "status": {"type": "string", "enum": ["paid", "unpaid", "cancelled"]},
            "min_amount": {"type": "number", "minimum": 0},
            "min_amount_exclusive": {"type": "number", "minimum": 0},
        },
    }
    return [
        ToolDef("query_orders", "查询订单", order_query, permissions=("orders.read",), triggers=("订单", "query")),
        ToolDef("query_customers", "查询客户数量", {"type": "object", "additionalProperties": False, "properties": {}}, permissions=("customers.read",), triggers=("客户",)),
        ToolDef("query_inventory", "查询库存", {"type": "object", "additionalProperties": False, "properties": {}}, permissions=("inventory.read",), triggers=("库存",)),
        ToolDef("sales_stats", "统计销售总额", order_query, permissions=("orders.read",), triggers=("统计", "aggregate")),
        ToolDef("customer_group", "按客户分类", order_query, permissions=("orders.read",), triggers=("分类", "group")),
        ToolDef(
            "export_excel",
            "导出 Excel",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {**order_query["properties"], "source_step": {"type": "string"}},
            },
            permissions=("orders.export",),
            triggers=("导出", "export", "Excel"),
        ),
        ToolDef(
            "create_order",
            "创建订单",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["customer_id", "amount"],
                "properties": {
                    "customer_id": {"type": "string", "minLength": 1},
                    "amount": {"type": "number", "exclusiveMinimum": 0, "maximum": 100000000},
                    "remark": {"type": "string", "maxLength": 20},
                },
            },
            permissions=("orders.write",),
            triggers=("创建订单", "create"),
            risk="high",
        ),
        ToolDef(
            "delete_order",
            "删除订单",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["order_id"],
                "properties": {"order_id": {"type": "string", "minLength": 2}},
            },
            permissions=("orders.delete",),
            triggers=("删除", "delete"),
            risk="high",
        ),
        ToolDef(
            "create_customer",
            "创建客户档案",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["name"],
                "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 40}},
            },
            permissions=("customers.write",),
            triggers=("客户档案", "create"),
            risk="high",
        ),
    ]


def plan_graph_for_registry(
    plan_id: str,
    message: str,
    tool_registry: Mapping[str, Any],
    *,
    today: date | None = None,
):
    """Return a workflow plan when every selected acceptance tool is registered."""
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    known = [tool for tool in acceptance_tools() if tool.name in tool_registry]
    if not known:
        return None
    permissions = {item for tool in known for item in tool.permissions}
    assessment = classify_intent(message, TurnState())
    selected = select_tools(message, assessment, known, permissions)
    if not selected:
        return None
    state = TurnState()
    nodes = []
    high = False
    for step in _ordered_steps(message, selected, state, today=today):
        tool = next(item for item in selected if item.name == step.tool_name)
        ok, error = validate_schema_object(tool.schema, step.arguments)
        if not ok:
            return PlanGraph(
                plan_id=plan_id,
                intent="clarify_ask",
                nodes=[
                    WorkflowNode(
                        node_id="clarify_tool_arguments",
                        tool_id="clarify",
                        action="ask",
                        params={"question": error, "target_tool": step.tool_name},
                        risk="low",
                        idempotent=True,
                        description=error,
                    )
                ],
                risk_level="low",
                metadata={"planner": "tool_turn", "executed": False},
            )
        high = high or tool.risk == "high"
        nodes.append(
            WorkflowNode(
                node_id=step.step_id,
                tool_id=step.tool_name,
                action="query" if step.tool_name.startswith("query") or step.tool_name.endswith("stats") else "execute",
                params=dict(step.arguments),
                risk="high" if tool.risk == "high" else "low",
                idempotent=tool.risk != "high",
                description=tool.description,
                depends_on=list(step.depends_on),
            )
        )
    return PlanGraph(
        plan_id=plan_id,
        intent=str(assessment.get("intent") or "tool_turn"),
        nodes=nodes,
        risk_level="high" if high else "low",
        metadata={"planner": "tool_turn", "message": message},
    )
