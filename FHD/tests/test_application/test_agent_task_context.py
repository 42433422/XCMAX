from __future__ import annotations

from app.application.agent_orchestrator.chat_trace import _resolved_user_id
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_context import apply_task_context


def test_task_context_keeps_conversation_separate_from_task_and_tracks_workspace() -> None:
    run = AgentRun(user_id="7", message="请核对本月销售并提交报告")

    result = apply_task_context(
        run,
        {
            "conversation_id": "conv-sales",
            "workspace_id": "tenant-3-sales",
            "worktree_path": "/workspace/sales-report",
            "task_title": "本月销售报告",
        },
    )

    assert result["task_id"] == run.run_id
    assert result["conversation_id"] == "conv-sales"
    assert result["title"] == "本月销售报告"
    assert result["workspace_id"] == "tenant-3-sales"
    assert result["workspace_path"] == "/workspace/sales-report"
    assert result["isolation"] == "worktree"
    assert run.metadata["task_context"] == result


def test_explicit_business_task_and_turn_identity_survive_approval_attempts() -> None:
    first = AgentRun(user_id="7", message="新增客户")
    second = AgentRun(user_id="7", message="审批后继续")
    context = {
        "conversation_id": "conv-sales",
        "turn_id": "turn-create-customer",
        "task_id": "task-create-customer",
    }

    first_context = apply_task_context(first, context)
    second_context = apply_task_context(second, {**context, "task_attempt": 2})

    assert first_context["conversation_id"] == second_context["conversation_id"]
    assert first_context["task_id"] == second_context["task_id"]
    assert first_context["turn_id"] == second_context["turn_id"]
    assert second_context["attempt"] == 2


def test_authenticated_actor_owns_trace_instead_of_client_scoped_user_id() -> None:
    resolved = _resolved_user_id(
        runtime_context={"local_user_id": 73, "actor_id": 73},
        user_id="web_normal_untrusted-session",
    )

    assert resolved == "73"
