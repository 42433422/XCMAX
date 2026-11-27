"""Native tool constraints remain scoped to progress and original authorized routes."""

import json
from dataclasses import replace

import pytest

from app.application.agent_runtime.gateway import public_runtime_result
from app.domain.task_lifecycle.react_progress import CONTROL_KEY, ensure_control, receipt_facts
from tests.fixtures.xiaox_runtime import receipt
from tests.test_application.test_xiaox_model_gateway import gateway as gateway
from tests.test_application.test_xiaox_model_gateway import post


def repair(store, *, phase="host_tools"):
    state = ensure_control(store.binding.metadata, 24)
    state.update(
        repairing=True,
        strategy=1,
        repair={
            "tasks": [
                {
                    "evidence": "host_receipt" if phase == "host_tools" else "reply",
                    "completed": False,
                }
            ]
        },
    )
    return state


@pytest.mark.parametrize("has_progress", [False, True])
def test_required_tools_relax_only_after_host_evidence_changes(gateway, has_progress):
    client, store, calls, _, _ = gateway
    state = repair(store)
    if has_progress:
        row = receipt()
        store.binding.metadata["calls"] = {row["call_id"]: row}
        assert receipt_facts([row])
    response = post(
        client,
        tools=[
            {
                "type": "function",
                "name": "mcp__xcmax__capability_search",
                "parameters": {"type": "object"},
            }
        ],
    )
    assert response.status_code == 200, response.text
    body = json.loads(calls[0].content)
    assert (body.get("tool_choice") == "required") is not has_progress
    request = next(iter(store.binding.metadata["model_requests"].values()))
    assert request["execution_phase"] == "repair"
    assert state["facts"] == []  # Provider claims cannot change host evidence.


def test_text_revision_does_not_force_tool_calls(gateway):
    client, store, calls, _, _ = gateway
    repair(store, phase="reply")
    assert post(client).status_code == 200
    assert "tool_choice" not in json.loads(calls[0].content)


def test_physical_repair_requests_have_their_own_persisted_cap(gateway):
    client, store, calls, _, _ = gateway
    state = repair(store, phase="reply")
    state["limits"]["repair"] = 1
    store.binding.metadata["model_requests"] = {
        "old-repair": {"state": "completed", "execution_phase": "repair"}
    }
    result = post(client)
    assert result.status_code == 429 and calls == []
    assert store.binding.metadata["model_call_limit"]["reason"] == "react_repair_budget_exhausted"


def test_execution_cannot_spend_the_reserved_repair_requests(gateway):
    client, store, calls, _, _ = gateway
    state = ensure_control(store.binding.metadata, 24)
    assert state["limits"]["execution"] + state["limits"]["repair"] + 3 == 24
    store.binding.metadata["model_requests"] = {
        f"initial-{i}": {"state": "completed", "execution_phase": "execution"}
        for i in range(state["limits"]["execution"])
    }
    result = post(client)
    assert result.status_code == 429 and calls == []
    assert store.binding.metadata["model_call_limit"]["reason"] == "react_execution_phase_exhausted"


def test_recovery_uses_only_pre_authorized_compatible_route(gateway):
    client, store, calls, response, app = gateway
    state = repair(store, phase="reply")
    primary = app.state.xiaox_model_route
    alternate = replace(primary, model="authorized-alternate")
    third = replace(primary, model="another-authorized-alternate")
    state["route_switch_target"] = alternate.identity
    app.state.xiaox_model_routes = (primary, alternate, third)
    store.binding.metadata["runtime_config"]["authorized_model_routes"] = [
        primary.identity,
        alternate.identity,
        third.identity,
    ]
    response["model"] = alternate.response_model
    result = post(client)
    assert result.status_code == 200, result.text
    assert json.loads(calls[0].content)["model"] == alternate.model
    assert store.run.metadata["runtime_effective_model_route"] == alternate.identity
    from app.infrastructure.billing import model_usage as ledger

    ledger.set_model_wallet_balance("71", 100)  # The fixture asserts a fresh reservation.
    again = post(client)
    assert again.status_code == 200, again.text
    assert json.loads(calls[1].content)["model"] == alternate.model


def test_internal_memory_candidates_never_cross_public_result_boundary():
    result = public_runtime_result(
        {
            "runtime": "xiaox",
            "metadata": {
                CONTROL_KEY: {
                    "quarantined_outputs": [
                        {"channel": "memory_candidate", "output": "private claim"}
                    ]
                }
            },
        }
    )
    assert "private claim" not in json.dumps(result)
