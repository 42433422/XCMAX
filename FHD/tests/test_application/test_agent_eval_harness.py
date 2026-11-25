from __future__ import annotations

import json
from xml.etree import ElementTree as ET

import pytest

from evals import run_agent_eval as eval_module
from evals.run_agent_eval import DEFAULT_TASKS_PATH, run_eval


def test_agent_eval_harness_baseline_passes(monkeypatch) -> None:
    from app.application.agent_orchestrator import orchestrator

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    original_executor = orchestrator.AgentToolExecutor
    result = run_eval(DEFAULT_TASKS_PATH)

    assert orchestrator.AgentToolExecutor is original_executor
    assert result["execution_mode"] == "fixture_local"
    failures = [
        {"id": case["id"], "failed_checks": case["failed_checks"]}
        for case in result["results"]
        if not case["passed"]
    ]
    assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)
    assert result["passed"] == len(eval_module.load_tasks()) == 123
    assert len(result["results"]) == len(eval_module.load_tasks())
    assert result["score"] == 1.0
    assert result["coverage"] == {
        "fixture_contract_passed": 123,
        "business_effect_verified": 16,
        "artifact_integrity_verified": 2,
        "task_admission_verified": 1,
        "read_only_contract": 8,
        "unverified": 45,
        "not_exercised": 51,
    }
    dispatch_only = [
        row for row in result["results"] if row["coverage_scope"] == "dispatch_contract_only"
    ]
    assert len(dispatch_only) == 39
    assert all(row["business_goal_expected"] for row in dispatch_only)
    assert all(row["result_coverage"] == "unverified" for row in dispatch_only)
    denied = [
        row for row in result["results"] if row["coverage_scope"] == "authorization_contract_only"
    ]
    assert len(denied) == 23
    assert all(row["business_goal_expected"] for row in denied)
    assert all(row["result_coverage"] == "not_exercised" for row in denied)
    assert all(row["details"]["run"] is None for row in denied)
    missing_spec = next(
        row
        for row in result["results"]
        if row["id"] == "business_shipment_create_missing_spec_rejects_before_publish"
    )
    assert missing_spec["details"]["response"]["error_code"] == "SHIPMENT_SPEC_REQUIRED"
    assert missing_spec["details"]["publish_call_count"] == 0


@pytest.mark.parametrize("invalid_review", ["missing", "foreign_goal"])
def test_memory_runtime_eval_requires_its_explicit_review(monkeypatch, invalid_review) -> None:
    task = next(
        row for row in eval_module.load_tasks() if row["kind"] == "memory_v2_planner_context"
    )
    if invalid_review == "missing":
        task.pop("runtime_review")
    else:
        task["runtime_review"]["goals"][0]["source"] = "unrelated"
    monkeypatch.setattr(eval_module, "load_tasks", lambda _path: [task])
    result = run_eval()
    assert result["failed"] == 1
    assert result["results"][0]["passed"] is False


@pytest.mark.parametrize("invalid_review", ["missing", "foreign_reply", "foreign_user"])
def test_owned_attachment_reply_review_is_bound_to_its_explicit_fixture(invalid_review) -> None:
    from evals.owned_attachment_eval import _scripted_model_response

    task = next(
        row
        for row in eval_module.load_tasks()
        if row["id"] == "multimodal_ocr_artifact_autonomous_plan"
    )
    prompt = {
        "task": "verify_runtime_goal",
        "original_request": {"text": task["message"]},
        "response": task["runtime_reply"],
        "evidence": [],
    }
    if invalid_review == "missing":
        task.pop("runtime_review")
    elif invalid_review == "foreign_reply":
        prompt["response"] = "unrelated reply"
    else:
        prompt["original_request"]["text"] = "unrelated request"
    assert _scripted_model_response(task, prompt) is None


@pytest.mark.parametrize("fail_task", [False, True])
def test_eval_owns_real_approval_queue_and_restores_it(monkeypatch, fail_task) -> None:
    from app.application.agent_orchestrator import task_execution_repository as queues
    from app.application.agent_orchestrator import tool_permission
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    original_claims = tool_permission._IDEMPOTENCY
    original_owners = tool_permission._LIVE_OWNERS
    original_path = tool_permission._idempotency_path()
    original_queue = queues._task_execution_repository
    original_open = queues._OPEN_REPOSITORIES
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def run_task(_task):
        assert tool_permission._IDEMPOTENCY is not original_claims
        assert tool_permission._LIVE_OWNERS is not original_owners
        assert tool_permission._idempotency_path() != original_path
        tool_permission._IDEMPOTENCY["evaluation-only"] = {}
        tool_permission._LIVE_OWNERS.add("evaluation-owner")
        repository = queues.get_task_execution_repository()
        assert isinstance(repository, queues.SQLAlchemyTaskExecutionRepository)
        assert repository is not original_queue
        run = AgentRun(user_id="7", message="requires approval")
        run.metadata["runtime_context"] = {"tenant_id": "7", "task_id": run.run_id}
        repository.enqueue(run)
        assert repository.claim("fixture-worker", lease_seconds=30) is not None
        repository.request_approval(run.run_id, "fixture-manager")
        result = AgentToolExecutor().execute(
            AgentStep(
                node_id="create",
                tool_id="customers",
                action="create",
                params={"unit_name": "Blocked fixture customer"},
            ),
            runtime_context={"tenant_id": "7", "task_id": run.run_id, "run_id": run.run_id},
        )
        assert result["success"] is False
        assert result["reason"] == "approval_required", result
        if fail_task:
            raise RuntimeError("evaluation failure")
        return {"passed": True}

    monkeypatch.setattr(eval_module, "load_tasks", lambda _path: [{}])
    monkeypatch.setattr(eval_module, "run_task", run_task)
    if fail_task:
        with pytest.raises(RuntimeError, match="evaluation failure"):
            run_eval()
    else:
        assert run_eval()["passed"] == 1
    assert queues._task_execution_repository is original_queue
    assert queues._OPEN_REPOSITORIES is original_open
    assert tool_permission._IDEMPOTENCY is original_claims
    assert tool_permission._LIVE_OWNERS is original_owners
    assert "evaluation-only" not in original_claims
    assert "evaluation-owner" not in original_owners


@pytest.mark.parametrize("fail_task", [False, True])
@pytest.mark.parametrize("existing_store", [False, True])
def test_eval_drains_owned_traces_before_removing_storage(
    monkeypatch, tmp_path, fail_task, existing_store
) -> None:
    import os
    import threading
    from pathlib import Path

    from app.infrastructure.llm import trace_store

    monkeypatch.setenv("XCAGI_OTLP_ENDPOINT", "")
    caller_path = tmp_path / "caller-traces"
    previous = trace_store.TraceStore(base_dir=caller_path) if existing_store else None
    if previous is not None:
        previous.start()
    monkeypatch.setattr(trace_store, "_store", previous)
    monkeypatch.setenv("XCAGI_GENAI_TRACE_DIR", str(caller_path))
    observed = {}
    failure = RuntimeError("evaluation task failed")
    span_ids = {f"evaluation-{index}" for index in range(101)}

    def run_task(_task):
        before = set(threading.enumerate())
        store = trace_store.get_trace_store()
        observed.update(store=store, threads=set(threading.enumerate()) - before)
        for span_id in span_ids:
            store.record({"span_id": span_id, "name": "evaluation resource"})
        if fail_task:
            raise failure
        return {"passed": True}

    cleanup = eval_module.tempfile.TemporaryDirectory.cleanup

    def check_cleanup(directory):
        root = Path(directory.name)
        if not root.name.startswith("xcagi-agent-eval-"):
            return cleanup(directory)
        store = observed["store"]
        try:
            assert store is not previous
            assert store._base_dir.is_relative_to(root)
            assert store._closed and store._log_provider is None
            assert not any(thread.is_alive() for thread in observed["threads"])
            assert {row["span_id"] for row in store.query(limit=200)} == span_ids
            assert trace_store._store is previous
            assert os.environ["XCAGI_GENAI_TRACE_DIR"] == str(caller_path)
            observed["cleaned"] = root
        finally:
            if store is not previous:
                store.stop()
            cleanup(directory)

    monkeypatch.setattr(eval_module, "load_tasks", lambda _path: [{}])
    monkeypatch.setattr(eval_module, "run_task", run_task)
    monkeypatch.setattr(eval_module.tempfile.TemporaryDirectory, "cleanup", check_cleanup)
    try:
        if fail_task:
            with pytest.raises(RuntimeError) as raised:
                run_eval()
            assert raised.value is failure
        else:
            assert run_eval()["passed"] == 1
        assert not observed["cleaned"].exists()
        assert trace_store._store is previous
        if previous is not None:
            assert not previous._closed
            previous.record({"span_id": "caller-after-evaluation"})
            previous.flush()
            assert [row["span_id"] for row in previous.query()] == ["caller-after-evaluation"]
    finally:
        if previous is not None:
            previous.stop()


def test_agent_eval_cli_prints_only_public_summary(monkeypatch, capsys) -> None:
    result = {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "score": 1.0,
        "results": [{"api_key": "must-not-be-printed", "passed": True}],
    }
    monkeypatch.setattr(eval_module, "run_eval", lambda _path: result)

    assert eval_module.main([]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "suite": "agent_platform_minimum",
        "execution_mode": "fixture_local",
        "tasks_path": str(DEFAULT_TASKS_PATH),
        "total": 1,
        "passed": 1,
        "failed": 0,
        "score": 1.0,
    }
    assert "must-not-be-printed" not in output


@pytest.mark.parametrize("failed", [False, True])
def test_agent_eval_junit_preserves_result_identity_without_fixture_payloads(
    monkeypatch, capsys, tmp_path, failed
) -> None:
    secret = "fixture-payload-must-not-be-published"
    result = {
        "total": 1,
        "passed": int(not failed),
        "failed": int(failed),
        "score": float(not failed),
        "results": [
            {
                "id": "case<&>",
                "kind": "offline_contract",
                "passed": not failed,
                "failed_checks": [
                    {
                        "name": f"context_not_contains:{secret}",
                        "actual": secret,
                        "expected": secret,
                    },
                    {"name": "task", "actual": secret, "expected": "pass"},
                ],
                "details": {"api_key": secret},
            }
        ],
    }
    identity = {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
    for name, value in identity.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(eval_module, "run_eval", lambda _path: result)
    report = tmp_path / "reports/junit.xml"

    assert eval_module.main(["--junitxml", str(report)]) == int(failed)
    output = capsys.readouterr().out
    assert json.loads(output)["failed"] == int(failed)
    suite = ET.parse(report).getroot()
    assert suite.attrib == {
        "name": "agent_platform_minimum",
        "tests": "1",
        "failures": str(int(failed)),
        "errors": "0",
    }
    assert {p.attrib["name"]: p.attrib["value"] for p in suite.findall("properties/property")} == {
        "execution_mode": "fixture_local",
        **identity,
    }
    case = suite.find("testcase")
    assert case is not None and case.attrib == {"name": "case<&>", "classname": "offline_contract"}
    failure = case.find("failure")
    if failed:
        assert failure is not None and failure.attrib["message"] == "context_not_contains, task"
    else:
        assert failure is None
    assert secret not in output + report.read_text()


def test_agent_eval_crash_cannot_publish_stale_junit(monkeypatch, tmp_path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text("evidence from a previous attempt")

    def crash(_path):
        raise RuntimeError("fixture setup failed")

    monkeypatch.setattr(eval_module, "run_eval", crash)
    with pytest.raises(RuntimeError, match="fixture setup failed"):
        eval_module.main(["--junitxml", str(report)])
    assert not report.exists()


def test_route_fixture_uses_real_session_and_restores_auth_boundary() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from app import db as host_db
    from app.db.models.user import User
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.utils.security.password_hash import check_password_hash

    app = FastAPI()

    @app.post("/fixture-write")
    def write(principal=Depends(require_agent_principal)):
        return {"tenant_id": principal.tenant_id, "sealed": bool(principal.actor_authorization)}

    with TestClient(app) as client:
        original_factory = host_db.HostSessionLocal
        assert client.post("/fixture-write").status_code == 401
        with eval_module._authenticated_route_fixture(client):
            with host_db.HostSessionLocal() as db:
                stored = db.query(User).one().password
                assert stored.startswith("pbkdf2:sha256:")
                assert not check_password_hash(stored, "unused")
            assert client.post("/fixture-write").json() == {"tenant_id": "7", "sealed": True}
            assert (
                client.post("/fixture-write", headers={"X-Session-ID": "forged"}).status_code == 401
            )
        assert host_db.HostSessionLocal is original_factory
        assert "X-Session-ID" not in client.headers
        assert client.post("/fixture-write").status_code == 401


def test_shipment_fixture_does_not_admit_missing_tenant(monkeypatch) -> None:
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes import shipment_orders

    app = FastAPI()
    app.include_router(shipment_orders.router)
    service = Mock()
    monkeypatch.setattr(shipment_orders, "_svc", lambda: service)
    with (
        TestClient(app) as client,
        eval_module._authenticated_route_fixture(client, tenant_id=None),
    ):
        response = client.delete(
            "/api/orders/clear-all", headers={"Idempotency-Key": "missing-tenant"}
        )
    assert response.status_code == 403
    assert response.json().get("error_code") == "approval_scope_required"
    assert not service.mock_calls


def test_eval_route_receipts_do_not_leak_into_later_requests(monkeypatch) -> None:
    from app.application.agent_orchestrator import tool_permission

    kinds = {"excel_vector_route_agent", "materials_route_agent", "products_route_agent"}
    tasks = [task for task in eval_module.load_tasks() if task["kind"] in kinds]
    monkeypatch.setattr(eval_module, "load_tasks", lambda _path: tasks)
    claims = dict(tool_permission._IDEMPOTENCY)
    owners = set(tool_permission._LIVE_OWNERS)
    result = run_eval()
    assert result["failed"] == 0, result["results"]
    assert result["passed"] == len(tasks) > 0
    assert claims == tool_permission._IDEMPOTENCY
    assert owners == tool_permission._LIVE_OWNERS


def test_original_medium_document_survives_workspace_review(monkeypatch):
    task = next(
        row
        for row in eval_module.load_tasks()
        if row["id"] == "generate_office_document_requires_approval_and_records_artifact"
    )
    assert task["review_channel"] == "workspace"
    monkeypatch.setattr(eval_module, "load_tasks", lambda _path: [task])
    result = run_eval()["results"][0]
    assert result["passed"], result["failed_checks"]
    assert result["result_coverage"] == "artifact_integrity_verified"
    run = result["details"]["run"]
    assert run["status"] == "completed" and len(run["artifacts"]) == 1
    assert run["metadata"]["plan"]["nodes"][0]["risk"] == "medium"
    assert run["metadata"]["plan"]["metadata"]["approval_required_node_ids"] == []
