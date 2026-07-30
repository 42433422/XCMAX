from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.print_authorization import (
    _clear_print_authorizations_for_tests,
    issue_document_print_capability,
)
from app.fastapi_routes import ai_assistant


def _client() -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def authenticated_owner(request, call_next):
        # Deliberately set server state rather than using a client header.
        request.state.user_id = 101
        return await call_next(request)

    app.include_router(ai_assistant.router)
    return TestClient(app, raise_server_exceptions=False)


def test_legacy_filename_print_requires_generated_owner_capability(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "shipment_outputs"
    output_dir.mkdir()
    document = output_dir / "delivery-42.xlsx"
    document.write_bytes(b"xlsx")
    _clear_print_authorizations_for_tests()
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    printer = MagicMock()
    printer.print_document.return_value = {"success": True, "message": "已提交"}
    monkeypatch.setattr(ai_assistant, "_printer_svc", lambda: printer)
    client = _client()

    direct = client.post("/api/print/delivery-42.xlsx", json={"order_id": 42})
    assert direct.status_code == 409
    assert direct.json()["error_code"] == "PRINT_CONFIRMATION_REQUIRED"
    printer.print_document.assert_not_called()

    capability = issue_document_print_capability(
        file_path=document,
        owner_user_id=101,
        order_id=42,
    )
    assert capability is not None
    printed = client.post(
        "/api/print/delivery-42.xlsx",
        json={"order_id": 42, "print_token": capability["document_token"]},
    )
    assert printed.status_code == 200
    assert printed.json()["post_print_receipt"]
    printer.print_document.assert_called_once_with(str(document), printer_name=None)

    replay = client.post(
        "/api/print/delivery-42.xlsx",
        json={"order_id": 42, "print_token": capability["document_token"]},
    )
    assert replay.status_code == 409
    assert replay.json()["error_code"] == "PRINT_CONFIRMATION_INVALID"
