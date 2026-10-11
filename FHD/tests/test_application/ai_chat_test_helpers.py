"""Shared isolated AI chat service and workflow test objects."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.application.ai_chat_app_service import AIChatApplicationService


def _make_svc() -> AIChatApplicationService:
    """构造能正常实例化的服务（模拟所有构造依赖）。"""
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


def _make_plan(
    *,
    plan_id: str = "plan_test",
    intent: str = "test_intent",
    nodes=None,
    todo_steps=None,
    risk_level: str = "low",
    metadata=None,
):
    """构造一个简单的 plan 对象（避免依赖真实 PlanGraph）。"""
    return SimpleNamespace(
        plan_id=plan_id,
        intent=intent,
        nodes=nodes or [],
        todo_steps=todo_steps or [],
        risk_level=risk_level,
        metadata=metadata or {},
    )


def _make_node(
    *,
    node_id: str = "n1",
    tool_id: str = "products",
    action: str = "query",
    params=None,
    risk: str = "low",
    idempotent: bool = True,
    depends_on=None,
    description: str = "",
):
    return SimpleNamespace(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        params=params or {},
        risk=risk,
        idempotent=idempotent,
        depends_on=depends_on or [],
        description=description,
    )


def _make_node_result(
    *,
    node_id: str = "n1",
    tool_id: str = "products",
    action: str = "query",
    success: bool = True,
    output=None,
    error: str = "",
    params=None,
    retryable: bool = True,
    retries: int = 0,
    recovery_hint: str = "",
    started_at: str = "",
    finished_at: str = "",
    duration_ms: int = 0,
):
    return SimpleNamespace(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        success=success,
        output=output or {},
        error=error,
        params=params or {},
        retryable=retryable,
        retries=retries,
        recovery_hint=recovery_hint,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    )


def _make_run_result(
    *,
    success: bool = True,
    message: str = "",
    node_results=None,
    final_context=None,
):
    return SimpleNamespace(
        success=success,
        message=message,
        node_results=node_results or [],
        final_context=final_context or {},
    )
