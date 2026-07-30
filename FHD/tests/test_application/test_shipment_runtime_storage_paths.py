"""Regression coverage for packaged-desktop shipment runtime paths."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_label_output_dir_is_userdata_tenant_owner_and_run_scoped(tmp_path, monkeypatch) -> None:
    from app.infrastructure.documents import shipment_document_generator_impl as documents

    user_data = tmp_path / "XCAGI-user-data"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(user_data))
    # A label generator must not even consult the packaged resource resolver.
    monkeypatch.setattr(
        "app.utils.path_utils.get_resource_path",
        lambda *_parts: (_ for _ in ()).throw(AssertionError("resources must stay read-only")),
    )

    output_dir, run_id = documents.get_shipment_label_output_dir(
        tenant_id=42,
        owner_user_id=7,
        run_id="preview/42:7",
    )

    assert run_id == "preview_42_7"
    assert Path(output_dir) == (
        user_data
        / "shipment_outputs"
        / "labels"
        / "tenants"
        / "42"
        / "owners"
        / "7"
        / "runs"
        / "preview_42_7"
    )


def test_label_output_rejects_relative_user_data_before_touching_bundle(monkeypatch) -> None:
    from app.infrastructure.documents import shipment_document_generator_impl as documents

    monkeypatch.setenv("XCAGI_DATA_DIR", "relative-user-data")
    monkeypatch.setattr(
        documents,
        "get_app_data_dir",
        lambda: (_ for _ in ()).throw(AssertionError("must reject before resolver mkdirs")),
    )

    with pytest.raises(OSError):
        documents.get_shipment_label_output_dir(tenant_id=42, owner_user_id=7, run_id="run-1")


def test_label_output_rejects_a_user_data_override_inside_frozen_resources(tmp_path, monkeypatch) -> None:
    from app.infrastructure.documents import shipment_document_generator_impl as documents

    resource_root = tmp_path / "XCAGI.app" / "Contents" / "Resources" / "backend"
    resource_root.mkdir(parents=True)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(resource_root / "resources" / "labels"))
    monkeypatch.setattr(sys, "_MEIPASS", str(resource_root), raising=False)
    monkeypatch.setattr(
        documents,
        "get_app_data_dir",
        lambda: (_ for _ in ()).throw(AssertionError("must reject before resolver mkdirs")),
    )

    with pytest.raises(OSError):
        documents.get_shipment_label_output_dir(tenant_id=42, owner_user_id=7, run_id="run-1")


def test_print_label_tool_uses_scoped_runtime_dir_and_returns_run_id() -> None:
    from app.application.workflow.planner import _execute_print_label_tool

    scoped_dir = "/tmp/XCAGI/labels/tenants/42/owners/7/runs/run-1"
    generator = MagicMock()
    generator.generate_labels_for_order.return_value = [{"filename": "label.png"}]
    with patch(
        "app.infrastructure.documents.shipment_document_generator_impl.get_shipment_label_output_dir",
        return_value=(scoped_dir, "run-1"),
    ), patch(
        "app.infrastructure.documents.shipment_document_generator_impl.SimpleLabelGenerator",
        return_value=generator,
    ) as generator_cls:
        result = _execute_print_label_tool(
            {"products": [{"name": "A"}], "order_number": "DO-9803"}
        )

    assert result["success"] is True
    assert result["label_run_id"] == "run-1"
    generator_cls.assert_called_once_with(scoped_dir)
    generator.generate_labels_for_order.assert_called_once_with(
        order_number="DO-9803", products=[{"name": "A"}]
    )


def test_legacy_etl_runtime_state_and_bare_outputs_never_use_cwd(tmp_path, monkeypatch) -> None:
    from app.application import excel_etl_kb
    from app.application import shipment_excel_etl_app_service as app_service
    from app.application import shipment_excel_etl_fingerprint_store as fingerprint_store
    from app.application import shipment_excel_etl_security as security

    bundled_cwd = tmp_path / "XCAGI.app" / "Contents" / "Resources" / "backend"
    bundled_cwd.mkdir(parents=True)
    monkeypatch.chdir(bundled_cwd)
    user_data = tmp_path / "Library" / "Application Support" / "XCAGI"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(user_data))
    monkeypatch.setattr(__import__("sys"), "frozen", True, raising=False)

    expected_data = user_data / "data"
    assert security.etl_runtime_data_dir() == expected_data
    assert app_service._fingerprint_store_path() == expected_data / "shipment_etl_fingerprints.json"
    assert fingerprint_store._legacy_db_path() == expected_data / "shipment_etl_fingerprints.sqlite3"
    assert excel_etl_kb._kb_path() == expected_data / "excel_etl_kb.json"
    assert security.resolve_etl_output_path("repaired.xlsx") == (
        expected_data / "etl" / "outputs" / "repaired.xlsx"
    )
    assert bundled_cwd.resolve() not in security.etl_allowed_roots()


def test_legacy_etl_data_root_failure_has_stable_code_and_never_falls_back_to_cwd(
    tmp_path, monkeypatch
) -> None:
    from app.application.shipment_excel_etl_security import (
        ShipmentEtlRuntimeDataDirError,
        etl_runtime_data_dir,
    )
    from app.utils import path_utils

    bundled_cwd = tmp_path / "XCAGI.app" / "Contents" / "Resources" / "backend"
    bundled_cwd.mkdir(parents=True)
    monkeypatch.chdir(bundled_cwd)
    monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)

    def unavailable() -> str:
        raise OSError("user data unavailable")

    monkeypatch.setattr(path_utils, "get_app_data_dir", unavailable)
    with pytest.raises(ShipmentEtlRuntimeDataDirError) as exc_info:
        etl_runtime_data_dir()

    assert exc_info.value.code == "ETL_RUNTIME_DATA_DIR_UNAVAILABLE"
    assert not (bundled_cwd / "data").exists()


def test_legacy_etl_data_root_failure_remains_a_handled_path_failure(tmp_path, monkeypatch) -> None:
    from app.application import shipment_excel_etl_app_service as app_service
    from app.utils import path_utils

    bundled_cwd = tmp_path / "XCAGI.app" / "Contents" / "Resources" / "backend"
    bundled_cwd.mkdir(parents=True)
    monkeypatch.chdir(bundled_cwd)
    monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
    monkeypatch.setattr(
        path_utils,
        "get_app_data_dir",
        lambda: (_ for _ in ()).throw(OSError("user data unavailable")),
    )

    # Legacy callers already convert ShipmentEtlPathError into a stable,
    # non-writing response.  The runtime-directory subtype must keep that
    # compatibility rather than escaping as a raw 500.
    result = app_service.parse_delivery_notes(str(bundled_cwd / "input.xlsx"))
    assert result["success"] is False
    assert result["error_code"] == "unsafe_path"
    assert not (bundled_cwd / "data").exists()


def test_relative_legacy_kb_override_is_rejected_instead_of_resolving_from_cwd(monkeypatch) -> None:
    from app.application.excel_etl_kb import _kb_path
    from app.application.shipment_excel_etl_security import ShipmentEtlRuntimeDataDirError

    monkeypatch.setenv("FHD_EXCEL_ETL_KB_PATH", "excel_etl_kb.json")
    with pytest.raises(ShipmentEtlRuntimeDataDirError) as exc_info:
        _kb_path()

    assert exc_info.value.code == "ETL_RUNTIME_DATA_DIR_UNAVAILABLE"
