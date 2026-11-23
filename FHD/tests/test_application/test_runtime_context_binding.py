import pytest

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_models import AgentRun
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize("revision", [0, 7])
def test_tool_runtime_preserves_authenticated_conversation_revision(trusted_actor, revision):
    from app.application.agent_runtime.gateway import _trusted_context
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError

    actor = trusted_actor()
    context = {
        **actor.context,
        "conversation_id": "original-chat",
        "_conversation_revision": revision,
        "turn_id": "host-original-turn",
    }
    runtime, owner = _trusted_context(context)
    assert owner == str(actor.user_id)
    assert type(runtime["_conversation_revision"]) is int
    assert runtime["_conversation_revision"] == revision
    assert runtime["_actor_authorization"] == context["_actor_authorization"]
    assert runtime["_actor_authorization"] is not context["_actor_authorization"]


def test_unbound_tool_context_cannot_supply_conversation_revision():
    from app.application.agent_runtime.gateway import _trusted_context
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError

    with pytest.raises(AgentModAuthorizationError):
        _trusted_context({"conversation_id": "claimed-chat", "_conversation_revision": 7})


def test_revoked_actor_cannot_forward_conversation_revision(trusted_actor):
    from app.application.agent_runtime.gateway import _trusted_context
    from app.db.models.user import User
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError

    actor = trusted_actor()
    with actor.factory.begin() as db:
        db.get(User, actor.user_id).is_active = False
    with pytest.raises(AgentModAuthorizationError):
        _trusted_context(
            {**actor.context, "_conversation_revision": 0, "turn_id": "host-original-turn"}
        )


@pytest.mark.parametrize(
    "method,status",
    [("resume_run", "paused"), ("stage_resume_run", "paused"), ("retry_run", "failed")],
)
def test_continuation_rejects_tenant_change_before_state_or_command_writes(method, status):
    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id="owner", message="task", status=status)
    run.metadata["runtime_context"] = {"tenant_id": "1"}
    repository.save(run)
    before = repository.get(run.run_id).to_dict()
    orchestrator = AgentOrchestrator(repository=repository)
    with pytest.raises(ValueError, match="租户"):
        getattr(orchestrator, method)(run.run_id, runtime_context={"tenant_id": "2"})
    assert repository.get(run.run_id).to_dict() == before
    assert repository.latest_task_control(run.run_id) is None
    assert len(repository.list_recent()) == 1


@pytest.mark.parametrize(
    "method,status",
    [
        ("resume_run", "paused"),
        ("stage_resume_run", "paused"),
        ("retry_run", "failed"),
    ],
)
@pytest.mark.parametrize(
    "key,original,replacement",
    [
        ("conversation_id", "old-chat", "other-chat"),
        ("session_id", "old-chat", "other-chat"),
        ("_conversation_revision", 7, 8),
        ("local_user_id", 17, 18),
        ("workspace_id", "original-task", "other-workspace"),
    ],
)
@pytest.mark.parametrize("previously_bound", [False, True])
def test_continuation_cannot_replace_or_invent_history_identity(
    method,
    status,
    key,
    original,
    replacement,
    previously_bound,
):
    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id="owner", message="stored history", status=status)
    run.metadata["runtime_context"] = {key: original} if previously_bound else {}
    repository.save(run)
    before = repository.get(run.run_id).to_dict()
    with pytest.raises(ValueError, match="会话"):
        getattr(AgentOrchestrator(repository=repository), method)(
            run.run_id,
            runtime_context={key: replacement},
        )
    assert repository.get(run.run_id).to_dict() == before
    assert repository.latest_task_control(run.run_id) is None


@pytest.mark.parametrize("original", [{}, {"_conversation_revision": 7}])
def test_approval_and_clarification_cannot_adopt_a_new_revision_after_clear(original):
    from app.application.agent_orchestrator.tool_permission import overlay_resume_context

    with pytest.raises(ValueError, match="历史版本"):
        overlay_resume_context(original, {"_conversation_revision": 8})
    assert overlay_resume_context(original, {"user_note": "continue"}) == {
        **original,
        "user_note": "continue",
    }


@pytest.mark.parametrize(
    "metadata",
    [
        {"non_retryable": True},
        {"recovery": {"state": "manual_reconciliation_required"}},
    ],
)
def test_internal_retry_cannot_replay_unreconciled_work(monkeypatch, metadata):
    from unittest.mock import Mock

    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id="owner", message="external write", status="blocked", metadata=metadata)
    repository.save(run)
    before = repository.get(run.run_id).to_dict()
    orchestrator = AgentOrchestrator(repository=repository)
    start = Mock(return_value=AgentRun(user_id="owner", message="duplicate", status="running"))
    assert not hasattr(orchestrator, "start_run")
    monkeypatch.setattr(orchestrator, "start_run_from_plan", start)
    with pytest.raises(ValueError, match="核对"):
        orchestrator.retry_run(run.run_id, requested_by="owner", auto_execute=False)
    start.assert_not_called()
    assert repository.get(run.run_id).to_dict() == before
    assert len(repository.list_recent()) == 1


@pytest.mark.parametrize("method", ["resume_run", "stage_resume_run"])
def test_paused_unreconciled_run_cannot_resume(monkeypatch, method):
    from unittest.mock import Mock

    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id="owner", message="unknown write", status="paused")
    run.metadata["recovery"] = {"state": "manual_reconciliation_required"}
    repository.save(run)
    before = repository.get(run.run_id).to_dict()
    orchestrator = AgentOrchestrator(repository=repository)
    execute = Mock()
    monkeypatch.setattr(orchestrator, "_execute_with_durable_lease", execute)
    with pytest.raises(ValueError, match="核对"):
        getattr(orchestrator, method)(run.run_id, requested_by="owner")
    execute.assert_not_called()
    assert repository.get(run.run_id).to_dict() == before
    assert repository.latest_task_control(run.run_id) is None
