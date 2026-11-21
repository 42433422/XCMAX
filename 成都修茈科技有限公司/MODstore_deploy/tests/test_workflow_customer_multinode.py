"""Real two-employee graph returns survive restart without replaying native work."""

from __future__ import annotations

import asyncio
import hashlib
import json
import zipfile
from copy import deepcopy

import pytest
from sqlalchemy import select

from modstore_server import workflow_customer_delivery as delivery
from modstore_server import workflow_customer_finalization as finalization
from modstore_server.models import CatalogItem, OutboxEvent, Workflow
from modstore_server.strategic_portfolio import digest
from tests import test_workflow_customer_finalization as original

experiment_run = original.experiment_run
workflow_experiment = original.workflow_experiment
execution_experiment = original.execution_experiment
customer_workflow = original.customer_workflow
returned_customer_graph = original.returned_customer_graph


@pytest.fixture
def two_employees(returned_customer_graph):
    state = returned_customer_graph
    env = state.env
    second = env["employee_id"] + "-second"
    archive = env["archive"].with_name("workflow-csv-second.xcemp")
    with (
        zipfile.ZipFile(env["archive"]) as source,
        zipfile.ZipFile(archive, "w") as target,
    ):
        for name in source.namelist():
            content = source.read(name)
            if name.endswith("/manifest.json"):
                manifest = json.loads(content)
                manifest["id"] = second
                content = json.dumps(manifest).encode()
            target.writestr(name.replace(env["employee_id"] + "/", second + "/", 1), content)
    with state.factory() as db:
        first = db.scalar(select(CatalogItem).where(CatalogItem.pkg_id == env["employee_id"]))
        db.add(
            CatalogItem(
                pkg_id=second,
                name="Second customer CSV employee",
                version=first.version,
                author_id=env["customer_id"],
                artifact="employee_pack",
                is_public=True,
                stored_filename=archive.name,
                sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            )
        )
        workflow = Workflow(user_id=env["customer_id"], name="Approved two-employee delivery")
        db.add(workflow)
        db.flush()
        state.workflow_id = int(workflow.id)
        env["run"]["workflows"][env["customer_id"]] = state.workflow_id
        db.commit()
    graph = deepcopy(env["run"]["graph"])
    first = graph["nodes"][1]
    first["name"] = "first native employee"
    first["config"]["input_mapping"]["output_relpath"] = "outputs/first.csv"
    other = deepcopy(first)
    other.update(temp_id="second", name="second native employee")
    other["config"].update(
        employee_id=second,
        task="Produce the second file of the customer's approved delivery",
        output_mapping={
            "second_receipt": "{{result}}",
            "delivery_marker": "second returned",
        },
    )
    other["config"]["input_mapping"]["output_relpath"] = "outputs/second.csv"
    graph["nodes"].insert(2, other)
    graph["edges"] = [
        {"source_temp_id": "start", "target_temp_id": "native"},
        {"source_temp_id": "native", "target_temp_id": "second"},
        {"source_temp_id": "second", "target_temp_id": "end"},
    ]
    env["run"]["graph"] = graph
    result = asyncio.run(env["run"]["generate"](env["customer_id"]))
    assert result["ok"] and result["sandbox_ok"], json.dumps(result, ensure_ascii=False)
    return state


def _crash_after_graph_return(state, monkeypatch):
    writer = finalization._write_terminal

    def crash(*_args, **_kwargs):
        raise SystemExit("process stopped after durable graph return")

    monkeypatch.setattr(finalization, "_write_terminal", crash)
    with pytest.raises(SystemExit, match="durable graph return"):
        state.run()
    monkeypatch.setattr(finalization, "_write_terminal", writer)
    assert len(state.native) == 2 and state.feedback == state.charged == []
    with state.factory() as db:
        execution = original._execution(state, db)
        assert execution.status == "running" and execution.completed_at is None
        event = delivery._event(db, f"{finalization.RETURNED_EVENT}:{execution.id}")
        assert event is not None
        state.recovery_cursor = int(event.id) - 1
        returned = json.loads(event.payload_json)
        return int(execution.id), returned


def test_two_original_employees_end_mapping_and_restart_only_finalize(two_employees, monkeypatch):
    state = two_employees
    execution_id, returned = _crash_after_graph_return(state, monkeypatch)
    result = finalization.recover_returned_customer_workflows(
        session_factory=state.factory, after=state.recovery_cursor
    )
    assert result == {"checked": 1, "completed": 1, "blocked": 0, "next_cursor": 0}
    assert (
        finalization.recover_returned_customer_workflows(
            session_factory=state.factory, after=state.recovery_cursor
        )["checked"]
        == 0
    )
    assert len(state.native) == 2 and len(state.feedback) == 1 and state.charged == []
    assert {call["employee_id"] for call in state.native} == {
        state.env["employee_id"],
        state.env["employee_id"] + "-second",
    }
    with state.factory() as db:
        execution = original._execution(state, db)
        assert execution.output_data == returned["output_json"]
        output = json.loads(execution.output_data)
        assert output["nodes"]["prev"]["type"] == "end"
        assert output["delivery_marker"] == "second returned"
        assert (
            output["second_receipt"]
            == output["nodes"]["second native employee"]["output"]["employee_result"]
        )
        binding, produced = delivery.load_completed_delivery(db, execution_id)
        assert len(binding["customer_delivery"]["nodes"]) == len(produced["artifacts"]) == 2
        rows = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == str(execution_id),
                OutboxEvent.event_name.in_((delivery.CLAIM_EVENT, delivery.PRODUCED_EVENT)),
            )
        ).all()
        assert len(rows) == 4
    listing = state.env["http"].get(
        "/api/customer-value/workflow-deliveries",
        params=original.customer_tests._query(state.env),
    )
    assert listing.status_code == 200 and len(listing.json()["items"]) == 2, listing.text
    for item in listing.json()["items"]:
        received = state.env["http"].get(item["download_url"])
        assert received.status_code == 200
        assert hashlib.sha256(received.content).hexdigest() == item["artifact_sha256"]
        assert (
            received.content == (state.env["workspace"] / "outputs" / item["filename"]).read_bytes()
        )


@pytest.mark.parametrize("fault", [None, "produced_digest", "returned_digest", "terminal_output"])
def test_completed_history_retains_original_artifacts_but_requires_its_sealed_graph(
    two_employees, fault
):
    state = two_employees
    state.run()
    charges = list(state.charged)
    assert len(charges) == 1
    with state.factory() as db:
        execution = original._execution(state, db)
        execution_id = int(execution.id)
        binding, produced = delivery.load_completed_delivery(db, execution_id)
        contract = binding["customer_delivery"]
        last = delivery.delivery_nodes(contract)[-1]
        if fault == "produced_digest":
            row = delivery._event(db, f"{delivery.PRODUCED_EVENT}:{execution_id}:{last['node_id']}")
            payload = json.loads(row.payload_json)
            payload["artifacts"][0]["artifact_sha256"] = "f" * 64
            row.payload_json = json.dumps(payload)
        elif fault == "returned_digest":
            row = delivery._event(db, f"{finalization.RETURNED_EVENT}:{execution_id}")
            payload = json.loads(row.payload_json)
            payload["receipt_sha256"] = "f" * 64
            row.payload_json = json.dumps(payload)
        elif fault == "terminal_output":
            execution.output_data = json.dumps({"claimed": "different graph"})
        db.commit()
    for artifact in produced["artifacts"]:
        (state.env["workspace"] / artifact["output_path"]).write_bytes(b"later execution output")
    with state.factory() as db:
        if fault:
            with pytest.raises(ValueError):
                delivery.load_completed_delivery(db, execution_id)
        else:
            assert delivery.load_completed_delivery(db, execution_id) == (
                binding,
                produced,
            )
            with pytest.raises(ValueError, match="bytes changed"):
                delivery.load_produced_delivery(db, contract)
            artifact = produced["artifacts"][-1]
            response = state.env["http"].get(
                f"/api/customer-value/workflow-deliveries/{execution_id}/{artifact['artifact_id']}",
                params=original.customer_tests._query(state.env),
            )
            assert response.status_code == 409
    assert len(state.native) == 2 and len(state.feedback) == 1 and state.charged == charges


@pytest.mark.parametrize(
    "fault",
    [
        "missing_last",
        "last_unknown",
        "missing_end",
        "returned_owner",
        "returned_digest",
        "bytes",
        "no_return",
    ],
)
def test_restart_cannot_complete_an_incomplete_or_changed_multinode_graph(
    two_employees, monkeypatch, fault
):
    state = two_employees
    execution_id, _returned = _crash_after_graph_return(state, monkeypatch)
    with state.factory() as db:
        _execution, _binding, contract = delivery._stored_contract(db, execution_id)
        last = delivery.delivery_nodes(contract)[-1]
        produced = delivery._event(
            db, f"{delivery.PRODUCED_EVENT}:{execution_id}:{last['node_id']}"
        )
        event = delivery._event(db, f"{finalization.RETURNED_EVENT}:{execution_id}")
        if fault == "missing_last":
            db.delete(produced)
        elif fault == "last_unknown":
            payload = json.loads(produced.payload_json)
            payload["native_result_sha256"] = "unknown"
            produced.payload_json = json.dumps(payload)
        elif fault == "bytes":
            (state.env["workspace"] / "outputs/second.csv").write_bytes(b"unrelated later bytes")
        elif fault == "no_return":
            db.delete(event)
        else:
            payload = json.loads(event.payload_json)
            if fault == "returned_owner":
                payload["user_id"] = state.env["run"]["arms"]["0"]
            else:
                output = json.loads(payload["output_json"])
                if fault == "missing_end":
                    del output["nodes"][str(output["nodes"]["prev"]["id"])]
                else:
                    output["delivery_marker"] = "changed after graph return"
                payload["output_json"] = json.dumps(output)
            if fault != "returned_digest":
                payload["receipt_sha256"] = digest(
                    {key: value for key, value in payload.items() if key != "receipt_sha256"}
                )
            event.payload_json = json.dumps(payload)
        db.commit()
    result = finalization.recover_returned_customer_workflows(
        session_factory=state.factory, after=state.recovery_cursor
    )
    assert result["completed"] == 0
    assert result["blocked"] == (0 if fault == "no_return" else 1)
    with state.factory() as db:
        execution = original._execution(state, db)
        assert execution.status == "running" and execution.completed_at is None
        with pytest.raises(ValueError, match="not actually completed"):
            delivery.load_completed_delivery(db, execution_id)
    assert len(state.native) == 2 and state.feedback == state.charged == []
