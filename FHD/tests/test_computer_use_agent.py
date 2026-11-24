"""Real Agent approval/executor/dispatch/service chain; only browser and actor are fake."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import AgentOrchestrator, run_repository
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.computer_use import ComputerUseService
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize("enabled", [False, True])
def test_canonical_catalog_only_advertises_physical_actions_on_enabled_host(
    monkeypatch, enabled, trusted_actor
):
    from app.application.capability_catalog import authorized_tool_specs, workflow_registry
    from app.application.workflow.planning_graph_policy import filter_registry_for_profile

    monkeypatch.setenv("XCAGI_COMPUTER_USE_ENABLED", str(int(enabled)))
    actor = trusted_actor(role="admin", tier="admin")
    registry = workflow_registry()
    original = registry["desktop_automation"]["actions"]
    planner_registry = filter_registry_for_profile(registry, "pro_default")
    filtered = planner_registry["desktop_automation"]["actions"]
    offered = {
        action: spec
        for (tool, action), spec in authorized_tool_specs(actor.context).items()
        if tool == "desktop_automation"
    }
    physical = {"computer_observe", "computer_execute"}
    retained = {"list", "open_app", "computer_status", "computer_stop", "computer_result"}
    assert physical <= original.keys()
    assert retained <= offered.keys()
    assert physical.intersection(offered) == (physical if enabled else set())
    if enabled:
        assert offered["computer_execute"].risk == "high"
        assert offered["computer_execute"].idempotent is False
    assert all(filtered[action] == original[action] for action in filtered)


class FakeBrowser:
    def __init__(self, *, verified: bool, repository: InMemoryAgentRunRepository):
        self.verified = verified
        self.repository = repository
        self.calls = []

    def validate(self, steps, verification):
        assert steps == [{"action": "navigate", "url": "https://example.com"}]
        assert verification == {"kind": "url", "expected": "https://example.com/"}

    def execute(self, steps, verification, *, cancelled):
        from app.domain.browser_receipt import observed_assertion

        # Read the actual persisted run while executing, rather than injecting
        # an approval-shaped object into ComputerUseService._approved.
        runs = self.repository.list_recent(user_id="7")
        assert len(runs) == 1
        persisted = runs[0]
        assert persisted.status == "running"
        assert persisted.steps[0].status == "running"
        assert persisted.metadata["approval_receipt"]["approved_by"] == "reviewer"
        assert persisted.metadata["approval_receipt"]["step_id"] == persisted.steps[0].step_id
        assert cancelled() is False
        self.calls.append((copy.deepcopy(steps), copy.deepcopy(verification), persisted.run_id))
        return {
            "success": self.verified,
            "verified": self.verified,
            "executed": True,
            "steps_completed": 1,
            "status": "verified" if self.verified else "needs_verification",
            "verification": observed_assertion(
                verification,
                "https://example.com/" if self.verified else "https://example.com/unfinished",
            ),
        }


@pytest.fixture
def agent_setup(tmp_path, monkeypatch):
    from app.infrastructure.auth import agent_mod_scope
    from app.utils.path_io import path_utils

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite3"))
    monkeypatch.setenv("XCAGI_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("XCAGI_COMPUTER_USE_USER_ID", "7")
    monkeypatch.setenv("XCAGI_COMPUTER_USE_TENANT_ID", "9")
    monkeypatch.setenv("XCAGI_MCP_ENABLED", "0")
    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)
    monkeypatch.setattr(path_utils, "get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        agent_mod_scope,
        "_bound_actor",
        lambda context: SimpleNamespace(
            id=context["user_id"], tenant_id=context["tenant_id"], role="admin"
        ),
    )
    monkeypatch.setattr(
        "app.application.workflow.tool_profile.resolve_tool_execution_profile",
        lambda *_args, **_kwargs: "pro_default",
    )
    repository = InMemoryAgentRunRepository()
    monkeypatch.setattr(run_repository, "get_agent_run_repository", lambda: repository)
    # Same test isolation as test_application/test_agent_orchestrator.py: the
    # real executor runs in this interpreter so the fake browser is visible.
    executor = SimpleNamespace(execute=AgentToolExecutor().execute)
    agent = AgentOrchestrator(repository=repository, tool_executor=executor)
    return agent, repository


@pytest.mark.parametrize("verified", [True, False], ids=["verified", "needs_reconciliation"])
def test_computer_use_runs_only_after_persisted_agent_approval(
    agent_setup, tmp_path, monkeypatch, verified
):
    agent, repository = agent_setup
    browser = FakeBrowser(verified=verified, repository=repository)
    monkeypatch.setattr(ComputerUseService, "_browser", staticmethod(lambda: browser))
    params = {
        "request_id": "approved-browser-effect",
        "target": "browser",
        "steps": [{"action": "navigate", "url": "https://example.com"}],
        "verification": {"kind": "url", "expected": "https://example.com/"},
    }
    context = {
        "source": "computer-use-agent-contract",
        "user_id": "7",
        "tenant_id": "9",
        "_actor_authorization": {"test_actor": True},
    }
    plan = PlanGraph(
        plan_id="computer-use-approval-contract",
        intent="computer_use",
        nodes=[
            WorkflowNode(
                node_id="browser_task",
                tool_id="desktop_automation",
                action="computer_execute",
                params=copy.deepcopy(params),
                risk="high",
                idempotent=False,
            )
        ],
    )
    waiting = agent.start_run_from_plan(
        user_id="7", message="在授权浏览器完成任务并验证结果", plan=plan, runtime_context=context
    )
    assert waiting.status == "waiting_user", waiting.to_dict()
    assert waiting.steps[0].status == "waiting_user"
    assert waiting.tool_calls == [] and browser.calls == []
    service = ComputerUseService(tmp_path / "computer-use")
    execution_context = {**context, "run_id": waiting.run_id, "step_id": waiting.steps[0].step_id}
    premature = service.invoke("computer_execute", params, execution_context)
    assert premature["error_code"] == "computer_permission_denied"
    assert browser.calls == []

    completed = agent.continue_run(
        waiting.run_id, approved_by="reviewer", approved_step_id=waiting.steps[0].step_id
    )
    assert completed is not None
    assert len(browser.calls) == 1, completed.to_dict()
    assert completed.run_id == waiting.run_id == browser.calls[0][2]
    assert len(completed.tool_calls) == 1
    assert "step.approved" in [event.event_type for event in completed.events]
    if verified:
        assert completed.steps[0].output["verified"] is True
        assert completed.status == "completed", (
            completed.error,
            completed.final_output,
            [(event.event_type, event.data) for event in completed.events[-5:]],
        )
        assert completed.steps[0].status == completed.tool_calls[0].status == "completed"
        assert completed.final_output["node_outputs"]["browser_task"]["success"] is True
    else:
        assert completed.status != "completed"
        assert completed.steps[0].status == "failed"
        # The existing executor preserves uncertain physical effects in its
        # reconciliation envelope rather than reporting a completed step.
        evidence = completed.steps[0].output.get(
            "reconciliation_evidence", completed.steps[0].output
        )
        assert evidence["verified"] is False
        assert evidence["status"] == "needs_verification"
        assert evidence["steps_completed"] == 1
        assert completed.metadata["non_retryable"] is True
        assert completed.metadata["recovery"]["state"] == "manual_reconciliation_required"
        assert completed.steps[0].output["reconciliation_required"] is True

    # Retrying the continuation or replaying the original request retrieves the
    # saved evidence; neither path may repeat a physical browser input.
    again = agent.continue_run(waiting.run_id, approved_by="reviewer")
    assert again.run_id == waiting.run_id
    assert again.status == completed.status
    replay = service.invoke("computer_execute", params, execution_context)
    assert replay["replayed"] is True
    assert replay["verified"] is verified
    assert len(browser.calls) == 1
    stored = repository.get(waiting.run_id)
    assert stored.status == completed.status
    assert len(stored.tool_calls) == 1
