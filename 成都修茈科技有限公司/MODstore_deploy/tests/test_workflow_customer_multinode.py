"""Real two-employee graph returns survive restart without replaying native work."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import select

from modstore_server import workflow_customer_delivery as delivery
from modstore_server import workflow_customer_finalization as finalization
from modstore_server.models import CatalogItem, OutboxEvent, Workflow, WorkflowNode
from modstore_server.strategic_portfolio import digest
from tests import test_workflow_customer_finalization as original

experiment_run = original.experiment_run
workflow_experiment = original.workflow_experiment
execution_experiment = original.execution_experiment
customer_workflow = original.customer_workflow
returned_customer_graph = original.returned_customer_graph


@pytest.fixture
def two_employees(returned_customer_graph, request):
    state = returned_customer_graph
    env = state.env
    dynamic = getattr(request, "param", True) == "dynamic"
    vendor_names = {name for name in sys.modules if name.startswith("csv_full_read")}
    second = env["employee_id"] + "-second"
    archive = env["archive"].with_name("workflow-csv-second.xcemp")
    if dynamic:
        root = Path(__file__).resolve().parents[3] / "FHD/mods/_employees/csv-full-read-employee"
        manifest = json.loads((root / "manifest.json").read_text())
        manifest["id"] = second
        manifest["employee_config_v2"]["workspace_policy"] = {
            "scope_globs": ["inputs/**", "outputs/**"],
            "forbidden_globs": ["**/.env"],
        }
        with zipfile.ZipFile(archive, "w") as target:
            for path in sorted(root.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    content = (
                        json.dumps(manifest).encode()
                        if path.name == "manifest.json"
                        else path.read_bytes()
                    )
                    target.writestr(f"{second}/{path.relative_to(root).as_posix()}", content)
    else:
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
    first["config"]["customer_deliverables"] = (
        ["outputs/first.csv"] if getattr(request, "param", True) and not dynamic else []
    )
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
    other["config"]["customer_deliverables"] = ["outputs/second.csv"]
    if dynamic:
        first["config"]["output_mapping"] = {"handoff_path": "outputs/first.csv"}
        other["config"]["input_mapping"].update(
            file_path="{{nodes.first native employee.output.handoff_path}}",
            output_relpath="outputs/second.json",
        )
        other["config"]["customer_deliverables"] = ["outputs/second.json"]
    graph["nodes"].insert(2, other)
    graph["edges"] = [
        {"source_temp_id": "start", "target_temp_id": "native"},
        {"source_temp_id": "native", "target_temp_id": "second"},
        {"source_temp_id": "second", "target_temp_id": "end"},
    ]
    if getattr(request, "param", True) == "undeclared":
        for node in (first, other):
            node["config"].pop("customer_deliverables")
    elif getattr(request, "param", True) == "unproduced_required_file":
        other["config"]["customer_deliverables"] = ["outputs/never-produced.csv"]
    env["run"]["graph"] = graph
    result = asyncio.run(env["run"]["generate"](env["customer_id"]))
    assert result["ok"] and result["sandbox_ok"], json.dumps(result, ensure_ascii=False)
    yield state
    for name in set(sys.modules) - vendor_names:
        if name.startswith("csv_full_read"):
            sys.modules.pop(name, None)


@pytest.mark.parametrize("two_employees", ["dynamic"], indirect=True)
def test_dynamic_native_file_input_is_bound_to_original_predecessor(two_employees):
    state = two_employees
    state.run()
    with state.factory() as db:
        execution = original._execution(state, db)
        assert execution.status == "completed", execution.error_message
        _binding, produced = delivery.load_completed_delivery(db, execution.id)
    assert len(state.native) == 2
    assert state.native[1]["input_data"]["file_path"] == "outputs/first.csv"
    assert (state.env["workspace"] / "outputs/second.json").is_file()
    assert [row["output_path"] for row in produced["artifacts"]] == [
        "outputs/first.csv",
        "outputs/second.json",
    ]
    output = json.loads((state.env["workspace"] / "outputs/second.json").read_text())
    assert output["rows"] == [{"order": f"A-{state.env['customer_id']}", "quantity": "3"}]
    from modstore_server.eventing.db_outbox import public_payload

    for row in produced["nodes"]:
        assert row["node_output"] and row["node_output_sha256"]
        assert "node_output" not in public_payload(delivery.PRODUCED_EVENT, row)


@pytest.mark.parametrize("two_employees", ["dynamic"], indirect=True)
@pytest.mark.parametrize("fresh_process", [False, True])
def test_dynamic_graph_restart_uses_sealed_original_outputs_without_native_replay(
    two_employees, monkeypatch, fresh_process
):
    state = two_employees
    execution_id, returned = _crash_after_graph_return(state, monkeypatch)
    # Later mutable workspace writes cannot replace either original private file.
    (state.env["workspace"] / "outputs/first.csv").write_bytes(b"a later unrelated file")
    if fresh_process:
        script = """
import json
import sys
from modstore_server.workflow_customer_finalization import recover_returned_customer_workflows
from modstore_server.services.employee import get_default_employee_client
from modstore_server import workflow_event_runner
def forbidden(*args, **kwargs):
    raise AssertionError('recovery attempted an employee, graph or billing replay')
get_default_employee_client().execute_task = forbidden
workflow_event_runner.execute_workflow = forbidden
workflow_event_runner.consume_llm_credit = forbidden
print('RECOVERY_RESULT=' + json.dumps(recover_returned_customer_workflows(after=int(sys.argv[1]))))
"""
        child = subprocess.run(
            [sys.executable, "-c", script, str(state.recovery_cursor)],
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(str(path) for path in sys.path if path),
            },
            text=True,
            capture_output=True,
            timeout=45,
        )
        assert child.returncode == 0, child.stdout + child.stderr
        recovered = json.loads(child.stdout.split("RECOVERY_RESULT=", 1)[1].strip())
    else:
        recovered = finalization.recover_returned_customer_workflows(
            session_factory=state.factory, after=state.recovery_cursor
        )
    assert recovered["completed"] == 1 and recovered["blocked"] == 0
    with state.factory() as db:
        binding, produced = delivery.load_completed_delivery(db, execution_id)
        execution = original._execution(state, db)
        assert execution.output_data == returned["output_json"]
        assert produced["nodes"][1]["runtime_contract_sha256"]
        for node, row in zip(
            delivery.delivery_nodes(binding["customer_delivery"]), produced["nodes"], strict=True
        ):
            content, _name = delivery.read_artifact_bytes(node, row["artifacts"][0])
            assert hashlib.sha256(content).hexdigest() == row["artifacts"][0]["artifact_sha256"]
    assert len(state.native) == 2 and len(state.feedback) == (0 if fresh_process else 1)
    assert state.charged == []


@pytest.mark.parametrize("two_employees", ["dynamic"], indirect=True)
@pytest.mark.parametrize(
    "fault", ["source_bytes", "owner", "mapping", "node_output", "missing_receipt"]
)
def test_dynamic_input_rejects_predecessor_or_mapping_drift_before_second_native_call(
    two_employees, monkeypatch, fault
):
    state = two_employees
    record = delivery.record_customer_delivery_node
    injected = []

    def record_then_change(**kwargs):
        record(**kwargs)
        if injected:
            return
        injected.append(kwargs["execution_id"])
        if fault == "source_bytes":
            (state.env["workspace"] / "outputs/first.csv").write_bytes(
                b"changed before downstream read"
            )
            return
        with state.factory() as db:
            event = delivery._event(
                db, f"{delivery.PRODUCED_EVENT}:{kwargs['execution_id']}:{kwargs['node_id']}"
            )
            if fault == "mapping":
                node = db.get(WorkflowNode, kwargs["node_id"])
                config = json.loads(node.config)
                config["output_mapping"]["handoff_path"] = "inputs/orders.json"
                node.config = json.dumps(config)
            elif fault == "missing_receipt":
                db.delete(event)
            else:
                payload = json.loads(event.payload_json)
                if fault == "owner":
                    payload["user_id"] = state.env["run"]["arms"]["0"]
                else:
                    payload["node_output"]["handoff_path"] = "inputs/orders.json"
                    payload["node_output_sha256"] = digest(payload["node_output"])
                event.payload_json = json.dumps(payload)
            db.commit()

    monkeypatch.setattr(delivery, "record_customer_delivery_node", record_then_change)
    with pytest.raises(ValueError):
        state.run()
    with state.factory() as db:
        execution = original._execution(state, db)
        assert execution.status == "failed" and execution.completed_at is not None
        assert delivery._event(db, f"{finalization.RETURNED_EVENT}:{execution.id}") is None
    assert len(state.native) == 1 and state.charged == []


@pytest.mark.parametrize("two_employees", ["dynamic"], indirect=True)
def test_dynamic_input_cannot_reuse_another_execution_receipt(two_employees, monkeypatch):
    state = two_employees
    state.run()
    with state.factory() as db:
        first = original._execution(state, db)
        _binding, original_produced = delivery.load_completed_delivery(db, first.id)
    record = delivery.record_customer_delivery_node
    injected = []

    def record_then_replace(**kwargs):
        record(**kwargs)
        if injected:
            return
        injected.append(kwargs["execution_id"])
        with state.factory() as db:
            event = delivery._event(
                db, f"{delivery.PRODUCED_EVENT}:{kwargs['execution_id']}:{kwargs['node_id']}"
            )
            event.payload_json = json.dumps(original_produced["nodes"][0])
            db.commit()

    monkeypatch.setattr(delivery, "record_customer_delivery_node", record_then_replace)
    with pytest.raises(ValueError, match="result changed"):
        state.run()
    assert len(state.native) == 3  # Two original calls; only the new first node ran.
    with state.factory() as db:
        assert delivery.load_completed_delivery(db, first.id)[1] == original_produced


@pytest.mark.parametrize(
    ("two_employees", "accepted", "successful"),
    [
        (True, (0,), False),
        (True, (1,), False),
        (True, (0, 1), True),
        (False, (0,), False),
        (False, (1,), True),
    ],
    indirect=["two_employees"],
)
def test_customer_outcome_requires_each_frozen_deliverable_not_intermediate_files(
    two_employees, monkeypatch, accepted, successful
):
    from tests.test_retort_experiment_lifecycle import Clock
    from tests.test_retort_workflow_customer import business_receipts, mature

    state, env = two_employees, two_employees.env
    monkeypatch.setattr(original.runner, "datetime", Clock)
    state.run()
    with state.factory() as db:
        execution = original._execution(state, db)
        assert execution.status == "completed"
        binding, produced = delivery.load_completed_delivery(db, execution.id)
        env.update(execution_id=execution.id, binding=binding)
    for index in accepted:
        env["artifact"] = produced["artifacts"][index]
        business_receipts(env)
    observed = mature(env)
    assert len(observed) == 1
    assert observed[0]["execution_id"] == env["execution_id"]
    assert observed[0]["success"] is successful
    assert len(state.native) == 2


@pytest.mark.parametrize(
    ("two_employees", "native_calls"),
    [("undeclared", 0), ("unproduced_required_file", 2)],
    indirect=["two_employees"],
)
def test_missing_delivery_scope_or_required_output_cannot_complete_customer_graph(
    two_employees, native_calls
):
    state = two_employees
    with pytest.raises(ValueError, match="deliverable"):
        state.run()
    with state.factory() as db:
        execution = original._execution(state, db)
        if native_calls == 0:
            assert execution is None  # Admission was rejected before its transaction committed.
        else:
            assert execution.status == "failed"
            assert delivery._event(db, f"{finalization.RETURNED_EVENT}:{execution.id}") is None
    assert len(state.native) == native_calls and state.charged == []


@pytest.mark.parametrize("fault", ["produced_digest", "returned_digest", "terminal_output"])
def test_completed_delivery_still_requires_original_native_result_and_sealed_graph(
    two_employees, fault
):
    state = two_employees
    state.run()
    with state.factory() as db:
        execution = original._execution(state, db)
        binding, produced = delivery.load_completed_delivery(db, execution.id)
        if fault == "terminal_output":
            execution.output_data = json.dumps({"claimed": "a different graph"})
        else:
            event_id = (
                f"{delivery.PRODUCED_EVENT}:{execution.id}:{produced['nodes'][-1]['node_id']}"
                if fault == "produced_digest"
                else f"{finalization.RETURNED_EVENT}:{execution.id}"
            )
            event = delivery._event(db, event_id)
            payload = json.loads(event.payload_json)
            if fault == "produced_digest":
                payload["artifacts"][0]["artifact_sha256"] = "f" * 64
            else:
                payload["receipt_sha256"] = "f" * 64
            event.payload_json = json.dumps(payload)
        db.commit()
        with pytest.raises((ValueError, OSError)):
            delivery.load_completed_delivery(db, execution.id)
    assert len(state.native) == 2


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
            artifact = json.loads(produced.payload_json)["artifacts"][0]
            delivery._artifact_snapshot_path(last, artifact).write_bytes(b"unrelated later bytes")
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
