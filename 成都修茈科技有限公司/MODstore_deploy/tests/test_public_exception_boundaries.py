"""Exercise public serialization with failing backend boundaries and success controls."""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

PRIVATE = "Traceback /private/state.sqlite token=private-boundary-test"


def _fail(*args, **kwargs):
    raise OSError(PRIVATE)


def test_public_hall_and_health_responses_keep_failure_visible(monkeypatch):
    from modstore_server import health_api, public_company_hall, public_company_hall_api

    app = FastAPI()
    app.include_router(health_api.router)
    app.include_router(public_company_hall_api.router)
    monkeypatch.setattr(public_company_hall, "build_public_company_hall", _fail)
    monkeypatch.setattr(health_api, "get_session_factory", _fail)
    with TestClient(app) as client:
        hall = client.get("/api/public/company-hall")
        assert hall.status_code == 200
        assert hall.json() == {
            "ok": False,
            "error": "company_hall_unavailable",
            "data": None,
        }
        health = client.get("/health/").json()
        assert health["status"] == "degraded" and health["database"] == "unavailable"
        assert PRIVATE not in json.dumps(health)
        data = {
            "schema": "xcagi.public_company_hall/v1",
            "readonly": True,
            "employees": [],
        }
        monkeypatch.setattr(
            public_company_hall, "build_public_company_hall", lambda **_: data
        )
        assert client.get("/api/public/company-hall").json() == {
            "ok": True,
            "data": data,
        }
        monkeypatch.setattr(
            health_api,
            "get_session_factory",
            lambda: lambda: nullcontext(SimpleNamespace(execute=lambda _: None)),
        )
        assert client.get("/health/").json()["database"] == "ok"


def test_payment_proxy_message_does_not_expose_endpoint_or_exception(monkeypatch):
    from modstore_server.application.payment_gateway import (
        java_payment_unreachable_message,
    )

    monkeypatch.setenv(
        "JAVA_PAYMENT_SERVICE_URL", "http://secret:password@private-host:8080"
    )
    message = java_payment_unreachable_message(OSError(PRIVATE))
    assert message == "Java 支付服务暂时不可用，请稍后查询原支付状态"


def test_workflow_parallel_failures_keep_branch_statuses_and_successful_output(
    monkeypatch,
):
    from modstore_server.workflow_engine import WorkflowEngine

    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_execute_http_request_node", _fail)
    monkeypatch.setattr(engine, "_execute_data_transform_node", _fail)
    result = engine._execute_parallel_node(
        None,
        {"receipt": "input"},
        {
            "branches": [
                {"name": "http", "type": "http_request"},
                {"name": "transform", "type": "data_transform"},
                {"name": "pass", "type": "pass"},
            ]
        },
    )
    branches = result["parallel_result"]
    assert branches["http"] == {"status": "failed", "error": "http_request_failed"}
    assert branches["transform"] == {
        "status": "failed",
        "error": "data_transform_failed",
    }
    assert branches["pass"] == {"status": "completed", "data": {"receipt": "input"}}
    assert PRIVATE not in json.dumps(result)


def test_roster_source_failure_keeps_unknown_gate_and_safe_error(monkeypatch):
    from modstore_server.maintenance_loop import status_roster

    monkeypatch.setattr(
        status_roster.duty_employee_registry, "duty_employee_records", _fail
    )
    result = status_roster._build_roster_alignment({}, _fail, lambda _: [])
    assert result["status"] == "unknown"
    assert result["gate"]["ok"] is False and result["gate"]["action"] == "unknown"
    assert result["error"] == "duty_roster_unavailable"
    assert PRIVATE not in json.dumps(result)


def test_workflow_nonterminal_result_preserves_partial_execution_evidence(monkeypatch):
    import modstore_server.workflow_engine as workflow
    from modstore_server.workflow_engine_workflowengine_mixin01__workflowenginepart01mixin_mixin01 import (
        WorkflowGraphError,
    )

    engine = workflow.WorkflowEngine()
    monkeypatch.setattr(workflow.WorkflowValidator, "validate_workflow", lambda *a: [])
    monkeypatch.setattr(workflow, "_topology_warnings", lambda *a: [])
    steps = [{"node_id": 7, "output_delta": {"receipt": "accepted"}}]

    def run(*args, **kwargs):
        raise WorkflowGraphError(
            PRIVATE, {"receipt": "accepted"}, steps, ["未到达结束节点"]
        )

    monkeypatch.setattr(engine, "_run_graph", run)
    result = engine.run_sandbox(None, SimpleNamespace(id=1), {})
    assert result["ok"] is False and result["errors"] == ["workflow did not reach end"]
    assert result["warnings"] == ["未到达结束节点"] and result["steps"] == steps
    assert result["output"] == {"receipt": "accepted"}
    assert PRIVATE not in json.dumps(result)
