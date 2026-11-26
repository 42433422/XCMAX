from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, ToolCall
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _invoke(bridge, token, name, arguments):
    if name == "execute_action":
        description = bridge.invoke(
            token,
            "capability_describe",
            {
                "tool_id": arguments["tool_id"],
                "action": arguments["action"],
            },
        )
        arguments = {"schema_digest": description["capability"]["schema_digest"], **arguments}
    return bridge.invoke(token, name, arguments)


def _bind_goal(run):
    run.metadata["runtime_type"] = "xiaox"
    contract = build_goal_contract(run)
    run.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])


@pytest.fixture
def bridge_setup(trusted_actor, monkeypatch, tmp_path):
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["customer.edit", "customer.view"])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    run = AgentRun(user_id=str(actor.user_id), message="执行企业任务", status="running")
    run.metadata["runtime_context"] = actor.context
    _bind_goal(run)
    repository.save(run)
    store = XiaoxBindingStore(repository)
    grant = store.create(run.run_id)
    orchestrator = AgentOrchestrator(
        repository=repository, tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute)
    )
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    return SimpleNamespace(
        actor=actor, store=store, run=run, grant=grant, bridge=XiaoxToolBridge(store, orchestrator)
    )


def test_authority_arguments_and_unbound_tools_never_publish_tasks(bridge_setup):
    setup = bridge_setup
    for params in (
        {"tenant_id": 999},
        {"approved": True},
        {"_actor_authorization": {}},
        {"idempotency_key": "replace"},
    ):
        with pytest.raises(XiaoxBindingError) as error:
            _invoke(
                setup.bridge,
                setup.grant.mcp_token,
                "execute_action",
                {
                    "call_id": "attack",
                    "tool_id": "customers",
                    "action": "query",
                    "params": params,
                },
            )
        assert error.value.code == "identity_override"
    with pytest.raises(XiaoxBindingError):
        _invoke(
            setup.bridge,
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": "recursive",
                "tool_id": "aiopen",
                "action": "chat",
                "params": {"message": "re-enter"},
            },
        )
    assert setup.store.get(setup.run.run_id).metadata["calls"] == {}
    assert len(setup.store.repository.list_recent()) == 1


def test_write_uses_original_approval_and_stable_task_for_repeated_model_calls(bridge_setup):
    setup = bridge_setup
    args = {
        "call_id": "first",
        "tool_id": "customers",
        "action": "create",
        "params": {"unit_name": "fixture"},
    }
    first = _invoke(setup.bridge, setup.grant.mcp_token, "execute_action", args)
    assert first["status"] == "waiting_user"
    assert first["pending_approval"] is True
    assert first["verified"] is False
    assert first["tool_calls"] == []
    again = _invoke(
        setup.bridge, setup.grant.mcp_token, "execute_action", {**args, "call_id": "fresh-model-id"}
    )
    assert again["task_id"] == first["task_id"]
    assert again["run_id"] == first["run_id"]
    assert len(setup.store.repository.list_recent()) == 2
    child = setup.store.repository.get(first["run_id"])
    assert child.metadata["runtime_context"]["parent_run_id"] == setup.run.run_id
    assert child.metadata["plan"]["nodes"][0]["params"] == args["params"]
    card = first["approval_card"]
    assert card["kind"] == "approval_pending"
    assert card["run_id"] == child.run_id and card["plan_id"] == child.plan_id
    assert card["blocking_nodes"] == [child.steps[0].node_id]
    assert card["approval_nodes"][0]["step_id"] == child.steps[0].step_id
    assert card["approval_nodes"][0]["params"] == args["params"]
    assert "approval_grant" not in card


def test_changed_write_cannot_reuse_an_approved_request_identity(bridge_setup):
    setup = bridge_setup
    args = {
        "call_id": "original",
        "tool_id": "customers",
        "action": "create",
        "params": {"unit_name": "fixture"},
    }
    first = _invoke(setup.bridge, setup.grant.mcp_token, "execute_action", args)
    with pytest.raises(XiaoxBindingError) as error:
        _invoke(
            setup.bridge,
            setup.grant.mcp_token,
            "execute_action",
            {**args, "params": {"unit_name": "different-object"}},
        )
    assert error.value.code == "call_conflict"
    assert len(setup.store.repository.list_recent()) == 2
    child = setup.store.repository.get(first["run_id"])
    assert child.steps[0].params == args["params"]


def test_dynamic_observations_use_reopened_sql_child_evidence(bridge_setup, monkeypatch):
    setup = bridge_setup
    run = AgentRun(user_id=setup.run.user_id, message="查询产品并按结果继续查询", status="running")
    run.metadata["runtime_context"] = setup.actor.context
    _bind_goal(run)
    setup.store.repository.save(run)
    grant = setup.store.create(run.run_id)
    dispatched = []

    def dispatch(tool, action, params):
        dispatched.append((tool, action, params["keyword"]))
        return {"success": True, "data": [{"model_number": params["keyword"]}]}

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    first = _invoke(
        setup.bridge,
        grant.mcp_token,
        "execute_action",
        {
            "tool_id": "customers",
            "action": "query",
            "params": {"keyword": "first"},
            "call_id": "first",
        },
    )
    assert first["verified"] is True
    setup.store.close(run.run_id, "waiting_user")
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=setup.actor.factory))
    renewed = reopened.create(run.run_id)
    bridge = XiaoxToolBridge(reopened, setup.bridge.orchestrator)
    second = _invoke(
        bridge,
        renewed.mcp_token,
        "execute_action",
        {
            "tool_id": "customers",
            "action": "query",
            "params": {"keyword": "second"},
            "call_id": "second",
        },
    )
    assert second["verified"] is True and second["run_id"] != first["run_id"]
    snapshot = reopened.receipt_snapshot(run.run_id)
    assert len(snapshot) == 2 and all(row["receipt"]["verified"] for row in snapshot)
    assert dispatched == [("customers", "query", "first"), ("customers", "query", "second")]


def test_acknowledged_child_completion_uses_original_independent_readback(
    bridge_setup, monkeypatch, tmp_path
):
    import copy
    import sqlite3

    from app.application.agent_orchestrator.verification_recovery import (
        reverify_run,
        verification_can_finalize,
    )

    setup = bridge_setup
    source = tmp_path / "acknowledged-result.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE result (request_id TEXT PRIMARY KEY, completed INTEGER)")
        db.execute("INSERT INTO result VALUES ('original-request', 0)")
    dispatched = []

    def dispatch(*args):
        dispatched.append(args)
        return {"success": False, "execution_state": "pending", "request_id": "original-request"}

    def readback(**kwargs):
        with sqlite3.connect(source) as db:
            row = db.execute(
                "SELECT completed FROM result WHERE request_id = ?",
                (kwargs["output"]["request_id"],),
            ).fetchone()
        ready = row == (1,)
        return {
            "status": "verified" if ready else "inconclusive",
            "code": "original_result_observed" if ready else "original_result_pending",
            "checks": [
                {
                    "check_id": "original_request",
                    "status": "passed" if ready else "unavailable",
                    "source": "independent_sqlite_connection",
                    "evidence": {"request_id": "original-request", "completed": ready},
                }
            ],
        }

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        readback,
    )
    args = {"tool_id": "customers", "action": "query", "params": {}, "call_id": "original"}
    first = _invoke(setup.bridge, setup.grant.mcp_token, "execute_action", args)
    assert first["status"] == "running" and first["verified"] is False
    with pytest.raises(CodexBindingError) as error:
        _invoke(setup.bridge, setup.grant.mcp_token, "execute_action", {**args, "call_id": "next"})
    assert error.value.code == "call_in_progress"
    original = copy.deepcopy(setup.store.repository.get(first["run_id"]).tool_calls[0].output)
    with sqlite3.connect(source) as db:
        db.execute("UPDATE result SET completed = 1 WHERE request_id = 'original-request'")
    observed = reverify_run(setup.store.repository, first["run_id"])
    assert verification_can_finalize(observed)
    setup.bridge.orchestrator.retry_run(first["run_id"], requested_by=setup.run.user_id)
    completed = setup.bridge.orchestrator.execute_dispatched_run(first["run_id"])
    assert completed.status == "completed"
    receipt = _invoke(setup.bridge, setup.grant.mcp_token, "task_evidence", {"call_id": "original"})
    assert receipt["verified"] is True and receipt["status"] == "completed"
    assert receipt["run_id"] == first["run_id"] and receipt["task_id"] == first["task_id"]
    assert receipt["tool_calls"][0]["output"] == original
    assert len(dispatched) == 1 and len(completed.tool_calls) == 1


def test_read_executes_controlled_chain_and_replays_persisted_receipt(bridge_setup, monkeypatch):
    setup = bridge_setup
    calls = []

    def dispatch(tool, action, params):
        from app.infrastructure.tenant_scope import current_tenant_id

        assert current_tenant_id() == setup.actor.tenant_id
        assert params["_runtime_context"]["parent_run_id"] == setup.run.run_id
        calls.append((tool, action))
        return {"success": True, "data": [{"model_number": "fixture", "price": 12}]}

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    args = {
        "call_id": "read",
        "tool_id": "customers",
        "action": "query",
        "params": {"keyword": "fixture"},
    }
    receipt = _invoke(setup.bridge, setup.grant.mcp_token, "execute_action", args)
    child = setup.store.repository.get(receipt["run_id"])
    assert receipt["verified"] is True, (
        receipt,
        child.error,
        [s.output for s in child.steps],
        calls,
    )
    reopened = XiaoxToolBridge(
        XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=setup.actor.factory))
    )
    replay = _invoke(reopened, setup.grant.mcp_token, "execute_action", args)
    assert replay["run_id"] == receipt["run_id"]
    assert replay["verified"] is True
    assert calls == [("customers", "query")]


def test_lost_claim_without_child_cannot_be_replayed(bridge_setup):
    setup = bridge_setup
    setup.store.claim_call(
        setup.run.run_id,
        "lost",
        tool_id="customers",
        action="create",
        params={"unit_name": "fixture"},
        read_only=False,
        generation=setup.grant.binding.metadata["generation"],
    )
    active = _invoke(setup.bridge, setup.grant.mcp_token, "task_evidence", {"call_id": "lost"})
    assert active["status"] == "claimed"
    assert active["in_progress"] is True
    setup.store.close(setup.run.run_id, "interrupted")
    result = setup.store.receipt_snapshot(setup.run.run_id)[0]["receipt"]
    assert result["outcome"] == "unknown"
    with pytest.raises(XiaoxBindingError) as error:
        setup.store.create(setup.run.run_id)
    assert error.value.code == "reconciliation_required"
    assert len(setup.store.repository.list_recent()) == 1


@pytest.mark.parametrize("bound", [False, True])
def test_original_child_receipt_never_follows_a_replacement_attempt(bridge_setup, bound):
    from app.db.models.agent import AgentRunRecord
    from app.infrastructure.codex.receipts import read_call_receipt

    setup = bridge_setup
    receipt = _invoke(
        setup.bridge,
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "original",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    original = setup.store.repository.get(receipt["run_id"])
    replacement = copy.deepcopy(original)
    replacement.run_id = AgentRun(user_id=original.user_id, message="replacement").run_id
    replacement.metadata["task_context"]["attempt"] = 2
    setup.store.repository.save(replacement)
    with setup.actor.factory.begin() as db:
        db.query(AgentRunRecord).filter_by(run_id=original.run_id).delete()
    if not bound:
        setup.store.update(
            setup.run.run_id,
            lambda _run, metadata: metadata["calls"]["original"].update(child_run_id=""),
        )
    reopened = CodexBindingStore(SQLAlchemyAgentRunRepository(session_factory=setup.actor.factory))
    binding = reopened.get(setup.run.run_id)
    call = binding.metadata["calls"]["original"]
    result = read_call_receipt(reopened, binding, call)
    assert result["status"] == "unknown"
    assert result["run_id"] == (original.run_id if bound else "")
    assert result["reconciliation_required"] is True and result["retryable"] is False
    assert reopened.repository.get(replacement.run_id).status == "waiting_user"
    assert reopened.get(setup.run.run_id).metadata["calls"]["original"] == call
    snapshot = reopened.receipt_snapshot(setup.run.run_id)[0]
    assert snapshot["receipt"]["status"] == "unknown"
    assert snapshot["child_run_id"] == call["child_run_id"]
    assert reopened.get(setup.run.run_id).run.metadata["non_retryable"] is True


@pytest.mark.parametrize("field", ["run_id", "task_id"])
@pytest.mark.parametrize("missing", [False, True])
def test_receipt_identity_mismatch_cannot_release_original_reservation(
    bridge_setup, field, missing
):
    setup = bridge_setup
    setup.store.update(
        setup.run.run_id,
        lambda parent, _metadata: parent.metadata.update(ai_cost_budget_units=10),
    )
    receipt = _invoke(
        setup.bridge,
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "original",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    before = setup.store.get(setup.run.run_id)
    foreign = {**receipt, "status": "completed", "ai_cost_units_total": 4}
    if missing:
        foreign.pop(field)
    else:
        foreign[field] = "another-original-identity"
    with pytest.raises(CodexBindingError) as error:
        setup.store.record_call(
            setup.run.run_id, "original", child_run_id=receipt["run_id"], receipt=foreign
        )
    assert error.value.code == "evidence_mismatch"
    after = setup.store.get(setup.run.run_id)
    assert after.metadata["calls"] == before.metadata["calls"]
    assert after.run.metadata["reserved_cost_units"] == 10
    assert after.run.metadata["ai_cost_units_total"] == before.run.metadata.get(
        "ai_cost_units_total", 0
    )


def test_lost_child_binding_ack_recovers_only_original_sql_admission(bridge_setup):
    setup = bridge_setup
    original = _invoke(
        setup.bridge,
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "original",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    setup.store.update(
        setup.run.run_id,
        lambda _run, metadata: metadata["calls"]["original"].update(child_run_id=""),
    )
    reopened = CodexBindingStore(SQLAlchemyAgentRunRepository(session_factory=setup.actor.factory))
    recovered = reopened.receipt_snapshot(setup.run.run_id)[0]
    assert recovered["child_run_id"] == recovered["receipt"]["run_id"] == original["run_id"]
    assert recovered["receipt"]["status"] == "waiting_user"
    assert recovered["receipt"]["pending_approval"] is True
    assert recovered["receipt"]["verified"] is False
    assert len(reopened.repository.list_recent()) == 2
    assert reopened.repository.get(original["run_id"]).tool_calls == []


@pytest.mark.parametrize("consumer", ["receipt", "browser", "artifact"])
def test_evidence_consumers_reject_an_unsupported_parent_binding(
    bridge_setup, monkeypatch, consumer
):
    from app.infrastructure.codex.receipts import (
        browser_action_receipts,
        read_action_artifact,
        read_call_receipt,
    )

    setup = bridge_setup
    original = _invoke(
        setup.bridge,
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "original",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    child = setup.store.repository.get(original["run_id"])
    context = {**child.metadata["runtime_context"], "run_id": child.run_id}
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        lambda: setup.store.repository,
    )
    setup.store.update(setup.run.run_id, lambda _run, metadata: metadata.update(version=2))
    binding = setup.store.get(setup.run.run_id)
    with pytest.raises(CodexBindingError) as error:
        if consumer == "receipt":
            read_call_receipt(setup.store, binding, binding.metadata["calls"]["original"])
        elif consumer == "browser":
            browser_action_receipts(context, "customers")
        else:
            read_action_artifact(f"/api/agent/runs/{child.run_id}/artifacts/original", context)
    assert error.value.code == "runtime_contract_unsupported"
    assert setup.store.repository.get(child.run_id).tool_calls == []


@pytest.mark.parametrize("claimed_success", [False, True])
def test_http_403_inside_transport_success_does_not_verify_business_success(
    bridge_setup, claimed_success
):
    setup = bridge_setup
    result = _invoke(
        setup.bridge,
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "write",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    child = setup.store.repository.get(result["run_id"])
    child.status = "completed"
    step = child.steps[0]
    step.status = "completed"
    step.output = {"success": claimed_success, "status_code": 403, "data": {"message": "denied"}}
    child.tool_calls.append(
        ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=step.params,
            status="completed",
            output=step.output,
        )
    )
    setup.store.repository.save(child)
    result = _invoke(setup.bridge, setup.grant.mcp_token, "task_evidence", {"call_id": "write"})
    assert result["verified"] is False
    # A definite denied receipt remains a recoverable failure. A contradictory
    # completed-write claim lacks proof of no effect and must never replay.
    assert result["status"] == ("unknown" if claimed_success else "failed")
    assert result["reconciliation_required"] is claimed_success


def test_draft_instructions_require_direct_delivery_without_internal_ids():
    from app.application.agent_runtime.chat import _INSTRUCTIONS
    from app.infrastructure.xiaox.tools import mcp_tool_definitions

    request_input = next(
        tool for tool in mcp_tool_definitions() if tool.name == "request_input"
    )
    # B1：行程、预算拆分等草案属于对话内交付，不能反复登记提问或索要内部 ID。
    assert "直接交付" in request_input.description
    assert "任务或目标内部 ID" in request_input.description
    assert "直接交付" in _INSTRUCTIONS
    assert "不得为对话内修订索要任务或目标内部 ID" in _INSTRUCTIONS


def test_request_input_is_durable_and_blocks_additional_actions(bridge_setup):
    setup = bridge_setup
    result = _invoke(
        setup.bridge, setup.grant.mcp_token, "request_input", {"question": "请提供客户名称"}
    )
    assert result["needs_user_input"] is True
    assert (
        setup.store.get(setup.run.run_id).metadata["waiting_input"]["question"] == "请提供客户名称"
    )
    with pytest.raises(XiaoxBindingError) as error:
        _invoke(
            setup.bridge,
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": "read",
                "tool_id": "customers",
                "action": "query",
                "params": {},
            },
        )
    assert error.value.code == "waiting_user"


def test_employee_gate_cannot_be_lost_or_override_actor_permissions(bridge_setup):
    setup = bridge_setup
    setup.store.update(
        setup.run.run_id,
        lambda run, metadata: metadata["runtime_config"].update(gate_required=True),
    )
    args = {"call_id": "gated", "tool_id": "products", "action": "query", "params": {}}
    with pytest.raises(XiaoxBindingError) as error:
        _invoke(setup.bridge, setup.grant.mcp_token, "execute_action", args)
    assert error.value.code == "gate_required"
    setup.bridge.gate = lambda tool, action, params: {"ok": False, "reason": "workspace blocked"}
    with pytest.raises(XiaoxBindingError) as error:
        _invoke(setup.bridge, setup.grant.mcp_token, "execute_action", args)
    assert error.value.code == "gate_denied"
    setup.bridge.gate = lambda tool, action, params: {"ok": True}
    with pytest.raises(XiaoxBindingError) as error:
        _invoke(
            setup.bridge,
            setup.grant.mcp_token,
            "execute_action",
            {
                **args,
                "tool_id": "materials",
                "action": "list",
            },
        )
    assert error.value.code == "permission_denied"
    assert setup.store.get(setup.run.run_id).metadata["calls"] == {}


def test_private_bridge_rejects_a_valid_token_for_another_run(bridge_setup):
    setup = bridge_setup
    other = AgentRun(user_id=setup.run.user_id, message="another task", status="running")
    other.metadata["runtime_context"] = setup.actor.context
    _bind_goal(other)
    setup.store.repository.save(other)
    other_grant = setup.store.create(other.run_id)
    bridge = XiaoxToolBridge(
        setup.store,
        setup.bridge.orchestrator,
        gate=lambda *args: {"ok": True},
        run_id=setup.run.run_id,
    )
    with pytest.raises(XiaoxBindingError) as error:
        _invoke(bridge, other_grant.mcp_token, "request_input", {"question": "new question"})
    assert error.value.code == "scope_conflict"
    assert "waiting_input" not in setup.store.get(other.run_id).metadata


def test_waiting_approval_blocks_new_business_actions(bridge_setup):
    setup = bridge_setup
    _invoke(
        setup.bridge,
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "pending",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    with pytest.raises(XiaoxBindingError) as error:
        _invoke(
            setup.bridge,
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": "second",
                "tool_id": "customers",
                "action": "query",
                "params": {},
            },
        )
    assert error.value.code == "waiting_user"
    assert len(setup.store.repository.list_recent()) == 2


def test_receipt_cannot_substitute_different_parameters(bridge_setup):
    setup = bridge_setup
    receipt = _invoke(
        setup.bridge,
        setup.grant.mcp_token,
        "execute_action",
        {
            "call_id": "write",
            "tool_id": "customers",
            "action": "create",
            "params": {"unit_name": "fixture"},
        },
    )
    child = setup.store.repository.get(receipt["run_id"])
    child.steps[0].params = {"unit_name": "changed-after-approval"}
    child.metadata["plan"]["nodes"][0]["params"] = child.steps[0].params
    setup.store.repository.save(child)
    with pytest.raises(XiaoxBindingError) as error:
        _invoke(setup.bridge, setup.grant.mcp_token, "task_evidence", {"call_id": "write"})
    assert error.value.code == "evidence_mismatch"


def test_revoke_after_child_is_saved_prevents_dispatch(bridge_setup, monkeypatch):
    setup = bridge_setup
    original = setup.store.record_call
    dispatched = []

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("child_run_id") and kwargs.get("receipt") is None:
            setup.store.close(setup.run.run_id, "cancelled")
        return result

    monkeypatch.setattr(setup.store, "record_call", record)
    monkeypatch.setattr(setup.bridge.orchestrator, "execute_dispatched_run", dispatched.append)
    with pytest.raises(XiaoxBindingError):
        _invoke(
            setup.bridge,
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": "read",
                "tool_id": "customers",
                "action": "query",
                "params": {},
            },
        )
    assert dispatched == []
    call = setup.store.get(setup.run.run_id).metadata["calls"]["read"]
    assert setup.store.repository.get(call["child_run_id"]).status == "cancelled"


def test_official_sdk_mcp_endpoint_rejects_wrong_audience_and_lists_tools(bridge_setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.infrastructure.xiaox.mcp_server import MCP_PATH, router
    from app.infrastructure.xiaox.tool_names import XIAOX_TOOL_NAMES

    setup = bridge_setup
    app = FastAPI()
    app.state.xiaox_binding_store = setup.store
    app.state.xiaox_tool_bridge = setup.bridge
    app.state.xiaox_run_id = setup.run.run_id
    setup.bridge.run_id = setup.run.run_id
    app.include_router(router)
    headers = {
        "Authorization": f"Bearer {setup.grant.mcp_token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    with TestClient(app) as client:
        denied = client.post(
            MCP_PATH,
            headers={**headers, "Authorization": f"Bearer {setup.grant.model_token}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert denied.status_code == 403
        response = client.post(
            MCP_PATH, headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert response.status_code == 200, response.text
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == set(
            XIAOX_TOOL_NAMES
        )
        # MCP SDK v2 removed automatic lowlevel tool-schema validation.
        # Extra model-supplied authority fields must fail before the business bridge.
        malformed = client.post(
            MCP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "execute_action",
                    "arguments": {
                        "tool_id": "customers",
                        "action": "create",
                        "call_id": "tampered",
                        "params": {"unit_name": "fixture"},
                        "approved": True,
                    },
                },
            },
        )
        assert malformed.status_code == 200
        assert malformed.json()["result"]["isError"] is True
        assert malformed.json()["result"]["structuredContent"]["error_code"] == "invalid_arguments"
        assert setup.store.get(setup.run.run_id).metadata["calls"] == {}
        result = client.post(
            MCP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "request_input", "arguments": {"question": "请提供日期"}},
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["result"]["structuredContent"]["needs_user_input"] is True


def test_private_mcp_initialize_and_list_cannot_borrow_another_run_token(bridge_setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.infrastructure.xiaox.mcp_server import MCP_PATH, router

    setup = bridge_setup
    other = AgentRun(user_id=setup.run.user_id, message="another task", status="running")
    other.metadata["runtime_context"] = setup.actor.context
    _bind_goal(other)
    setup.store.repository.save(other)
    token = setup.store.create(other.run_id).mcp_token
    app = FastAPI()
    app.state.xiaox_binding_store = setup.store
    app.state.xiaox_tool_bridge = XiaoxToolBridge(setup.store, run_id=setup.run.run_id)
    app.state.xiaox_run_id = setup.run.run_id
    app.include_router(router)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    with TestClient(app) as client:
        for method in ("initialize", "tools/list"):
            response = client.post(
                MCP_PATH, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method}
            )
            assert response.status_code == 403
            assert response.json()["error_code"] == "scope_conflict"
        del app.state.xiaox_run_id
        response = client.post(
            MCP_PATH, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert response.status_code == 503
