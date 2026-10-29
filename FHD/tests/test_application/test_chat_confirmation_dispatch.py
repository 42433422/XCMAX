"""Confirmation/cancellation must reach the scoped workflow, never an intent guess."""

import logging
from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from app.application.agent_task_context import scoped_conversation_user_id
from app.application.ai_chat.workflow_session import WorkflowSession
from app.application.normal_chat.dispatch import dispatch_read, dispatch_read_async
from app.application.normal_chat_dispatch import build_clarify_response_dict
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.domain.conversation.services.chat_tool_intent import (
    looks_like_explicit_workflow_tool_intent,
)


def ports(pending, route):
    return {
        "request": None,
        "user_id": "raw-body-id",
        "route_message": route,
        "has_pending_workflow": lambda key: key in pending,
        "explicit_workflow_intent": looks_like_explicit_workflow_tool_intent,
        "scope": lambda request: nullcontext(),
        "handlers": {"clarify": build_clarify_response_dict},
        "logger": logging.getLogger(__name__),
    }


def wrong_route(_):
    return {"intent": "clarify", "slots": {"question": "您是想开发货单吗？"}}


@pytest.mark.parametrize("control", ["确认", "取消", "确认执行", "继续", "YES!", "停止。"])
@pytest.mark.parametrize("has_pending", [False, True])
def test_sync_control_never_reaches_classifier(control, has_pending):
    pending = {"chat:scoped": object()} if has_pending else {}
    route = MagicMock(side_effect=wrong_route)
    assert dispatch_read(control, **ports(pending, route)) is None
    route.assert_not_called()


@pytest.mark.asyncio
async def test_two_successive_scoped_plans_keep_confirmation_and_cancellation():
    ctx = {"local_user_id": 2, "tenant_id": 1, "session_id": "same", "mod_id": "mod-a"}
    key = scoped_conversation_user_id("raw-body-id", ctx)
    pending = {}
    callbacks = MagicMock()
    callbacks._hydrate_pending_workflow.return_value = False
    callbacks._run_workflow_with_state_updates.return_value = (object(), {})
    callbacks._format_workflow_run_response.return_value = {"success": True, "response": "done"}
    callbacks._persist_plan_state.return_value = True
    session = WorkflowSession(pending, callbacks)
    classified = []

    async def route(text):
        classified.append(text)
        return wrong_route(text)

    for number, control in [(1, "确认"), (2, "取消")]:
        pending[key] = {
            "plan": PlanGraph(
                plan_id=f"plan-{number}",
                intent="business_db_write",
                nodes=[
                    WorkflowNode(
                        "n1", "customers", "create", params={"unit_name": f"synthetic-{number}"}
                    )
                ],
            ),
            "runtime_context": dict(ctx),
        }
        assert await dispatch_read_async(control, **ports(pending, route)) is None
        handled, response = session.resume_pending_dynamic_workflow(key, control, control, ctx)
        assert handled and response["success"]
        assert key not in pending
    assert classified == []
    callbacks._run_workflow_with_state_updates.assert_called_once()
    assert callbacks._persist_plan_state.call_args.kwargs["status"] == "cancelled"


@pytest.mark.parametrize(
    "changed", [{"session_id": "other"}, {"tenant_id": 2}, {"mod_id": "mod-b"}]
)
def test_control_cannot_select_other_scopes_pending_plan(changed):
    ctx = {"local_user_id": 2, "tenant_id": 1, "session_id": "same", "mod_id": "mod-a"}
    original_key = scoped_conversation_user_id("raw-body-id", ctx)
    pending = {
        original_key: {
            "plan": PlanGraph(plan_id="original", intent="business_db_write"),
            "runtime_context": ctx,
        }
    }
    callbacks = MagicMock()
    callbacks._hydrate_pending_workflow.return_value = False
    context = {**ctx, **changed}
    key = scoped_conversation_user_id("raw-body-id", context)
    route = MagicMock(side_effect=wrong_route)
    assert dispatch_read("确认", **ports(pending, route)) is None
    handled, response = WorkflowSession(pending, callbacks).resume_pending_dynamic_workflow(
        key, "确认", "确认", context
    )
    assert handled and "没有待确认" in response["response"]
    assert original_key in pending
    callbacks._run_workflow_with_state_updates.assert_not_called()
    route.assert_not_called()


@pytest.mark.parametrize("control", ["确认", "取消"])
def test_missing_or_no_longer_hydratable_plan_is_explicit_not_a_new_intent(control):
    callbacks = MagicMock()
    callbacks._hydrate_pending_workflow.return_value = False
    ctx = {"local_user_id": 2, "tenant_id": 1, "session_id": "expired-or-revoked"}
    key = scoped_conversation_user_id("raw-body-id", ctx)
    route = MagicMock(side_effect=wrong_route)
    assert dispatch_read(control, **ports({}, route)) is None
    handled, response = WorkflowSession({}, callbacks).resume_pending_dynamic_workflow(
        key, control, control, ctx
    )
    assert handled and "没有待确认" in response["response"]
    callbacks._run_workflow_with_state_updates.assert_not_called()
    route.assert_not_called()


@pytest.mark.parametrize("control", ["确认", "取消"])
@pytest.mark.parametrize("expected", ["clicked-plan", "", None, 3])
def test_card_control_rejects_another_pending_plan_before_any_effect(control, expected):
    callbacks = MagicMock()
    callbacks._hydrate_pending_workflow.return_value = False
    current = {"plan": PlanGraph(plan_id="newer-plan", intent="write")}
    pending = {"user": current}
    handled, response = WorkflowSession(pending, callbacks).resume_pending_dynamic_workflow(
        "user", control, control, {"expected_workflow_plan_id": expected}
    )
    assert handled and response["success"] is False
    assert response["data"]["action"] == "workflow_confirmation_stale"
    assert pending["user"] is current
    callbacks._run_workflow_with_state_updates.assert_not_called()
    callbacks._persist_plan_state.assert_not_called()
    callbacks._continue_after_clarification.assert_not_called()


@pytest.mark.parametrize("control", ["确认", "取消"])
def test_card_control_rejects_expired_target_instead_of_acknowledging_it(control):
    callbacks = MagicMock()
    callbacks._hydrate_pending_workflow.return_value = False
    handled, response = WorkflowSession({}, callbacks).resume_pending_dynamic_workflow(
        "user",
        control,
        control,
        {"session_id": "original", "expected_workflow_plan_id": "expired-plan"},
    )
    assert handled and response["success"] is False
    assert response["data"]["action"] == "workflow_confirmation_stale"
    callbacks._run_workflow_with_state_updates.assert_not_called()


@pytest.mark.parametrize("control", ["确认", "取消"])
def test_matching_plan_only_card_preserves_confirmation_and_cancellation(control):
    callbacks = MagicMock()
    callbacks._run_workflow_with_state_updates.return_value = (object(), {})
    callbacks._format_workflow_run_response.return_value = {"success": True, "response": "done"}
    callbacks._persist_plan_state.return_value = True
    pending = {
        "user": {
            "plan": PlanGraph(
                plan_id="clicked-plan",
                intent="write",
                nodes=[
                    WorkflowNode("n1", "customers", "create", params={"unit_name": "synthetic"})
                ],
            )
        }
    }
    handled, response = WorkflowSession(pending, callbacks).resume_pending_dynamic_workflow(
        "user", control, control, {"expected_workflow_plan_id": "clicked-plan"}
    )
    assert handled and response["success"] is True
    assert "user" not in pending
    assert callbacks._run_workflow_with_state_updates.call_count == (control == "确认")
    assert callbacks._persist_plan_state.call_count == (control == "取消")
