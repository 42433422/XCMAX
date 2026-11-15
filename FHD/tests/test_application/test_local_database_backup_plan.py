"""Ticket 67: original backup wordings must be admitted without a model call."""

from __future__ import annotations

import pytest

from app.application.workflow.local_database_backup_plan import classify_local_database_backup
from app.application.workflow.planner import LLMWorkflowPlanner

TICKET_PHRASES = (
    "请现在创建一次本机数据库备份",
    "请备份数据库",
    "请备份数据库。执行前先给我确认，需要审批的操作提交审批。",
)


def _planner() -> LLMWorkflowPlanner:
    def forbidden(**_kwargs):
        raise AssertionError("local backup commands must not call the planner model")

    return LLMWorkflowPlanner(completion=forbidden)


@pytest.mark.parametrize("message", TICKET_PHRASES)
def test_original_phrases_classify_as_backup(message):
    assert classify_local_database_backup(message) == "backup"


@pytest.mark.parametrize(
    "message,kind",
    [
        ("查看数据库备份", None),
        ("请恢复数据库", None),
        ("删除数据库备份", None),
        ("不要备份数据库", "negated"),
        ("备份数据库到 U 盘", "unsupported_destination"),
    ],
)
def test_non_create_wordings_are_not_executable_backups(message, kind):
    assert classify_local_database_backup(message) == kind


@pytest.mark.parametrize("message", TICKET_PHRASES)
def test_planner_admits_original_phrases_without_model(message):
    plan = _planner().plan(user_id="u-67", message=message, tool_registry={})
    assert plan.intent == "system_maintenance_backup_database"
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("system_maintenance", "backup_database")]
    assert plan.nodes[0].params == {}
    assert plan.metadata.get("planning_source") == "deterministic_command"
    assert plan.metadata.get("planning_rejected") is not True


@pytest.mark.parametrize(
    "message,reason",
    [
        ("不要备份数据库", "不会创建数据库备份"),
        ("备份数据库到 U 盘", "只支持创建本机数据库备份"),
    ],
)
def test_planner_rejects_negated_or_external_destination_with_a_visible_reason(message, reason):
    plan = _planner().plan(user_id="u-67", message=message, tool_registry={})
    assert plan.metadata.get("planning_rejected") is True
    assert reason in str(plan.metadata.get("rejection_reason") or "")
    assert plan.nodes == []


def _dispatch_result(message: str, monkeypatch):
    from unittest.mock import Mock

    from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.risk_gate import HybridRiskGate

    callbacks = Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    callbacks._merge_tool_runtime_context.return_value = {}
    callbacks._build_workflow_thinking_steps.return_value = "计划：创建本机数据库备份"
    monkeypatch.setattr(
        "app.application.facades.tools_facade.get_workflow_tool_registry",
        lambda: {},
    )
    return PlannedWorkflowDispatch(
        {}, callbacks, _planner(), HybridRiskGate(), ApprovalService()
    ).handle("u-67", message, "pro", {}, message)


def test_dispatch_asks_for_existing_risk_confirmation_without_running_backup(monkeypatch):
    from unittest.mock import Mock

    orchestrator = Mock()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.AgentOrchestrator",
        lambda: orchestrator,
    )
    result = _dispatch_result("请现在创建一次本机数据库备份", monkeypatch)
    assert result["execution_started"] is False
    assert result["data"]["action"] == "workflow_confirmation_required"
    assert "backup_database" in str(result["data"])
    orchestrator.start_run_from_plan.assert_not_called()


def test_dispatch_surfaces_unsupported_destination_without_calling_a_model(monkeypatch):
    result = _dispatch_result("备份数据库到 U 盘", monkeypatch)
    assert result["success"] is False
    assert result["data"]["execution_started"] is False
    assert "只支持创建本机数据库备份" in result["response"]


def test_official_backup_keeps_existing_approval_contract():
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.workflow_types import WorkflowNode
    from resources.config.risk_actions_loader import get_action_approval

    svc = ApprovalService()
    backup = WorkflowNode(node_id="b", tool_id="system_maintenance", action="backup_database", params={}, risk="medium")
    restore = WorkflowNode(node_id="r", tool_id="system_maintenance", action="restore_database", params={}, risk="high")
    assert get_action_approval("system_maintenance", "backup_database") != "always"
    assert svc.check_node_requires_approval(backup) is False
    assert get_action_approval("system_maintenance", "restore_database") == "always"
    assert svc.check_node_requires_approval(restore) is True
