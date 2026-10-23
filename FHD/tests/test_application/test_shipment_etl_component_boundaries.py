"""Shipment writes, compensation and deduplication must describe the same state."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from app.application import shipment_excel_etl_app_service as etl
from app.application.shipment_etl.batching import _scan


def _note(number):
    return {
        "unit_name": "合成验收客户",
        "order_number": number,
        "order_date": "2026-10-22",
        "source_kind": "delivery_note",
        "profile_target": "shipment",
        "items": [
            {
                "model_number": "SYNTH-1",
                "product_name": "合成产品",
                "quantity_tins": 1,
                "quantity_kg": 10,
                "unit_price": 2,
                "amount": 20,
            }
        ],
    }


@pytest.fixture
def import_ports(tmp_path, monkeypatch):
    from app.application.excel_etl_kb import reset_excel_etl_kb_for_tests
    from app.application.shipment_etl_profile import clear_profile_cache

    kb_path = tmp_path / "kb.json"
    monkeypatch.setenv("FHD_EXCEL_ETL_KB_PATH", str(kb_path))
    reset_excel_etl_kb_for_tests(kb_path)
    clear_profile_cache()
    recorded = set()
    service = MagicMock()
    service.cancel_shipment.return_value = {"success": True}
    service.delete_shipment.return_value = {"success": True}
    monkeypatch.setattr("app.bootstrap.get_shipment_app_service", lambda: service)
    monkeypatch.setattr(etl, "_is_fingerprint_imported", lambda tenant, fp: fp in recorded)
    monkeypatch.setattr(
        etl, "_record_fingerprint_now", lambda tenant, fp, **kwargs: recorded.add(fp)
    )
    monkeypatch.setattr(
        "app.application.shipment_excel_etl_fingerprint_store.delete_fingerprint",
        lambda tenant, fp: recorded.discard(fp),
    )
    yield service, recorded
    clear_profile_cache()


def test_failed_compensation_keeps_fingerprint_and_retry_skips_active_shipment(import_ports):
    service, recorded = import_ports
    service.create_shipment.side_effect = [
        {"success": True, "shipment": {"id": 101}},
        {"success": False, "message": "second shipment rejected"},
        {"success": False, "message": "second shipment still rejected"},
    ]
    service.cancel_shipment.return_value = {"success": False, "message": "cannot cancel"}
    service.delete_shipment.return_value = {"success": False, "message": "cannot delete"}
    notes = [_note("SYNTH-A"), _note("SYNTH-B")]
    first = etl.execute_shipment_excel_etl("", notes=deepcopy(notes), import_products=False)
    assert first["success"] is False
    assert first["safe_to_retry"] is False
    assert first["shipment_ids"] == [101]
    assert etl.note_fingerprint(notes[0]) in recorded

    retried = etl.execute_shipment_excel_etl("", notes=deepcopy(notes), import_products=False)
    assert retried["shipment_skipped"] == 1
    assert service.create_shipment.call_count == 3


def test_service_exception_compensates_known_writes_and_marks_unknown_outcome(import_ports):
    service, recorded = import_ports
    service.create_shipment.side_effect = [
        {"success": True, "shipment": {"id": 101}},
        RuntimeError("connection lost while creating shipment"),
    ]
    result = etl.execute_shipment_excel_etl(
        "",
        notes=[_note("SYNTH-A"), _note("SYNTH-B")],
        import_products=False,
    )
    assert result["success"] is False
    assert result["compensated"] == [101]
    assert recorded == set()
    assert result["safe_to_retry"] is False
    assert result["requires_reconciliation"] is True
    service.cancel_shipment.assert_called_once_with(101)


def test_identical_notes_in_one_batch_are_created_once(import_ports):
    service, _ = import_ports
    service.create_shipment.return_value = {"success": True, "shipment": {"id": 101}}
    note = _note("SYNTH-A")
    result = etl.execute_shipment_excel_etl(
        "",
        notes=[note, deepcopy(note)],
        import_products=False,
    )
    assert result["success"] is True
    assert result["shipment_created"] == 1
    assert result["shipment_skipped"] == 1
    service.create_shipment.assert_called_once()


def test_fingerprint_failure_does_not_claim_a_completed_write_is_safe_to_repeat(
    import_ports, monkeypatch
):
    service, _ = import_ports
    service.create_shipment.return_value = {"success": True, "shipment": {"id": 101}}

    def unavailable(*args, **kwargs):
        raise OSError("deduplication store unavailable")

    monkeypatch.setattr(etl, "_record_fingerprint_now", unavailable)
    result = etl.execute_shipment_excel_etl("", notes=[_note("SYNTH-A")], import_products=False)
    assert result["success"] is True
    assert result["shipment_created"] == 1
    assert result["safe_to_retry"] is False
    assert result["fingerprint_errors"]
    service.cancel_shipment.assert_not_called()


def test_batch_does_not_report_success_when_a_file_is_rejected_before_writing(
    import_ports, tmp_path, monkeypatch
):
    source = tmp_path / "synthetic.xlsx"
    source.write_bytes(b"synthetic placeholder; parsing is replaced below")
    monkeypatch.setattr(
        etl,
        "execute_shipment_excel_etl",
        lambda *args, **kwargs: {
            "success": False,
            "error_code": "ledger_confirm_required",
            "message": "confirmation required",
        },
    )
    result = etl.batch_execute_shipment_excel_etl(tmp_path, workspace_root=tmp_path, dry_run=True)
    assert result["success"] is False
    assert result["failed_file_count"] == 1
    assert result["shipment_created"] == 0
    assert result["files"][0]["error_code"] == "ledger_confirm_required"
    assert "失败文件 1" in result["message"]


def test_batch_pattern_cannot_escape_the_selected_directory(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.xlsx"
    outside.write_text("fixture", encoding="utf-8")
    try:
        result = _scan(tmp_path, "../*.xlsx", tmp_path)
        assert result == {
            "success": False,
            "message": "非法文件模式",
            "error_code": "unsafe_pattern",
            "files": [],
        }
    finally:
        outside.unlink(missing_ok=True)


def test_failed_fingerprint_cleanup_does_not_claim_a_rollback_is_retryable(
    import_ports, monkeypatch
):
    service, recorded = import_ports
    service.create_shipment.side_effect = [
        {"success": True, "shipment": {"id": 101}},
        {"success": False, "message": "second shipment rejected"},
    ]

    def unavailable(tenant, fingerprint):
        raise OSError("deduplication store unavailable during compensation")

    monkeypatch.setattr(
        "app.application.shipment_excel_etl_fingerprint_store.delete_fingerprint", unavailable
    )
    result = etl.execute_shipment_excel_etl(
        "", notes=[_note("SYNTH-A"), _note("SYNTH-B")], import_products=False
    )
    assert result["success"] is False
    assert result["shipment_created"] == 0
    assert result["compensated"] == [101]
    assert etl.note_fingerprint(_note("SYNTH-A")) in recorded
    assert result["safe_to_retry"] is False
    assert result["fingerprint_errors"]


def test_dry_run_deduplicates_without_constructing_any_writer(import_ports, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("a dry run must not construct business writers")

    monkeypatch.setattr("app.bootstrap.get_shipment_app_service", unexpected)
    monkeypatch.setattr(
        "app.services.tools_workflow_registered._execute_excel_import_records", unexpected
    )
    note = _note("SYNTH-A")
    result = etl.execute_shipment_excel_etl("", notes=[note, deepcopy(note)], dry_run=True)
    assert result["success"] is True
    assert result["would_create"] == 1
    assert result["would_skip"] == 1
    assert result["closed_loop"] is False


def test_product_import_failure_prevents_shipment_service_construction(import_ports, monkeypatch):
    def unexpected():
        pytest.fail("shipments must not be created after a product import rejection")

    monkeypatch.setattr("app.bootstrap.get_shipment_app_service", unexpected)
    monkeypatch.setattr(
        "app.services.tools_workflow_registered._execute_excel_import_records",
        lambda records: {"success": False, "message": "product validation rejected"},
    )
    result = etl.execute_shipment_excel_etl("", notes=[_note("SYNTH-A")])
    assert result["success"] is False
    assert result["error_code"] == "product_import_failed"
    assert result["closed_loop"] is False


def test_explicit_non_idempotent_import_keeps_repeated_notes(import_ports):
    service, recorded = import_ports
    service.create_shipment.side_effect = [
        {"success": True, "shipment": {"id": 101}},
        {"success": True, "shipment": {"id": 102}},
    ]
    note = _note("SYNTH-A")
    result = etl.execute_shipment_excel_etl(
        "", notes=[note, deepcopy(note)], import_products=False, idempotent=False
    )
    assert result["success"] is True
    assert result["shipment_ids"] == [101, 102]
    assert result["shipment_created"] == 2
    assert result["shipment_skipped"] == 0
    assert service.create_shipment.call_count == 2
    assert recorded == set()
    assert result["safe_to_retry"] is False
