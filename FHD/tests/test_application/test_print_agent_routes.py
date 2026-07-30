from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.application.print_authorization import (
    _clear_print_authorizations_for_tests,
    defer_document_print_capability,
    issue_document_print_capability,
    reserve_document_print_capability,
)
from app.fastapi_routes import print_routes


def _client(
    fake_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    authenticated_owner: dict[str, int] | None = None,
) -> TestClient:
    monkeypatch.setattr(print_routes, "_svc", lambda: fake_service)
    print_routes._print_confirm_cache.clear()
    _clear_print_authorizations_for_tests()
    owner_state = authenticated_owner if authenticated_owner is not None else {"user_id": 101}
    app = FastAPI()

    @app.middleware("http")
    async def authenticated_owner(request, call_next):
        # A print capability is valid only for middleware-authenticated state;
        # the X-User-Id header below is intentionally not the authority.
        request.state.user_id = owner_state["user_id"]
        return await call_next(request)

    app.include_router(print_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_print_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "101"
    assert run.status == "completed"
    assert run.intent == f"print_{action}"
    assert run.tool_calls[0].tool_id == "print"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.print.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in run.events
    }


def test_print_routes_execute_side_effects_through_agent_orchestrator(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    document = tmp_path / "document.pdf"
    document.write_bytes(b"%PDF")
    label = tmp_path / "label.png"
    label.write_bytes(b"\x89PNG\r\n")
    svc = MagicMock()
    svc.get_printers.return_value = {
        "success": True,
        "printers": [{"name": "DocPrinter"}, {"name": "LabelPrinter"}],
    }
    svc.save_printer_selection.return_value = {
        "success": True,
        "message": "打印机选择已保存",
    }
    svc.classify_printers.return_value = {
        "document": ["DocPrinter"],
        "label": ["LabelPrinter"],
    }
    svc.print_document.return_value = {"success": True, "message": "文档已提交打印"}
    svc.print_label.return_value = {"success": True, "message": "标签已打印"}
    svc.test_printer.return_value = {"success": True, "message": "测试页已发送"}
    client = _client(svc, monkeypatch)
    document_capability = issue_document_print_capability(
        file_path=document,
        owner_user_id=101,
    )
    assert document_capability is not None

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        selection = client.put(
            "/api/print/printer-selection",
            json={"document_printer": "DocPrinter", "label_printer": "LabelPrinter"},
            headers={"X-User-Id": "101"},
        )
        document_print = client.post(
            "/api/print/document",
            json={
                "file_path": str(document),
                "printer_name": "DocPrinter",
                "use_automation": False,
                "print_token": document_capability["document_token"],
            },
            headers={"X-User-Id": "101"},
        )
        label_print = client.post(
            "/api/print/label",
            json={
                "file_path": str(label),
                "printer_name": "LabelPrinter",
                "copies": 2,
                "require_confirm": False,
            },
            headers={"X-User-Id": "101"},
        )
        test_print = client.post(
            "/api/print/test",
            json={"printer_name": "DocPrinter"},
            headers={"X-User-Id": "101"},
        )

    assert selection.status_code == 200
    assert document_print.status_code == 200
    assert label_print.status_code == 200
    assert test_print.status_code == 200

    svc.save_printer_selection.assert_called_once_with(
        document_printer="DocPrinter",
        label_printer="LabelPrinter",
    )
    svc.print_document.assert_called_once_with(str(document), "DocPrinter", False)
    svc.print_label.assert_called_once_with(str(label), "LabelPrinter", 2)
    svc.test_printer.assert_called_once_with("DocPrinter")

    assert selection.json()["document"] == ["DocPrinter"]
    assert document_print.json()["message"] == "文档已提交打印"
    assert document_print.json()["post_print_receipt"]
    assert label_print.json()["require_confirm"] is False
    assert test_print.json()["message"] == "测试页已发送"

    _assert_print_run(repo, selection.json()["run_id"], "save_printer_selection")
    _assert_print_run(repo, document_print.json()["run_id"], "print_document")
    _assert_print_run(repo, label_print.json()["run_id"], "print_label")
    _assert_print_run(repo, test_print.json()["run_id"], "test")


def test_document_route_rejects_raw_paths_and_foreign_capabilities(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = tmp_path / "document.pdf"
    document.write_bytes(b"%PDF")
    svc = MagicMock()
    client = _client(svc, monkeypatch)

    raw_path = client.post("/api/print/document", json={"file_path": str(document)})
    assert raw_path.status_code == 409
    assert raw_path.json()["error_code"] == "PRINT_CONFIRMATION_REQUIRED"
    svc.print_document.assert_not_called()

    foreign_capability = issue_document_print_capability(
        file_path=document,
        owner_user_id=202,
    )
    assert foreign_capability is not None
    foreign = client.post(
        "/api/print/document",
        json={
            "file_path": str(document),
            "print_token": foreign_capability["document_token"],
        },
    )
    assert foreign.status_code == 403
    assert foreign.json()["error_code"] == "PRINT_CONFIRMATION_OWNER_MISMATCH"
    svc.print_document.assert_not_called()


def test_queued_cups_document_is_reconciled_before_receipt_is_issued(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    document = tmp_path / "document.pdf"
    document.write_bytes(b"%PDF")
    svc = MagicMock()
    svc.print_document.return_value = {
        "success": True,
        "message": "打印任务已提交到 macOS CUPS，正在等待设备完成",
        "printer": "Canon_TS3700_series",
        "job_id": "Canon_TS3700_series-42",
        "print_completed": False,
        "print_state": "queued",
    }
    svc.get_document_print_job_status.return_value = {
        "state": "pending",
        "job_id": "Canon_TS3700_series-42",
        "query_available": True,
    }
    client = _client(svc, monkeypatch)
    capability = issue_document_print_capability(
        file_path=document,
        owner_user_id=101,
        order_id=42,
    )
    assert capability is not None
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        submitted = client.post(
            "/api/print/document",
            json={
                "file_path": str(document),
                "print_token": capability["document_token"],
                "order_id": 42,
            },
        )

    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["print_completed"] is False
    assert payload["print_state"] == "queued"
    assert payload["print_job_token"]
    assert "post_print_receipt" not in payload

    # The spent capability cannot create a duplicate physical job while the
    # current CUPS job is still pending.
    replay = client.post(
        "/api/print/document",
        json={
            "file_path": str(document),
            "print_token": capability["document_token"],
            "order_id": 42,
        },
    )
    assert replay.status_code == 409

    pending = client.get(f"/api/print/jobs/{payload['print_job_token']}")
    assert pending.status_code == 200
    assert pending.json()["success"] is True
    assert pending.json()["print_completed"] is False
    assert "post_print_receipt" not in pending.json()

    svc.get_document_print_job_status.return_value = {
        "state": "completed",
        "job_id": "Canon_TS3700_series-42",
        "query_available": True,
    }
    completed = client.get(f"/api/print/jobs/{payload['print_job_token']}")
    assert completed.status_code == 200
    assert completed.json()["success"] is True
    assert completed.json()["print_completed"] is True
    assert completed.json()["post_print_receipt"]

    svc.get_document_print_job_status.return_value = {
        "state": "aborted",
        "job_id": "Canon_TS3700_series-42",
        "reason": "media-empty-error",
    }
    # Once completed, later probes cannot downgrade the terminal state.
    stable = client.get(f"/api/print/jobs/{payload['print_job_token']}")
    assert stable.status_code == 200
    assert stable.json()["print_state"] == "completed"


def test_pending_job_status_rejects_a_different_authenticated_owner(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = tmp_path / "document.pdf"
    document.write_bytes(b"%PDF")
    svc = MagicMock()
    owner_state = {"user_id": 101}
    client = _client(svc, monkeypatch, owner_state)
    capability = issue_document_print_capability(file_path=document, owner_user_id=101)
    assert capability is not None
    reservation = reserve_document_print_capability(
        capability["document_token"],
        owner_user_id=101,
        file_path=document,
    )
    tracker = defer_document_print_capability(
        reservation,
        printer_name="Canon_TS3700_series",
        job_id="Canon_TS3700_series-42",
    )
    assert tracker["success"] is True

    owner_state["user_id"] = 202
    response = client.get(f"/api/print/jobs/{tracker['print_job_token']}")

    assert response.status_code == 403
    assert response.json()["error_code"] == "PRINT_PENDING_TRACKER_OWNER_MISMATCH"
    svc.get_document_print_job_status.assert_not_called()


def test_workflow_label_dispatch_route_executes_through_agent_orchestrator(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    print_app = MagicMock()
    print_app.print_single_label.return_value = {
        "success": True,
        "message": "标签已打印",
        "model_number": "M-1",
        "quantity": 2,
    }
    product_service = MagicMock()
    product_service.search_products.return_value = [
        {"name": "产品M1", "specification": "红色", "unit": "盒"}
    ]
    svc = MagicMock()
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.print_app_service.get_print_application_service",
            return_value=print_app,
        ),
        patch(
            "app.application.get_product_app_service",
            return_value=product_service,
        ),
    ):
        response = client.post(
            "/api/print/workflow/label-print/dispatch",
            json={"model_number": "M-1", "quantity": 2, "idempotency_key": "idem-1"},
            headers={"X-User-Id": "101"},
        )

    assert response.status_code == 200
    product_service.search_products.assert_called_once_with(keyword="M-1", limit=1)
    print_app.print_single_label.assert_called_once_with(
        product_name="产品M1",
        model_number="M-1",
        specification="红色",
        unit="盒",
        quantity=2,
    )
    payload = response.json()
    assert payload["message"] == "标签已打印"
    _assert_print_run(repo, payload["run_id"], "workflow_label_dispatch")
