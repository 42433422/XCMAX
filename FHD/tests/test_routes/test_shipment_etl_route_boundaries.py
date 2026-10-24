"""Exercise upload ownership and public failure responses at the ETL boundary."""

from __future__ import annotations

import asyncio
import inspect
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.fastapi_routes import excel_extract as _excel_extract  # noqa: F401
from app.fastapi_routes import excel_extract_shipment as api


async def _call(name: str, **overrides: Any) -> JSONResponse:
    endpoint = getattr(api, name)
    values = {
        name: getattr(parameter.default, "default", parameter.default)
        for name, parameter in inspect.signature(endpoint).parameters.items()
    }
    if "_user" in values:
        values["_user"] = None
    values.update(overrides)
    response = await endpoint(**values)
    assert isinstance(response, JSONResponse)
    return response


@pytest.fixture
def etl_adapters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Mock:
    service = Mock()
    service.preview.return_value = {"success": True, "notes": []}
    service.execute.return_value = {"success": True, "shipment_created": 1}
    service.batch_execute.return_value = {"success": True, "shipment_created": 1}
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(api, "TEMP_EXCEL_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.application.shipment_excel_etl_app_service.get_shipment_excel_etl_app_service",
        lambda: service,
    )
    monkeypatch.setattr(
        "app.application.shipment_excel_etl_app_service.preview_shipment_excel_etl",
        service.preview,
    )
    monkeypatch.setattr(
        "app.application.shipment_excel_etl_ocr.parse_ocr_document", service.preview
    )
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["preview", "execute", "ocr_preview"])
async def test_successful_upload_closes_stream_and_keeps_next_step_input(
    route: str, etl_adapters: Mock, tmp_path: Path
) -> None:
    upload = UploadFile(io.BytesIO(b"spreadsheet"), filename="customer.xlsx")
    response = await _call(f"shipment_etl_{route}", file=upload)
    assert response.status_code == 200
    assert upload.file.closed
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and files[0].read_bytes() == b"spreadsheet"
    if route == "preview":
        assert json.loads(bytes(response.body))["uploaded_temp_path"] == str(files[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["preview", "execute", "ocr_preview"])
@pytest.mark.parametrize("raises", [False, True])
async def test_failed_upload_releases_owned_file_and_input(
    route: str, raises: bool, etl_adapters: Mock, tmp_path: Path
) -> None:
    method = etl_adapters.execute if route == "execute" else etl_adapters.preview
    method.return_value = {"success": False, "message": "password=private"}
    if raises:
        method.side_effect = RuntimeError("password=private")
    upload = UploadFile(io.BytesIO(b"rejected"), filename="shipment.xlsx")
    response = await _call(f"shipment_etl_{route}", file=upload)
    assert response.status_code == (500 if raises else 400)
    assert b"private" not in bytes(response.body)
    assert list(tmp_path.iterdir()) == []
    assert upload.file.closed


@pytest.mark.asyncio
async def test_invalid_notes_does_not_leave_an_upload(etl_adapters: Mock, tmp_path: Path) -> None:
    upload = UploadFile(io.BytesIO(b"rejected"), filename="shipment.xlsx")
    response = await _call("shipment_etl_execute", file=upload, notes_json="{")
    assert response.status_code == 400
    assert json.loads(bytes(response.body))["error_code"] == "bad_notes"
    etl_adapters.execute.assert_not_called()
    assert list(tmp_path.iterdir()) == []
    assert upload.file.closed


@pytest.mark.asyncio
async def test_cancelled_upload_closes_stream_and_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch, etl_adapters: Mock, tmp_path: Path
) -> None:
    upload = UploadFile(io.BytesIO(b"cancelled"), filename="shipment.xlsx")
    monkeypatch.setattr(upload, "read", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await _call("shipment_etl_preview", file=upload)
    assert upload.file.closed
    assert list(tmp_path.iterdir()) == []
    etl_adapters.preview.assert_not_called()


@pytest.mark.asyncio
async def test_path_failure_closes_upload(
    monkeypatch: pytest.MonkeyPatch, etl_adapters: Mock, tmp_path: Path
) -> None:
    monkeypatch.setattr(api, "_temporary_upload_path", Mock(side_effect=OSError("private")))
    upload = UploadFile(io.BytesIO(b"rejected"), filename="shipment.xlsx")
    response = await _call("shipment_etl_preview", file=upload)
    assert response.status_code == 500
    assert b"private" not in bytes(response.body)
    assert upload.file.closed
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_collision_never_overwrites_or_deletes_an_existing_file(
    monkeypatch: pytest.MonkeyPatch, etl_adapters: Mock, tmp_path: Path
) -> None:
    existing = tmp_path / "already-accepted.xlsx"
    existing.write_bytes(b"original")
    monkeypatch.setattr(api, "_temporary_upload_path", lambda *_args: str(existing))
    upload = UploadFile(io.BytesIO(b"replacement"), filename="shipment.xlsx")
    response = await _call("shipment_etl_preview", file=upload)
    assert response.status_code == 500
    assert existing.read_bytes() == b"original"
    assert upload.file.closed
    etl_adapters.preview.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["preview", "execute", "ocr_preview"])
async def test_caller_owned_path_survives_failure(
    route: str, etl_adapters: Mock, tmp_path: Path
) -> None:
    existing = tmp_path / "caller-owned.xlsx"
    existing.write_bytes(b"original")
    method = etl_adapters.execute if route == "execute" else etl_adapters.preview
    method.side_effect = RuntimeError("fail")
    response = await _call(f"shipment_etl_{route}", file=None, file_path=str(existing))
    assert response.status_code == 500
    assert existing.read_bytes() == b"original"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["execute", "batch_execute"])
async def test_failed_dry_run_is_an_error_and_drops_private_details(
    route: str, etl_adapters: Mock
) -> None:
    method = getattr(etl_adapters, route)
    method.return_value = {
        "success": False,
        "dry_run": True,
        "message": "password=private",
        "errors": ["/private/database"],
        "would_create": 2,
    }
    params = {"notes_json": "[]"} if route == "execute" else {"directory": "/tmp"}
    response = (
        await _call(f"shipment_etl_{route}", file=None, **params)
        if route == "execute"
        else await _call(f"shipment_etl_{route}", **params)
    )
    assert response.status_code == 400
    payload = json.loads(bytes(response.body))
    assert payload["success"] is False and payload["would_create"] == 2
    assert "private" not in json.dumps(payload)


@pytest.mark.parametrize("name", ["get_extract_logs", "get_extract_log", "get_preview"])
def test_log_read_errors_do_not_expose_backend_details(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.bootstrap.get_extract_log_service", Mock(side_effect=RuntimeError("password=private"))
    )
    response = getattr(api, name)(*(() if name == "get_extract_logs" else (1,)))
    assert response.status_code == 500
    assert b"private" not in bytes(response.body)


def test_successful_dry_run_keeps_preview_contract() -> None:
    result = {"success": True, "dry_run": True, "notes": [{"unit_name": "demo"}]}
    assert api._safe_failed_etl_result(result, "failed") is result


@pytest.mark.asyncio
async def test_upload_is_read_in_bounded_chunks(
    monkeypatch: pytest.MonkeyPatch, etl_adapters: Mock
) -> None:
    upload = UploadFile(io.BytesIO(b"x" * (2 * 1024 * 1024 + 7)), filename="large.xlsx")
    reader = AsyncMock(wraps=upload.read)
    monkeypatch.setattr(upload, "read", reader)
    response = await _call("shipment_etl_preview", file=upload)
    assert response.status_code == 200
    assert reader.await_count == 4
    assert all(call.args == (1024 * 1024,) for call in reader.await_args_list)


@pytest.mark.asyncio
async def test_stager_owns_partial_file_on_cancellation_without_facade_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.fastapi_routes.shipment_etl.uploads import UploadStager

    path = tmp_path / "partial.xlsx"
    upload = UploadFile(io.BytesIO(b""), filename="partial.xlsx")
    monkeypatch.setattr(upload, "read", AsyncMock(side_effect=[b"partial", asyncio.CancelledError]))
    monkeypatch.setattr(api, "_temporary_upload_path", Mock(side_effect=AssertionError("facade")))
    stager = UploadStager(lambda *_args: str(path), api.logger)
    with pytest.raises(asyncio.CancelledError):
        async with stager.open(upload, "", prefix="etl"):
            pytest.fail("A cancelled file must never reach the application")
    assert upload.file.closed and not path.exists()


@pytest.mark.asyncio
async def test_ocr_upload_uses_derived_spreadsheet_and_preserves_provenance(
    monkeypatch: pytest.MonkeyPatch, etl_adapters: Mock, tmp_path: Path
) -> None:
    derived = tmp_path / "ocr.xlsx"
    derived.write_bytes(b"ocr result")
    metadata = {"file_path": str(derived), "page_count": 1}
    parser = Mock(return_value={"success": True, "ocr": metadata, "source_path": "scan.png"})
    monkeypatch.setattr("app.application.shipment_excel_etl_ocr.parse_ocr_document", parser)
    upload = UploadFile(io.BytesIO(b"image"), filename="scan.png")
    response = await _call("shipment_etl_ocr_preview", file=upload, include_ledger="1")
    assert response.status_code == 200 and upload.file.closed
    payload = json.loads(bytes(response.body))
    assert payload["ocr"] == metadata and payload["source_path"] == "scan.png"
    parser.assert_called_once()
    etl_adapters.preview.assert_called_once_with(
        str(derived), include_ledger=True, workspace_root=None
    )
    etl_adapters.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "status"),
    [("unsafe_path", 400), ("ledger_confirm_required", 409), ("direct_execute_denied", 403)],
)
async def test_execution_gate_statuses_survive_sanitization(
    code: str, status: int, etl_adapters: Mock
) -> None:
    etl_adapters.execute.return_value = {"success": False, "error_code": code, "message": "private"}
    response = await _call("shipment_etl_execute", file=None, notes_json="[]")
    assert response.status_code == status
    payload = json.loads(bytes(response.body))
    assert payload["error_code"] == code and payload["message"] != "private"


@pytest.mark.asyncio
async def test_notes_and_template_capture_keep_form_contracts(
    monkeypatch: pytest.MonkeyPatch, etl_adapters: Mock, tmp_path: Path
) -> None:
    notes = [{"unit_name": "form customer", "items": []}]
    capture = Mock(
        side_effect=lambda result, **_kwargs: {**result, "template_ingest": {"success": True}}
    )
    monkeypatch.setattr(
        "app.application.office_template_ingest_app_service.attach_template_ingest_to_etl_result",
        capture,
    )
    upload = UploadFile(io.BytesIO(b"workbook"), filename="source.xlsx")
    response = await _call(
        "shipment_etl_execute",
        file=upload,
        workspace_root=f" {tmp_path} ",
        notes_json=json.dumps({"notes": notes}),
        import_products="0",
        import_shipments="off",
        idempotent="yes",
        include_ledger="auto",
        confirm_ledger="on",
        dry_run="true",
        direct="1",
        force_shipment_target="yes",
        save_as_template="1",
        template_name=" Template ",
        template_scope=" tenant ",
    )
    assert response.status_code == 200 and upload.file.closed
    accepted = next(tmp_path.iterdir())
    etl_adapters.execute.assert_called_once_with(
        str(accepted),
        import_products=False,
        import_shipments=False,
        idempotent=True,
        include_ledger="auto",
        confirm_ledger=True,
        dry_run=True,
        direct=True,
        force_shipment_target=True,
        notes=notes,
        workspace_root=str(tmp_path),
    )
    capture.assert_called_once_with(
        etl_adapters.execute.return_value,
        file_path=str(accepted),
        save_as_template=True,
        template_name="Template",
        template_scope="tenant",
        source="shipment_excel_etl_execute",
    )
    assert json.loads(bytes(response.body))["template_ingest"]["success"] is True


@pytest.mark.asyncio
async def test_mounted_template_preview_regeneration_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.application import excel_etl_kb
    from app.application.shipment_etl_profile import clear_profile_cache

    monkeypatch.setattr(
        excel_etl_kb, "_KB", excel_etl_kb.ExcelEtlKnowledgeBase(tmp_path / "kb.json")
    )
    monkeypatch.setenv("FHD_EXCEL_ETL_DEFAULT_TARGET", "shipment")
    monkeypatch.setenv("FHD_SHIPMENT_ETL_LLM", "0")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("FHD_EXCEL_ETL_ALLOW_BUILTIN", raising=False)
    monkeypatch.setattr(api, "TEMP_EXCEL_DIR", str(tmp_path))
    clear_profile_cache()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_legacy_shipment_etl_access] = lambda: None
    app.dependency_overrides[api.require_identified_user] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            generated = await client.post(
                "/api/excel/data/shipment-etl/generate-template", data={"unit_name": "回归测试客户"}
            )
            assert generated.status_code == 200, generated.text
            source = Path(generated.json()["file_path"])
            assert source.parent == tmp_path and source.is_file()
            preview = await client.post(
                "/api/excel/data/shipment-etl/preview",
                data={"file_path": str(source), "include_ledger": "0"},
            )
            assert preview.status_code == 200, preview.text
            assert preview.json()["notes"][0]["unit_name"] == "回归测试客户"
            rewritten = await client.post(
                "/api/excel/data/shipment-etl/regenerate",
                data={
                    "file_path": str(source),
                    "include_ledger": "0",
                    "workspace_root": str(tmp_path),
                },
            )
            assert rewritten.status_code == 200, rewritten.text
            assert rewritten.json()["fingerprint_match"] is True
            assert Path(rewritten.json()["generated"]["file_path"]).is_file()
            denied = await client.post(
                "/api/excel/data/shipment-etl/generate-template",
                data={"output_path": str(tmp_path / ".." / "outside.xlsx")},
            )
            assert denied.status_code == 400 and denied.json()["error_code"] == "unsafe_path"
            assert not (tmp_path.parent / "outside.xlsx").exists()
    finally:
        clear_profile_cache()
