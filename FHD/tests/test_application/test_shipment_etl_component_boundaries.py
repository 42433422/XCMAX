"""Shipment writes, compensation and deduplication must describe the same state."""

import os
import struct
from copy import deepcopy
from pathlib import Path
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
    from app.application.shipment_etl_profile import clear_profile_cache
    from app.domain.app_pure.excel_etl_kb import reset_excel_etl_kb_for_tests

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
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
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


def test_batch_scan_rejects_a_file_symlink_outside_selected_directory(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    selected = workspace / "incoming"
    selected.mkdir(parents=True)
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    outside = tmp_path / "private.xlsx"
    outside.write_bytes(b"private fixture")
    link = selected / "redirect.xlsx"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    result = _scan(selected, "*.xlsx", workspace)

    assert result == {
        "success": False,
        "message": "非法目录项",
        "error_code": "unsafe_path",
        "files": [],
    }


def test_batch_scan_uses_only_names_from_the_selected_directory(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    selected = workspace / "incoming"
    selected.mkdir(parents=True)
    (selected / "one.xlsx").write_bytes(b"synthetic")
    (selected / "ignore.csv").write_bytes(b"synthetic")
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))

    result = _scan(selected, "*.xlsx", workspace)

    assert result.root == selected
    assert result.paths == [selected / "one.xlsx"]


def test_batch_scan_rejects_a_directory_symlink_outside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    selected = workspace / "incoming-link"
    outside = tmp_path / "private"
    outside.mkdir(parents=True)
    workspace.mkdir()
    (outside / "private.xlsx").write_bytes(b"private fixture")
    try:
        selected.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name == "nt":
            pytest.skip(f"Windows runner cannot create a test reparse point: {exc}")
        raise
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))

    result = _scan(selected, "*.xlsx", workspace)

    assert result == {
        "success": False,
        "message": "非法目录",
        "error_code": "unsafe_path",
        "files": [],
    }


def test_batch_scan_keeps_enumeration_pinned_when_directory_path_is_swapped(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security
    from app.application.shipment_etl import directory_listing

    workspace = tmp_path / "workspace"
    selected = workspace / "incoming"
    outside = tmp_path / "private"
    selected.mkdir(parents=True)
    outside.mkdir()
    (selected / "trusted.xlsx").write_bytes(b"trusted fixture")
    (outside / "private.xlsx").write_bytes(b"private fixture")
    moved = workspace / "moved-incoming"
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    enumerated: list[str] = []

    if os.name == "nt":
        native_list = directory_listing._windows_directory_names

        def swap_then_list(directory_fd):
            _replace_with_directory_symlink(selected, moved, outside)
            enumerated.extend(native_list(directory_fd))
            return enumerated

        monkeypatch.setattr(directory_listing, "_windows_directory_names", swap_then_list)
    else:
        native_list = directory_listing.os.listdir

        def swap_then_list(directory_fd):
            _replace_with_directory_symlink(selected, moved, outside)
            enumerated.extend(native_list(directory_fd))
            return enumerated

        monkeypatch.setattr(directory_listing.os, "listdir", swap_then_list)
        monkeypatch.setattr(
            directory_listing.os,
            "supports_fd",
            set(directory_listing.os.supports_fd) | {swap_then_list},
        )

    try:
        result = _scan(selected, "*.xlsx", workspace)
        assert "trusted.xlsx" in enumerated
        assert "private.xlsx" not in enumerated
        assert not hasattr(result, "paths")
        assert result["error_code"] == "unsafe_path"
    finally:
        if selected.is_symlink():
            selected.unlink()
        if moved.exists():
            moved.rename(selected)


def _replace_with_directory_symlink(selected: Path, moved: Path, outside: Path) -> None:
    selected.rename(moved)
    try:
        selected.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        selected.unlink(missing_ok=True)
        moved.rename(selected)
        if os.name == "nt":
            pytest.skip(f"Windows runner cannot create a test reparse point: {exc}")
        raise


def test_batch_scan_preserves_permission_errors(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security

    workspace = tmp_path / "workspace"
    selected = workspace / "incoming"
    selected.mkdir(parents=True)
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))

    def deny_listing(*args, **kwargs):
        raise PermissionError("synthetic permission denial")

    monkeypatch.setattr(security, "list_etl_directory_names", deny_listing)
    with pytest.raises(PermissionError, match="synthetic permission denial"):
        _scan(selected, "*.xlsx", workspace)


def _windows_directory_record(name: str, *, next_offset: int = 0) -> bytearray:
    name_bytes = name.encode("utf-16-le")
    record = bytearray(104 + len(name_bytes))
    struct.pack_into("<I", record, 0, next_offset)
    struct.pack_into("<I", record, 60, len(name_bytes))
    record[104:] = name_bytes
    return record


def test_batch_scan_windows_directory_page_parser_accepts_multiple_entries():
    from app.application.shipment_etl.directory_listing import _parse_windows_directory_page

    first_name = "trusted.xlsx"
    first_bytes = first_name.encode("utf-16-le")
    first_next = (104 + len(first_bytes) + 7) // 8 * 8
    page = bytearray(first_next + 104 + len("second.xlsx".encode("utf-16-le")))
    page[: 104 + len(first_bytes)] = _windows_directory_record(first_name, next_offset=first_next)
    page[first_next:] = _windows_directory_record("second.xlsx")

    assert _parse_windows_directory_page(bytes(page)) == [first_name, "second.xlsx"]


def test_batch_scan_windows_directory_information_class_values():
    from app.application.shipment_etl import directory_listing

    assert directory_listing._FILE_ID_BOTH_DIRECTORY_INFO == 10
    assert directory_listing._FILE_ID_BOTH_DIRECTORY_RESTART_INFO == 11


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("short_header", "truncated Windows directory entry header"),
        ("overlap", "invalid Windows directory entry offset"),
        ("misaligned", "invalid Windows directory entry offset"),
        ("past_page", "invalid Windows directory entry offset"),
        ("odd_name", "invalid Windows directory entry filename length"),
        ("past_page_name", "invalid Windows directory entry filename length"),
    ],
)
def test_batch_scan_windows_directory_page_parser_rejects_bad_bounds(mutation, message):
    from app.application.shipment_etl.directory_listing import _parse_windows_directory_page

    page = _windows_directory_record("x.xlsx")
    if mutation == "short_header":
        page = page[:80]
    elif mutation == "overlap":
        struct.pack_into("<I", page, 0, 8)
    elif mutation == "misaligned":
        struct.pack_into("<I", page, 0, 105)
    elif mutation == "past_page":
        struct.pack_into("<I", page, 0, 4096)
    elif mutation == "odd_name":
        struct.pack_into("<I", page, 60, 3)
    elif mutation == "past_page_name":
        struct.pack_into("<I", page, 60, len(page))

    with pytest.raises(OSError, match=message):
        _parse_windows_directory_page(bytes(page))


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
        "app.domain.shared_services.tools_workflow_registered._execute_excel_import_records", unexpected
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
        "app.domain.shared_services.tools_workflow_registered._execute_excel_import_records",
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
