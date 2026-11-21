"""Real approved workflow, native CSV archive and original customer file APIs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import zipfile
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from growthbook import Experiment, GrowthBook
from sqlalchemy import select

from modstore_server import customer_value_lifecycle_api as customer_api
from modstore_server import retort_feedback_experiments as lifecycle
from modstore_server import workflow_customer_delivery as delivery
from modstore_server.api.deps import get_current_user
from modstore_server.models import (
    CatalogItem,
    CustomerValueReceipt,
    OutboxEvent,
    User,
    Workflow,
    WorkflowExecution,
    WorkflowNode,
    get_session_factory,
)
from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT
from modstore_server.retort_workflow_metrics import execution_queries
from tests import test_retort_workflow_execution as execution_tests
from tests.test_retort_experiment_lifecycle import Clock, reapprove, start

experiment_run = execution_tests.experiment_run
workflow_experiment = execution_tests.workflow_experiment
execution_experiment = execution_tests.execution_experiment


@pytest.fixture
def customer_workflow(execution_experiment, monkeypatch, tmp_path):
    from modstore_server import (
        catalog_store,
        customer_value_payment_source,
        retort_feedback_measurements,
        strategic_customer_outcomes,
    )
    from modstore_server.db import workflow as workflow_models
    from modstore_server.workflow_api import execution

    run = execution_experiment
    Clock.value = datetime.now(UTC)
    for module in (
        delivery,
        customer_api,
        strategic_customer_outcomes,
        execution,
        workflow_models,
        retort_feedback_measurements,
    ):
        monkeypatch.setattr(module, "datetime", Clock)
    employee = "csv-generate-" + uuid4().hex[:12]
    root = (
        Path(__file__).resolve().parents[3]
        / "FHD"
        / "mods"
        / "_employees"
        / "csv-generate-employee"
    )
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["id"] = employee
    manifest["employee_config_v2"]["workspace_policy"] = {
        "scope_globs": ["inputs/**", "outputs/**"],
        "forbidden_globs": ["**/.env"],
    }
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "workspaces" / "{user_id}"))
    archive = catalog_store.files_dir() / "workflow-csv.xcemp"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                member = f"{employee}/{path.relative_to(root).as_posix()}"
                if path.name == "manifest.json":
                    bundle.writestr(member, json.dumps(manifest))
                else:
                    bundle.write(path, member)
    arms, actors = {}, {}
    with get_session_factory()() as db:
        admin = db.get(User, run["users"][0])
        for _ in range(30):
            user = User(username=uuid4().hex, password_hash="test-only", is_enterprise=True)
            db.add(user)
            db.flush()
            workflow = Workflow(user_id=user.id, name="Paid CSV customer workflow")
            db.add(workflow)
            db.flush()
            run["users"].append(user.id)
            run["workflows"][user.id] = workflow.id
            actors[user.id] = user
            key = f"xcagi-retort-{run['id']}"
            sdk = GrowthBook(attributes={"id": str(user.id)})
            try:
                arm = sdk.run(Experiment(key=key, seed=key, hashVersion=2, variations=[0, 1]))
                arms[str(arm.variationId)] = user.id
            finally:
                sdk.destroy()
            if len(arms) == 2:
                break
        assert len(arms) == 2
        db.add(
            CatalogItem(
                pkg_id=employee,
                name=manifest["name"],
                version=manifest["version"],
                author_id=arms["1"],
                artifact="employee_pack",
                is_public=True,
                stored_filename=archive.name,
                sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            )
        )
        db.commit()
        for row in [admin, *actors.values()]:
            db.refresh(row)
        db.expunge_all()
    run["arms"] = arms
    life = run["spec"]["lifecycle"]
    life.pop("execution_outcomes", None)
    life.update(
        measurement_scope=WORKFLOW_CUSTOMER_MEASUREMENT,
        cohort_user_ids=run["users"],
        maturation_hours=1,
        customer_outcomes={
            "source": "modstore_customer_workflow_postgres_v1",
            "employee_id": employee,
            "observation_hours": 1,
            "success_metric_id": "success",
            "failure_metric_id": "failure",
            "maximum_treatment_failures": 2,
        },
    )
    run["spec"] = lifecycle.freeze_experiment_policy(run["spec"])
    reapprove(run)
    queries = execution_queries(WORKFLOW_CUSTOMER_MEASUREMENT)
    run["api"].datasource["assignmentQueries"][0]["sql"] = queries["assignment"]
    for name, metric in run["api"].metrics.items():
        metric["sql"].update(conversionSQL=queries[name], userAggregationSQL="MAX(value)")
    run["graph"] = {
        "nodes": [
            {"temp_id": "start", "node_type": "start", "config": {}},
            {
                "temp_id": "native",
                "node_type": "employee",
                "config": {
                    "employee_id": employee,
                    "task": "Generate the customer's ordered CSV file",
                    "input_mapping": {"file_path": "{{global.file_path}}"},
                },
            },
            {"temp_id": "end", "node_type": "end", "config": {}},
        ],
        "edges": [
            {"source_temp_id": "start", "target_temp_id": "native"},
            {"source_temp_id": "native", "target_temp_id": "end"},
        ],
    }
    source = {"source_available": True, "source_authoritative": True, "orders": []}
    for module in (customer_api, customer_value_payment_source):
        monkeypatch.setattr(module, "load_authoritative_payment_orders", lambda _days: source)
    goals, orders, workspaces = {}, {}, {}
    for user_id in arms.values():
        workspace = tmp_path / "workspaces" / str(user_id)
        (workspace / "inputs").mkdir(parents=True)
        (workspace / "inputs/orders.json").write_text(
            json.dumps(
                {
                    "columns": ["order", "quantity"],
                    "rows": [{"order": f"A-{user_id}", "quantity": 3}],
                }
            )
        )
        workspaces[user_id] = workspace
        order = {
            "status": "paid",
            "out_trade_no": f"customer-workflow-order-{user_id}",
            "user_id": user_id,
            "amount_cents": 10_000,
            "currency": "CNY",
            "paid_at": (Clock.value - timedelta(hours=1)).isoformat(),
            "payment_provider": "alipay",
            "provider_trade_no": f"alipay-workflow-{user_id}",
            "provider_verification": "alipay_signed_callback",
            "environment": "production",
        }
        source["orders"].append(order)
        orders[user_id] = order
        goal = {
            "order_no": order["out_trade_no"],
            "customer_goal_id": f"customer-workflow-csv-{user_id}",
            "baseline": 0.0,
            "target": 1.0,
            "comparison": "ge",
            "unit": "valid_csv_file",
            "measurement_window": "approved-workflow-customer-window",
        }
        goals[user_id] = goal
        customer_api.record_kpi_agreement(
            customer_api.KpiAgreementReceiptBody(
                **goal,
                idempotency_key=f"original-workflow-customer-goal-{user_id}",
                agreement_sha256="a" * 64,
            ),
            user=actors[user_id],
        )
    start(run)
    for user_id in arms.values():
        generated = asyncio.run(run["generate"](user_id))
        assert generated["ok"] and generated["sandbox_ok"], generated
    customer_id = arms["1"]
    actor = [actors[customer_id]]
    app = FastAPI()
    app.include_router(customer_api.router)
    app.include_router(customer_api.admin_router)
    app.dependency_overrides[get_current_user] = lambda: actor[0]
    monkeypatch.setattr(sys, "path", list(sys.path))
    vendor_names = {name for name in sys.modules if name.startswith("csv_generate")}
    with TestClient(app) as http:
        result = {
            "run": run,
            "customer_id": customer_id,
            "actors": actors,
            "actor": actor,
            "admin": admin,
            "goal": goals[customer_id],
            "goals": goals,
            "order": orders[customer_id],
            "orders": orders,
            "source": source,
            "http": http,
            "workspace": workspaces[customer_id],
            "workspaces": workspaces,
            "archive": archive,
            "employee_id": employee,
        }

        def execute(user_id=None, **overrides):
            owner = user_id or customer_id
            goal = goals[owner]
            response = run["execute"](
                owner,
                {
                    "file_path": "inputs/orders.json",
                    "customer_delivery": {
                        "order_no": goal["order_no"],
                        "customer_goal_id": goal["customer_goal_id"],
                    },
                    **overrides,
                },
            )
            if response.status_code == 200:
                result["execution_id"] = response.json()["id"]
                with get_session_factory()() as db:
                    binding, produced = delivery.load_completed_delivery(db, result["execution_id"])
                    result.update(binding=binding, artifact=produced["artifacts"][0])
            return response

        result["execute"] = execute
        yield result
    for name in set(sys.modules) - vendor_names:
        if name.startswith("csv_generate"):
            sys.modules.pop(name, None)


def _query(env):
    return {key: env["goal"][key] for key in ("order_no", "customer_goal_id")}


def _accept(env, **overrides):
    artifact = env["artifact"]
    return env["http"].post(
        "/api/customer-value/acceptance-receipts",
        json={
            **_query(env),
            "idempotency_key": "original-workflow-customer-acceptance",
            "acceptance_id": "accepted-native-csv-file",
            "accepted_artifact_id": artifact["artifact_id"],
            "artifact_sha256": artifact["artifact_sha256"],
            "customer_confirmed": True,
            **overrides,
        },
    )


def test_customer_generation_prompt_and_existing_graph_schema_preserve_delivery_scope(
    customer_workflow, monkeypatch
):
    from modstore_server import workflow_nl_graph as generator

    env, messages = customer_workflow, []
    dispatch = generator.chat_dispatch_via_session

    async def capture(*args, **kwargs):
        messages.append(deepcopy(args[4]))
        return await dispatch(*args, **kwargs)

    monkeypatch.setattr(generator, "chat_dispatch_via_session", capture)
    env["run"]["graph"]["nodes"][1]["config"]["customer_deliverables"] = ["outputs/output.csv"]
    for owner in (env["customer_id"], env["run"]["outsider"]):
        with get_session_factory()() as db:
            workflow = Workflow(user_id=owner, name="Explicit required customer file")
            db.add(workflow)
            db.flush()
            workflow_id = workflow.id
            db.commit()
        generated = asyncio.run(env["run"]["generate"](owner, workflow_id=workflow_id))
        assert generated["ok"] and generated["sandbox_ok"], generated
        assert (generator.CUSTOMER_DELIVERY_REQUIREMENTS in messages[-1][1]["content"]) is (
            owner == env["customer_id"]
        )
        with get_session_factory()() as db:
            node = db.scalar(
                select(WorkflowNode).where(
                    WorkflowNode.workflow_id == workflow_id, WorkflowNode.node_type == "employee"
                )
            )
            assert json.loads(node.config)["customer_deliverables"] == ["outputs/output.csv"]


def test_native_workflow_original_customer_downloads_then_explicitly_accepts(customer_workflow):
    env = customer_workflow
    result = env["execute"]()
    assert result.status_code == 200, result.text
    assert (
        env["binding"]["customer_delivery"]["goal"]["customer_ref"]
        == f"paid-user:{env['customer_id']}"
    )
    listing = env["http"].get("/api/customer-value/deliveries", params=_query(env))
    assert listing.status_code == 200 and len(listing.json()["items"]) == 1, listing.text
    row = listing.json()["items"][0]
    received = env["http"].get(row["download_url"])
    assert received.status_code == 200, received.text
    assert f"A-{env['customer_id']}".encode() in received.content
    assert received.content == (env["workspace"] / "outputs/output.csv").read_bytes()
    assert hashlib.sha256(received.content).hexdigest() == row["artifact_sha256"]
    assert str(env["workspace"]) not in listing.text
    with get_session_factory()() as db:
        assert not db.scalars(
            select(CustomerValueReceipt).where(
                CustomerValueReceipt.receipt_kind == "acceptance",
                CustomerValueReceipt.customer_ref == f"paid-user:{env['customer_id']}",
            )
        ).all()
    accepted = _accept(env)
    assert accepted.status_code == 200, accepted.text
    assert _accept(env).json()["created"] is False


@pytest.mark.parametrize(
    "change",
    [
        "bytes",
        "missing",
        "other_customer",
        "admin",
        "refund",
        "goal",
        "sha",
        "unproduced",
        "failed",
    ],
)
def test_existing_customer_receipt_api_rejects_unrelated_or_changed_workflow_artifact(
    customer_workflow, change
):
    env = customer_workflow
    response = env["execute"]()
    assert response.status_code == 200, response.text
    path = delivery._artifact_snapshot_path(env["binding"]["customer_delivery"], env["artifact"])
    overrides = {}
    if change == "bytes":
        path.write_bytes(b"later overwritten CSV")
    elif change == "missing":
        path.unlink()
    elif change == "other_customer":
        env["actor"][0] = env["actors"][env["run"]["arms"]["0"]]
    elif change == "admin":
        env["actor"][0] = env["admin"]
    elif change == "refund":
        env["order"]["status"] = "refunded"
    elif change == "goal":
        customer_api.record_kpi_agreement(
            customer_api.KpiAgreementReceiptBody(
                **env["goal"],
                idempotency_key="changed-workflow-customer-agreement",
                agreement_sha256="b" * 64,
            ),
            user=env["actor"][0],
        )
    elif change == "sha":
        overrides["artifact_sha256"] = "b" * 64
    elif change == "unproduced":
        overrides["accepted_artifact_id"] = f"workflow-file-{env['execution_id']}-999-" + "a" * 24
    else:
        with get_session_factory()() as db:
            db.get(WorkflowExecution, env["execution_id"]).status = "failed"
            db.commit()
    result = _accept(env, **overrides)
    assert result.status_code in {403, 404, 409}, result.text
    with get_session_factory()() as db:
        assert not db.scalars(
            select(CustomerValueReceipt).where(
                CustomerValueReceipt.receipt_kind == "acceptance",
                CustomerValueReceipt.customer_ref == f"paid-user:{env['customer_id']}",
            )
        ).all()


def test_completed_native_node_cannot_be_replayed(customer_workflow):
    env = customer_workflow
    response = env["execute"]()
    assert response.status_code == 200, response.text
    contract = env["binding"]["customer_delivery"]
    with get_session_factory()() as db:
        db.get(WorkflowExecution, env["execution_id"]).status = "running"
        db.commit()
    config = {
        "employee_id": contract["employee_id"],
        "task": contract["task"],
        "input_mapping": {"file_path": "{{global.file_path}}"},
    }
    with pytest.raises(ValueError, match="already started"):
        delivery.run_customer_delivery_node(
            execution_id=env["execution_id"],
            node_id=contract["node_id"],
            user_id=env["customer_id"],
            config=config,
            node_input=contract["node_input"],
            execute=lambda **_: pytest.fail("duplicate native invocation"),
        )
    with get_session_factory()() as db:
        assert (
            len(
                db.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.event_name == delivery.PRODUCED_EVENT,
                        OutboxEvent.aggregate_id == str(env["execution_id"]),
                    )
                ).all()
            )
            == 1
        )


def test_next_execution_cannot_replace_original_download_or_customer_outcome(customer_workflow):
    from tests.test_retort_workflow_customer import business_receipts, mature

    env = customer_workflow
    assert env["execute"]().status_code == 200
    first_artifact = deepcopy(env["artifact"])
    first_execution = env["execution_id"]
    first_bytes = (env["workspace"] / first_artifact["output_path"]).read_bytes()
    business_receipts(env)
    source = env["workspace"] / "inputs/orders.json"
    data = json.loads(source.read_text())
    data["rows"][0]["quantity"] = 17
    source.write_text(json.dumps(data))
    assert env["execute"]().status_code == 200
    second_bytes = (env["workspace"] / first_artifact["output_path"]).read_bytes()
    assert first_bytes != second_bytes
    # Removing the mutable workspace output also cannot remove either sealed file.
    (env["workspace"] / first_artifact["output_path"]).unlink()
    listing = env["http"].get("/api/customer-value/workflow-deliveries", params=_query(env))
    assert listing.status_code == 200 and len(listing.json()["items"]) == 2, listing.text
    downloads = {
        row["artifact_id"]: env["http"].get(row["download_url"]) for row in listing.json()["items"]
    }
    assert downloads[first_artifact["artifact_id"]].status_code == 200
    assert downloads[first_artifact["artifact_id"]].content == first_bytes
    assert downloads[env["artifact"]["artifact_id"]].content == second_bytes
    observed = {row["execution_id"]: row["success"] for row in mature(env)}
    assert observed == {first_execution: True, env["execution_id"]: False}


def test_private_snapshot_retry_checks_existing_bytes_without_replacing_them(customer_workflow):
    env = customer_workflow
    assert env["execute"]().status_code == 200
    contract, artifact = env["binding"]["customer_delivery"], env["artifact"]
    original = {key: value for key, value in artifact.items() if key != "storage"}
    assert delivery._snapshot_artifact(contract, original) == artifact
    (env["workspace"] / artifact["output_path"]).write_bytes(b"later mutable output")
    assert delivery._snapshot_artifact(contract, original) == artifact
    path = delivery._artifact_snapshot_path(contract, artifact)
    path.write_bytes(b"corrupted previously published snapshot")
    with pytest.raises(ValueError, match="bytes changed"):
        delivery._snapshot_artifact(contract, original)
    assert path.read_bytes() == b"corrupted previously published snapshot"


def test_real_native_bytes_with_pending_receipt_are_not_customer_delivery(
    customer_workflow, monkeypatch
):
    from modstore_server.services.employee import get_default_employee_client

    env = customer_workflow
    client = get_default_employee_client()
    execute = client.execute_task
    calls = []

    def pending_after_native(**kwargs):
        result = execute(**kwargs)
        calls.append(result)
        return {**result, "status": "pending", "requires_reconciliation": True}

    monkeypatch.setattr(client, "execute_task", pending_after_native)
    response = env["execute"]()
    assert response.status_code == 500, response.text
    assert len(calls) == 1 and (env["workspace"] / "outputs/output.csv").is_file()
    with get_session_factory()() as db:
        execution = db.scalar(
            select(WorkflowExecution)
            .where(WorkflowExecution.workflow_id == env["run"]["workflows"][env["customer_id"]])
            .order_by(WorkflowExecution.id.desc())
        )
        assert execution.status == "failed"
        events = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == str(execution.id),
                OutboxEvent.event_name.in_((delivery.CLAIM_EVENT, delivery.PRODUCED_EVENT)),
            )
        ).all()
        assert [row.event_name for row in events] == [delivery.CLAIM_EVENT]
        with pytest.raises(ValueError, match="not actually completed"):
            delivery.load_completed_delivery(db, execution.id)
    response = env["http"].get("/api/customer-value/workflow-deliveries", params=_query(env))
    assert response.status_code == 200 and response.json()["items"] == []


@pytest.mark.parametrize("change", ["atime", "write", "replace"])
def test_native_file_hash_ignores_read_access_but_rejects_content_identity_changes(
    customer_workflow, monkeypatch, change
):
    from modstore_server import catalog_archive_integrity, employee_executor

    env = customer_workflow
    target = env["workspace"] / "outputs/output.csv"
    actions = employee_executor._actions_real
    hash_file = catalog_archive_integrity.sha256_file
    reads = []

    def native_with_old_access_time(*args, **kwargs):
        result = actions(*args, **kwargs)
        current = target.stat()
        os.utime(target, ns=(current.st_mtime_ns - 172_800_000_000_000, current.st_mtime_ns))
        return result

    def hash_then_change(path):
        if path != target:
            return hash_file(path)
        before = path.stat()
        checksum = hash_file(path)  # The actual read updates atime on this filesystem.
        after = path.stat()
        assert before.st_atime_ns != after.st_atime_ns
        assert all(
            getattr(before, key) == getattr(after, key)
            for key in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_nlink",
                "st_uid",
                "st_gid",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        )
        reads.append(checksum)
        if change != "atime":
            original = path.read_bytes()
            changed = original.replace(b",3", b",4")
            assert original != changed and len(original) == len(changed)
            if change == "write":
                path.write_bytes(changed)
                os.utime(path, ns=(after.st_atime_ns, after.st_mtime_ns + 1_000_000))
            else:
                replacement = path.with_suffix(".replacement")
                replacement.write_bytes(changed)
                os.utime(replacement, ns=(after.st_atime_ns, after.st_mtime_ns))
                replacement.replace(path)
        return checksum

    monkeypatch.setattr(employee_executor, "_actions_real", native_with_old_access_time)
    monkeypatch.setattr(catalog_archive_integrity, "sha256_file", hash_then_change)
    response = env["execute"]()
    assert len(reads) == 1
    if change == "atime":
        assert response.status_code == 200, response.text
        assert env["artifact"]["artifact_sha256"] == reads[0]
        return
    assert response.status_code == 500, response.text
    assert hashlib.sha256(target.read_bytes()).hexdigest() != reads[0]
    with get_session_factory()() as db:
        execution = db.scalar(
            select(WorkflowExecution)
            .where(WorkflowExecution.workflow_id == env["run"]["workflows"][env["customer_id"]])
            .order_by(WorkflowExecution.id.desc())
        )
        assert execution.status == "failed"
        assert (
            db.scalar(
                select(OutboxEvent.id).where(
                    OutboxEvent.event_name == delivery.PRODUCED_EVENT,
                    OutboxEvent.aggregate_id == str(execution.id),
                )
            )
            is None
        )
