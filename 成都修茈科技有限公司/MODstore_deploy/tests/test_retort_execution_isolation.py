"""SQL admission and workflow identity for private-feedback execution."""

from uuid import uuid4

import pytest

from modstore_server import retort_github_workspace as workspace
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.dot_ticket_dispatch import DoltIncidentContractError, _incident_prompt
from modstore_server.models import IncidentEvent, RetortEvolutionRun, User
from modstore_server.para_execution_isolation import HEADER_ONLY_PLATFORM_PROFILE
from tests.test_strategic_portfolio import database as database_fixture

database = database_fixture


@pytest.mark.parametrize("source", ["customer_feedback", "training_candidate"])
def test_private_feedback_requires_real_admission_and_keeps_original_workflow_identity(
    database, monkeypatch, source
):
    from modstore_server import para_model_admission

    monkeypatch.setattr(workspace, "get_session_factory", lambda: database)
    monkeypatch.delenv("DEVFLEET_FORCE_OPENCODE", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_PLATFORM_POOL", raising=False)
    request_id = str(uuid4())
    protocol = {"repository": "example/product", "source_sha": "a" * 40}
    effects = {source: {}, "authorization": {"approved": True}, "issue_number": 20}
    with database() as db:
        db.add(User(id=7, username="admin", password_hash="unused", is_admin=True))
        event = IncidentEvent(
            event_type="ops.retort.evolution", source="retort", fingerprint=request_id
        )
        db.add(event)
        db.flush()
        event_id = event.id
        db.add(
            RetortEvolutionRun(
                id=request_id,
                user_id=7,
                event_id=event_id,
                status="waiting_execution",
                protocol_json=json_dumps(protocol),
                effects_json=json_dumps(effects),
            )
        )
        db.commit()
    monkeypatch.setattr(
        para_model_admission,
        "platform_model_admission",
        lambda _: {"status": "admitted", "model": "coding", "approved_models": ["coding"]},
    )
    calls = []
    workflow = {
        "id": 100,
        "display_title": f"para-workspace-{request_id}",
        "head_branch": "main",
        "head_sha": protocol["source_sha"],
        "run_attempt": 1,
        "path": f".github/workflows/{workspace.WORKFLOW}",
        "status": "in_progress",
    }

    def github(method, path, body=None):
        calls.append((method, path, body))
        if method == "POST" and path.endswith("/dispatches"):
            assert body == {"ref": "main", "inputs": {"request_id": request_id}}
            return {}
        if "runs?" in path:
            return {"workflow_runs": [workflow]}
        if path.endswith("/runs/100"):
            return workflow
        raise AssertionError((method, path))

    monkeypatch.setattr(workspace, "github", github)
    assert (
        workspace._ensure_runner(request_id, protocol, effects)["model_allocation"]["status"]
        == "waiting"
    )
    assert calls == []
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "1")
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_POOL", "1")
    admitted = workspace._ensure_runner(request_id, protocol, effects)
    assert admitted["model_allocation"]["execution_isolation"] == HEADER_ONLY_PLATFORM_PROFILE
    workspace._ensure_runner(request_id, *workspace._load(request_id))
    assert len([call for call in calls if call[0] == "POST"]) == 1
    payload = {
        "retort_run_id": request_id,
        "user_id": 7,
        "github_workspace": {
            "retort_run_id": request_id,
            "request_id": request_id,
            **protocol,
            "run_id": 100,
            "issue_number": 20,
        },
    }
    with database() as db:
        assert workspace.authorized_incident(db, payload, event_id)
        assert not workspace.authorized_incident(db, {**payload, "user_id": 8}, event_id)
        wrong_run = {**payload, "github_workspace": {**payload["github_workspace"], "run_id": 101}}
        assert not workspace.authorized_incident(db, wrong_run, event_id)
        monkeypatch.delenv("DEVFLEET_FORCE_OPENCODE")
        assert not workspace.authorized_incident(db, payload, event_id)
        assert workspace.authorized_incident(db, payload, event_id, read_only=True)
        stored = json_loads(db.get(RetortEvolutionRun, request_id).effects_json, {})
        assert stored["run_id"] == 100


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
