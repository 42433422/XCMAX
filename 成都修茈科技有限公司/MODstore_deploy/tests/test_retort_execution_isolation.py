"""SQL admission and workflow identity for private-feedback execution."""

import pytest

from modstore_server import retort_github_workspace as workspace
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.dot_ticket_dispatch import DoltIncidentContractError, _incident_prompt
from modstore_server.models import IncidentEvent, RetortEvolutionRun
from modstore_server.para_execution_isolation import HEADER_ONLY_PLATFORM_PROFILE
from tests import test_strategic_workspace_bridge as engineering

database = engineering.database
configured = engineering.configured
approved_workspace = engineering.workspace


@pytest.mark.parametrize("source", ["customer_feedback", "training_candidate"])
def test_private_feedback_requires_real_admission_and_keeps_original_workflow_identity(
    approved_workspace, monkeypatch, source
):
    state = approved_workspace
    request_id, protocol, effects = state.request_id, state.protocol, state.effects
    feedback = effects.pop("customer_feedback")
    effects[source] = feedback
    with state.factory() as db:
        event = IncidentEvent(
            event_type="ops.retort.evolution", source="retort", fingerprint=request_id
        )
        db.add(event)
        db.flush()
        event_id = event.id
        row = db.get(RetortEvolutionRun, request_id)
        row.event_id = event_id
        row.effects_json = json_dumps(effects)
        db.commit()
    monkeypatch.delenv("DEVFLEET_FORCE_OPENCODE")
    monkeypatch.delenv("MODSTORE_PARA_PLATFORM_POOL")
    assert workspace._ensure_runner(request_id, protocol, effects)["model_allocation"] == {
        "status": "waiting",
        "reason": "strategic_company_budget_binding_required",
    }
    assert not state.github.writes
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "1")
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_POOL", "1")
    # Isolated execution does not itself authorize company resources.
    assert workspace._ensure_runner(request_id, protocol, effects)["model_allocation"] == {
        "status": "waiting",
        "reason": "strategic_company_budget_binding_required",
    }
    assert not state.github.writes
    engineering.attach(state)
    admitted = workspace._ensure_runner(request_id, protocol, effects)
    assert admitted["model_allocation"]["execution_isolation"] == HEADER_ONLY_PLATFORM_PROFILE
    workspace._ensure_runner(request_id, *workspace._load(request_id))
    assert len(state.github.writes) == 1
    assert state.github.writes[0] == (
        f"/repos/{protocol['repository']}/actions/workflows/{workspace.WORKFLOW}/dispatches",
        {"ref": "main", "inputs": {"request_id": request_id}},
    )
    payload = {
        "retort_run_id": request_id,
        "user_id": 7,
        "github_workspace": {
            "retort_run_id": request_id,
            "request_id": request_id,
            **protocol,
            "run_id": 42,
            "issue_number": effects["issue_number"],
        },
    }
    with state.factory() as db:
        assert workspace.authorized_incident(db, payload, event_id)
        assert not workspace.authorized_incident(db, {**payload, "user_id": 8}, event_id)
        wrong_run = {**payload, "github_workspace": {**payload["github_workspace"], "run_id": 101}}
        assert not workspace.authorized_incident(db, wrong_run, event_id)
        monkeypatch.delenv("DEVFLEET_FORCE_OPENCODE")
        assert not workspace.authorized_incident(db, payload, event_id)
        assert workspace.authorized_incident(db, payload, event_id, read_only=True)
        stored = json_loads(db.get(RetortEvolutionRun, request_id).effects_json, {})
        assert stored["run_id"] == 42


def test_training_contract_cannot_choose_an_unisolated_model_tool():
    contract = {
        "role": "scout",
        "source": {},
        "handoffs": [],
        "review": {},
        "requires_isolated_execution": True,
        "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
    }
    for tool in ("codex", "dolt"):
        with pytest.raises(DoltIncidentContractError, match="non_exportable"):
            _incident_prompt(contract, {}, tool)
    assert "role: scout" in _incident_prompt(contract, {}, "opencode")
