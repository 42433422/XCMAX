from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.print_authorization import (
    _clear_print_authorizations_for_tests,
    consume_post_print_receipt,
    finish_document_print_capability,
    issue_document_print_capability,
    reserve_document_print_capability,
)
from app.services.tools_payload_legacy import dispatch_legacy_tool_payload
from app.services.tools_workflow_registered import _registered_router_print


def _legacy_json(payload, status_code: int = 200):
    return {"payload": payload, "status_code": status_code}


def test_capability_is_exact_owner_bound_and_yields_one_time_print_receipt(tmp_path) -> None:
    document = tmp_path / "shipment.xlsx"
    document.write_bytes(b"xlsx")
    _clear_print_authorizations_for_tests()

    capability = issue_document_print_capability(
        file_path=document,
        owner_user_id=101,
        order_id=42,
    )
    assert capability is not None

    denied = reserve_document_print_capability(
        capability["document_token"],
        owner_user_id=202,
        file_path=document,
        order_id=42,
    )
    assert denied["success"] is False
    assert denied["error_code"] == "PRINT_CONFIRMATION_OWNER_MISMATCH"

    reserved = reserve_document_print_capability(
        capability["document_token"],
        owner_user_id=101,
        file_path=document,
        order_id=42,
    )
    assert reserved["success"] is True
    receipt = finish_document_print_capability(reserved, print_succeeded=True)
    assert receipt

    wrong_file = tmp_path / "other.xlsx"
    wrong_file.write_bytes(b"xlsx")
    wrong_artifact = consume_post_print_receipt(
        receipt,
        owner_user_id=101,
        file_path=wrong_file,
        order_id=42,
    )
    assert wrong_artifact["success"] is False
    assert wrong_artifact["error_code"] == "PRINT_RECEIPT_ARTIFACT_MISMATCH"

    consumed = consume_post_print_receipt(
        receipt,
        owner_user_id=101,
        file_path=document,
        order_id=42,
    )
    assert consumed == {"success": True, "file_path": str(document), "order_id": 42}

    replay = consume_post_print_receipt(
        receipt,
        owner_user_id=101,
        file_path=document,
        order_id=42,
    )
    assert replay["success"] is False
    assert replay["error_code"] == "PRINT_RECEIPT_INVALID"


def test_failed_print_releases_capability_for_a_user_retry(tmp_path) -> None:
    document = tmp_path / "shipment.xlsx"
    document.write_bytes(b"xlsx")
    _clear_print_authorizations_for_tests()
    capability = issue_document_print_capability(file_path=document, owner_user_id=101)
    assert capability is not None

    first = reserve_document_print_capability(
        capability["document_token"],
        owner_user_id=101,
        file_path=document,
    )
    assert first["success"] is True
    assert finish_document_print_capability(first, print_succeeded=False) is None

    retry = reserve_document_print_capability(
        capability["document_token"],
        owner_user_id=101,
        file_path=document,
    )
    assert retry["success"] is True


def test_legacy_print_tool_requires_the_same_owner_bound_capability(tmp_path) -> None:
    document = tmp_path / "shipment.xlsx"
    document.write_bytes(b"xlsx")
    _clear_print_authorizations_for_tests()
    service = MagicMock()
    service.print_document.return_value = {"success": True, "message": "已提交"}

    with patch("app.services.get_printer_service", return_value=service):
        raw = dispatch_legacy_tool_payload(
            "print",
            "print_document",
            {"file_path": str(document)},
            json_response_fn=_legacy_json,
            hdr_getter=lambda _name, _default=None: _default,
            parse_order_text_fn=lambda _text: {},
            owner_user_id=101,
        )
    assert raw["status_code"] == 409
    assert raw["payload"]["error_code"] == "PRINT_CONFIRMATION_REQUIRED"
    service.print_document.assert_not_called()

    capability = issue_document_print_capability(file_path=document, owner_user_id=101)
    assert capability is not None
    with patch("app.services.get_printer_service", return_value=service):
        printed = dispatch_legacy_tool_payload(
            "print",
            "print_document",
            {"file_path": str(document), "print_token": capability["document_token"]},
            json_response_fn=_legacy_json,
            hdr_getter=lambda _name, _default=None: _default,
            parse_order_text_fn=lambda _text: {},
            owner_user_id=101,
        )
    assert printed["status_code"] == 200
    assert printed["payload"]["post_print_receipt"]
    service.print_document.assert_called_once_with(str(document), None, False)


def test_registered_print_tool_refuses_direct_document_print() -> None:
    with patch("app.services.get_printer_service") as service_factory:
        result = _registered_router_print(
            "print_document",
            {"file_path": "/tmp/anything.xlsx"},
            {},
            "normal",
            "",
        )
    assert result["success"] is False
    assert result["error_code"] == "PRINT_CAPABILITY_ROUTE_REQUIRED"
    service_factory.return_value.print_document.assert_not_called()
