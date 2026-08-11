"""Tests for app.application.workflow.approval_service — coverage ramp."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.application.workflow.approval_service import (
    ApprovalService,
    get_approval_service,
    process_approval_timeouts,
    reload_approval_service,
)
from app.application.workflow.types import (
    ApprovalRequest,
    ApprovalStatus,
    PlanGraph,
    WorkflowNode,
)


def _make_node(
    node_id: str = "n1",
    tool_id: str = "shipment_generate",
    action: str = "execute",
    params: dict | None = None,
) -> WorkflowNode:
    return WorkflowNode(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        params=params or {},
    )


def _make_plan(nodes: list[WorkflowNode] | None = None) -> PlanGraph:
    return PlanGraph(
        plan_id="plan-1",
        intent="test",
        nodes=nodes or [_make_node()],
    )


# ---------------------------------------------------------------------------
# ApprovalService — check_node_requires_approval
# ---------------------------------------------------------------------------
class TestCheckNodeRequiresApproval:
    def test_disabled_config(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=False)
        node = _make_node()
        assert svc.check_node_requires_approval(node) is False

    def test_always_trigger(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        svc._config.rules = [
            {"tool_id": "shipment_generate", "action": "execute", "trigger": "always"}
        ]
        node = _make_node()
        assert svc.check_node_requires_approval(node) is True

    def test_business_db_interactive_write_requires_approval(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True, rules=[])
        node = _make_node(tool_id="business_db", action="write")
        assert svc.check_node_requires_approval(node) is True

    def test_never_trigger(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        svc._config.rules = [
            {"tool_id": "shipment_generate", "action": "execute", "trigger": "never"}
        ]
        node = _make_node()
        assert svc.check_node_requires_approval(node) is False

    def test_conditional_trigger_match(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        svc._config.rules = [
            {
                "tool_id": "shipment_generate",
                "action": "execute",
                "trigger": "conditional",
                "conditions": {"amount": 100},
            }
        ]
        node = _make_node(params={"amount": 100})
        assert svc.check_node_requires_approval(node) is True

    def test_conditional_trigger_no_match(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        svc._config.rules = [
            {
                "tool_id": "shipment_generate",
                "action": "execute",
                "trigger": "conditional",
                "conditions": {"amount": 100},
            }
        ]
        node = _make_node(params={"amount": 50})
        assert svc.check_node_requires_approval(node) is False

    def test_no_matching_rule(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        svc._config.rules = [{"tool_id": "other_tool", "action": "execute", "trigger": "always"}]
        node = _make_node(tool_id="shipment_generate")
        assert svc.check_node_requires_approval(node) is False


# ---------------------------------------------------------------------------
# ApprovalService — _evaluate_conditions
# ---------------------------------------------------------------------------
class TestEvaluateConditions:
    def test_empty_conditions(self):
        svc = ApprovalService()
        node = _make_node()
        assert svc._evaluate_conditions({}, node) is False

    def test_simple_equality(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 100})
        assert svc._evaluate_conditions({"amount": 100}, node) is True

    def test_simple_inequality(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 50})
        assert svc._evaluate_conditions({"amount": 100}, node) is False

    def test_missing_param(self):
        svc = ApprovalService()
        node = _make_node(params={})
        assert svc._evaluate_conditions({"amount": 100}, node) is False

    def test_op_gt(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 150})
        assert svc._evaluate_conditions({"amount": {"op": "gt", "value": 100}}, node) is True

    def test_op_gt_fail(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 50})
        assert svc._evaluate_conditions({"amount": {"op": "gt", "value": 100}}, node) is False

    def test_op_gte(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 100})
        assert svc._evaluate_conditions({"amount": {"op": "gte", "value": 100}}, node) is True

    def test_op_lt(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 50})
        assert svc._evaluate_conditions({"amount": {"op": "lt", "value": 100}}, node) is True

    def test_op_lte(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 100})
        assert svc._evaluate_conditions({"amount": {"op": "lte", "value": 100}}, node) is True

    def test_op_neq(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 50})
        assert svc._evaluate_conditions({"amount": {"op": "neq", "value": 100}}, node) is True

    def test_op_neq_fail(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 100})
        assert svc._evaluate_conditions({"amount": {"op": "neq", "value": 100}}, node) is False

    def test_op_eq(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 100})
        assert svc._evaluate_conditions({"amount": {"op": "eq", "value": 100}}, node) is True

    def test_op_contains(self):
        svc = ApprovalService()
        node = _make_node(params={"name": "hello world"})
        assert (
            svc._evaluate_conditions({"name": {"op": "contains", "value": "world"}}, node) is True
        )

    def test_op_contains_fail(self):
        svc = ApprovalService()
        node = _make_node(params={"name": "hello"})
        assert (
            svc._evaluate_conditions({"name": {"op": "contains", "value": "world"}}, node) is False
        )

    def test_multiple_conditions_all_match(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 150, "type": "urgent"})
        assert (
            svc._evaluate_conditions({"amount": {"op": "gt", "value": 100}, "type": "urgent"}, node)
            is True
        )

    def test_multiple_conditions_one_fails(self):
        svc = ApprovalService()
        node = _make_node(params={"amount": 50, "type": "urgent"})
        assert (
            svc._evaluate_conditions({"amount": {"op": "gt", "value": 100}, "type": "urgent"}, node)
            is False
        )


# ---------------------------------------------------------------------------
# ApprovalService — get_approval_required_nodes
# ---------------------------------------------------------------------------
class TestGetApprovalRequiredNodes:
    def test_disabled(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=False)
        plan = _make_plan([_make_node(), _make_node(node_id="n2", tool_id="other")])
        assert svc.get_approval_required_nodes(plan) == []

    def test_some_nodes_require_approval(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        svc._config.rules = [
            {"tool_id": "shipment_generate", "action": "execute", "trigger": "always"}
        ]
        plan = _make_plan(
            [
                _make_node(tool_id="shipment_generate"),
                _make_node(node_id="n2", tool_id="other"),
            ]
        )
        result = svc.get_approval_required_nodes(plan)
        assert len(result) == 1
        assert result[0].tool_id == "shipment_generate"


# ---------------------------------------------------------------------------
# ApprovalService — create / approve / reject / cancel
# ---------------------------------------------------------------------------
class TestApprovalRequestLifecycle:
    def test_create_request(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        req = svc.create_approval_request("plan-1", node)
        assert req.request_id is not None
        assert req.status == ApprovalStatus.PENDING
        assert req.tool_id == "shipment_generate"

    def test_create_request_with_plan(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        plan = _make_plan()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node, plan=plan)
        assert svc.get_pending_workflow(req.request_id) is not None

    def test_approve_request(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        assert svc.approve(req.request_id) is True
        assert req.status == ApprovalStatus.APPROVED
        assert req.approved_at is not None

    def test_approve_nonexistent_request(self):
        svc = ApprovalService()
        assert svc.approve("nonexistent") is False

    def test_approve_already_approved(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        svc.approve(req.request_id)
        assert svc.approve(req.request_id) is False

    def test_reject_request(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        assert svc.reject(req.request_id, "bad") is True
        assert req.status == ApprovalStatus.REJECTED
        assert req.approver_comment == "bad"

    def test_reject_nonexistent_request(self):
        svc = ApprovalService()
        assert svc.reject("nonexistent") is False

    def test_cancel_request(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        assert svc.cancel(req.request_id) is True
        assert req.status == ApprovalStatus.CANCELLED

    def test_cancel_nonexistent_request(self):
        svc = ApprovalService()
        assert svc.cancel("nonexistent") is False


# ---------------------------------------------------------------------------
# ApprovalService — query methods
# ---------------------------------------------------------------------------
class TestApprovalQueryMethods:
    def test_get_pending_request(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        assert svc.get_pending_request(req.request_id) is req

    def test_get_pending_request_not_found(self):
        svc = ApprovalService()
        assert svc.get_pending_request("nonexistent") is None

    def test_get_pending_request_by_plan(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        assert svc.get_pending_request_by_plan("plan-1") is req

    def test_get_pending_request_by_plan_not_found(self):
        svc = ApprovalService()
        assert svc.get_pending_request_by_plan("nonexistent") is None

    def test_is_approved(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        assert svc.is_approved("plan-1") is False
        svc.approve(req.request_id)
        # fail-closed：审批通过（status=APPROVED）后，is_approved 应返回 True。
        assert svc.is_approved("plan-1") is True

    def test_is_approved_wrong_plan(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        svc.approve(req.request_id)
        # 属于 plan-1 的请求不应导致 plan-2 被判定为已批准。
        assert svc.is_approved("plan-2") is False

    def test_is_rejected(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        svc.reject(req.request_id)
        # fail-closed：审批拒绝（status=REJECTED）后，is_rejected 应返回 True。
        assert svc.is_rejected("plan-1") is True

    def test_get_pending_approval_info(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node)
        info = svc.get_pending_approval_info("plan-1")
        assert info is not None
        assert info["request_id"] == req.request_id
        assert info["status"] == "pending"

    def test_get_pending_approval_info_not_found(self):
        svc = ApprovalService()
        assert svc.get_pending_approval_info("nonexistent") is None


# ---------------------------------------------------------------------------
# ApprovalService — workflow management
# ---------------------------------------------------------------------------
class TestApprovalWorkflowManagement:
    def test_remove_pending_workflow(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        node = _make_node()
        plan = _make_plan()
        with patch.object(svc, "_persist_request_to_db"):
            req = svc.create_approval_request("plan-1", node, plan=plan)
        removed = svc.remove_pending_workflow(req.request_id)
        assert removed is not None
        assert svc.get_pending_workflow(req.request_id) is None

    def test_remove_nonexistent_workflow(self):
        svc = ApprovalService()
        assert svc.remove_pending_workflow("nonexistent") is None


def test_ai_workflow_approval_persists_valid_actor_flow_and_audit(monkeypatch, tmp_path):
    db_file = tmp_path / "approval-persistence.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    from sqlalchemy import text

    import app.db as db_mod
    from app.db.base import Base
    from app.db.models.approval import (
        ApprovalFlow,
        ApprovalFlowNode,
        ApprovalRecord,
    )
    from app.db.models.approval import (
        ApprovalRequest as ApprovalRequestModel,
    )
    from app.db.models.user import User
    from app.db.session import get_db

    tables = [
        User.__table__,
        ApprovalFlow.__table__,
        ApprovalFlowNode.__table__,
        ApprovalRequestModel.__table__,
        ApprovalRecord.__table__,
    ]
    db_mod.dispose_and_recreate_engine()
    Base.metadata.create_all(db_mod.engine, tables=tables)
    with db_mod.engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE ai_action_audit ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
                "actor TEXT, action TEXT NOT NULL, payload TEXT)"
            )
        )
    try:
        with get_db() as db:
            user = User(
                username="crud-approver",
                password="test-only",
                display_name="CRUD 审批人",
                role="user",
                is_active=True,
            )
            db.add(user)
            db.flush()
            user_id = user.id

        svc = ApprovalService()
        node = _make_node(
            tool_id="business_db",
            action="write",
            params={
                "entity": "products",
                "operation": "create",
                "payload": {"product_name": "CHATCRUD-TEST"},
            },
        )
        plan = _make_plan([node])
        request = svc.create_approval_request(
            "plan-crud",
            node,
            runtime_context={"user_id": str(user_id)},
            plan=plan,
            require_persistence=True,
        )
        metadata = svc.get_request_metadata(request.request_id)
        assert metadata is not None
        assert metadata["applicant_id"] == user_id
        assert f"request_no={request.request_id}" in metadata["approval_path"]
        assert svc.attach_pending_agent_run(
            request.request_id,
            agent_run_id="run-crud-1",
            approved_step_id=node.node_id,
        )

        with get_db() as db:
            persisted = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request.request_id)
                .one()
            )
            assert persisted.flow_id > 0
            assert persisted.applicant_id == user_id
            assert persisted.current_node_id is None
            assert persisted.status == "pending"
            business_data = json.loads(persisted.business_data)
            assert business_data["agent_run_id"] == "run-crud-1"
            assert business_data["approved_step_id"] == node.node_id
            assert persisted.flow.flow_key == "ai-workflow-interactive"
            assert len(persisted.flow.nodes) == 1
            audit = db.execute(
                text(
                    "SELECT actor, action FROM ai_action_audit "
                    "WHERE action = 'approval.submit_ai_workflow'"
                )
            ).one()
            assert audit.actor == str(user_id)

        missing_actor_svc = ApprovalService()
        with pytest.raises(RuntimeError, match="未能持久化"):
            missing_actor_svc.create_approval_request(
                "plan-missing-actor",
                node,
                runtime_context={"user_id": "unknown-user"},
                plan=plan,
                require_persistence=True,
            )
        assert missing_actor_svc._pending_requests == {}
        assert missing_actor_svc._pending_workflows == {}
    finally:
        Base.metadata.drop_all(db_mod.engine, tables=list(reversed(tables)))
        db_mod.dispose_and_recreate_engine()


# ---------------------------------------------------------------------------
# ApprovalService — reload_config
# ---------------------------------------------------------------------------
class TestApprovalServiceReloadConfig:
    @patch("app.application.workflow.approval_service.reload_approval_config")
    def test_reload_config(self, mock_reload):
        mock_reload.return_value = MagicMock(enabled=True)
        svc = ApprovalService()
        svc.reload_config()
        mock_reload.assert_called_once()


# ---------------------------------------------------------------------------
# Module-level functions
# ---------------------------------------------------------------------------
class TestModuleLevelFunctions:
    @patch("app.application.workflow.approval_service._approval_service", None)
    @patch("app.application.workflow.approval_service.ApprovalService")
    def test_get_approval_service_creates_instance(self, mock_cls):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        # Reset module global
        import app.application.workflow.approval_service as mod

        mod._approval_service = None
        result = get_approval_service()
        assert result is mock_instance

    @patch("app.application.workflow.approval_service._approval_service")
    def test_get_approval_service_returns_existing(self, mock_svc):
        import app.application.workflow.approval_service as mod

        mod._approval_service = mock_svc
        result = get_approval_service()
        assert result is mock_svc

    @patch("app.db.session.get_db")
    def test_process_approval_timeouts_db_error(self, mock_get_db):
        mock_get_db.side_effect = RuntimeError("db error")
        result = process_approval_timeouts()
        assert result["success"] is False

    @patch("app.db.session.get_db")
    def test_process_approval_timeouts_no_expired(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = mock_db
        result = process_approval_timeouts()
        assert result["success"] is True
        assert result["processed"] == 0

    @patch("app.application.workflow.approval_service._approval_service")
    def test_reload_approval_service(self, mock_svc):
        import app.application.workflow.approval_service as mod

        mod._approval_service = mock_svc
        result = reload_approval_service()
        mock_svc.reload_config.assert_called_once()
        assert result is mock_svc


# ---------------------------------------------------------------------------
# ApprovalService — is_approval_enabled
# ---------------------------------------------------------------------------
class TestIsApprovalEnabled:
    def test_enabled(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True)
        assert svc.is_approval_enabled() is True

    def test_disabled(self):
        svc = ApprovalService()
        svc._config = MagicMock(enabled=False)
        assert svc.is_approval_enabled() is False
