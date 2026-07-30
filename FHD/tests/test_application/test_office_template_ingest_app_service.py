"""办公文件 → 模版库一键入库桥接单测。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.application.office_template_ingest_app_service import (
    attach_template_ingest_to_etl_result,
    ingest_office_bytes_to_template_library,
    ingest_office_path_to_template_library,
)


def test_ingest_bytes_analyze_then_create_success() -> None:
    analyzed = {
        "success": True,
        "task_id": "t1",
        "template_name": "报价单",
        "template_type": "excel",
        "fields": [{"label": "型号", "value": "", "type": "dynamic"}],
        "preview_data": {"file_path": "/tmp/a.xlsx", "sheet_name": "出货"},
    }
    created = {
        "success": True,
        "message": "模板创建成功",
        "template": {"id": "db:1", "db_id": 1, "name": "报价单"},
    }
    with (
        patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_analyze",
            return_value=(analyzed, 200),
        ),
        patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_create",
            return_value=(created, 200),
        ) as create_mock,
    ):
        data, code = ingest_office_bytes_to_template_library(
            file_body=b"fake",
            filename="quote.xlsx",
            template_name="报价单",
            source="unit_test",
        )
    assert code == 200
    assert data["success"] is True
    assert data["ingested"] is True
    assert data["template"]["id"] == "db:1"
    payload = create_mock.call_args.args[0]
    assert payload["name"] == "报价单"
    assert payload["category"] == "excel"
    assert payload["source"] == "unit_test"
    assert payload["file_path"] == "/tmp/a.xlsx"


def test_ingest_bytes_analyze_failure_short_circuits() -> None:
    with (
        patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_analyze",
            return_value=({"success": False, "message": "坏文件"}, 400),
        ),
        patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_create"
        ) as create_mock,
    ):
        data, code = ingest_office_bytes_to_template_library(
            file_body=b"x",
            filename="bad.xlsx",
        )
    assert code == 400
    assert data["ingested"] is False
    create_mock.assert_not_called()


def test_ingest_path_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.xlsx"
    data, code = ingest_office_path_to_template_library(missing)
    assert code == 400
    assert data["error_code"] == "missing_file"
    assert data["ingested"] is False


def test_attach_template_ingest_skipped_when_flag_off() -> None:
    result = attach_template_ingest_to_etl_result(
        {"success": True},
        file_path="/tmp/a.xlsx",
        save_as_template=False,
    )
    assert "template_ingest" not in result


def test_attach_template_ingest_on_etl_success(tmp_path: Path) -> None:
    src = tmp_path / "ship.xlsx"
    src.write_bytes(b"xlsx")
    with patch(
        "app.application.office_template_ingest_app_service.ingest_office_path_to_template_library",
        return_value=({"success": True, "ingested": True, "template": {"id": "db:9"}}, 200),
    ):
        out = attach_template_ingest_to_etl_result(
            {"success": True, "notes": []},
            file_path=src,
            save_as_template=True,
            template_name="送货单版式",
            source="shipment_excel_etl_preview",
        )
    assert out["success"] is True
    assert out["template_ingest"]["ingested"] is True
    assert out["template_ingest"]["template"]["id"] == "db:9"


def test_attach_template_ingest_skips_when_etl_failed() -> None:
    out = attach_template_ingest_to_etl_result(
        {"success": False, "message": "parse fail"},
        file_path="/tmp/a.xlsx",
        save_as_template=True,
    )
    assert out["template_ingest"]["skipped"] is True
    assert out["template_ingest"]["ingested"] is False


def test_shipment_etl_source_tags_template_type_as_shipment() -> None:
    analyzed = {
        "success": True,
        "template_name": "送货单",
        "template_type": "excel",
        "fields": [],
        "preview_data": {"file_path": "/tmp/ship.xlsx"},
    }
    created = {"success": True, "template": {"id": "db:3"}}
    with (
        patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_analyze",
            return_value=(analyzed, 200),
        ),
        patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_create",
            return_value=(created, 200),
        ) as create_mock,
    ):
        data, code = ingest_office_bytes_to_template_library(
            file_body=b"fake",
            filename="ship.xlsx",
            source="shipment_excel_etl",
        )
    assert code == 200
    assert data["ingested"] is True
    assert create_mock.call_args.args[0]["template_type"] == "发货单"
