import asyncio
import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.application.autonomy import maintenance_console as svc

JOB = "eaf2fd6d-c7fa-48d4-9ed0-b682ad85eca1"


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "XCAGI_RUNDECK_JOBS", json.dumps({"restart_service": JOB, "clear_logs": JOB})
    )
    monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(tmp_path / "approval.jsonl"))
    monkeypatch.setattr(svc, "append_autonomy_audit", Mock())
    return tmp_path


@pytest.mark.parametrize(
    "item",
    [
        {"job": {"id": str(uuid4())}, "status": "running"},
        {"job": {"id": JOB}, "status": "succeeded"},
    ],
)
def test_cancel_rejects_foreign_or_finished_execution(configured, monkeypatch, item):
    api = Mock(return_value=item)
    monkeypatch.setattr(svc, "api", api)
    with pytest.raises(ValueError):
        svc.cancel(10, "operator")
    assert api.call_count == 1


def test_binding_change_rejects_approved_payload(configured):
    with pytest.raises(ValueError):
        svc.perform({"kind": "restart_service", "job_id": str(uuid4()), "request_id": str(uuid4())})


def test_snapshot_does_not_claim_recovery(configured, monkeypatch):
    monkeypatch.setattr(
        svc, "api", lambda *args: {"executions": [{"id": 1, "status": "succeeded"}]}
    )
    data = svc.snapshot()
    assert data["executions"][0]["recovery"] == "unverified"
    assert "token" not in json.dumps(data)


def test_unconfigured_action(configured, monkeypatch):
    perform = Mock()
    monkeypatch.setattr(svc, "perform", perform)
    with pytest.raises(ValueError):
        svc.request_run("delete_user_data", str(uuid4()), "operator")
    perform.assert_not_called()


def test_gate_precedes_service(configured, monkeypatch):
    from fastapi.responses import JSONResponse

    from app.fastapi_routes.admin_control.autonomy import AutonomyAdmin

    service = Mock()
    monkeypatch.setattr(svc, "snapshot", service)
    controller = AutonomyAdmin(
        errors=Mock(),
        gate=lambda request: JSONResponse({}, status_code=403),
        approver=lambda request: "",
        duty_health=Mock(),
    )
    response = asyncio.run(controller.admin_maintenance_tasks(Mock()))
    assert response.status_code == 403
    service.assert_not_called()


def test_missing_upstream_auth_does_not_invalidate_admin_session(monkeypatch):
    from unittest.mock import AsyncMock

    from app.fastapi_routes.admin_control.market_gateway import MarketGateway

    transport = Mock()
    transport.authorization_header.return_value = ""
    transport.resolve_authorization = AsyncMock(return_value="")
    gateway = MarketGateway(
        errors=Mock(),
        gate=lambda request: None,
        proxy=AsyncMock(),
        maintenance=AsyncMock(),
        transport=lambda: transport,
    )
    response = asyncio.run(gateway._market_admin_proxy(Mock(), "GET", "/api/ops/orchestrate/jobs"))
    assert response.status_code == 409
    assert b"upstream_auth_unavailable" in response.body
    transport.request.assert_not_called()


def test_log_cleanup_requires_review(configured, monkeypatch):
    perform = Mock()
    monkeypatch.setattr(svc, "perform", perform)
    result = svc.request_run("clear_logs", str(uuid4()), "operator")
    assert result["state"] == "pending_approval"
    perform.assert_not_called()
    record = svc.approvals.get_action_state(result["action_id"])
    assert record["payload"]["job_id"] == JOB
    assert record["payload"]["actor"] == "operator"
