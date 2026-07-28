"""The ETL-promoted layout should carry the customer name into chat selection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.application.etl.service_shipment_templates import ShipmentTemplateServiceMixin
from app.db.models.etl import EtlTemplate, EtlTemplateVersion


class _TemplateService(ShipmentTemplateServiceMixin):
    def __init__(self, run, upload):
        self._run = run
        self._upload = upload

    def _owned_run(self, _db, _run_id, _owner_user_id):
        return self._run

    def _owned_upload(self, _db, _upload_id, _owner_user_id):
        return self._upload


def test_save_delivery_layout_defaults_to_selected_customer_name(tmp_path):
    run = SimpleNamespace(
        target_type="shipment_records",
        status="preview_ready",
        summary_json="{}",
        upload_id="upload-1",
        file_sha256="a" * 64,
        source_features_json=(
            '{"regions":[{"id":"侯雪梅!R3C1:9","sheet":"侯雪梅",'
            '"header_row":3,"status":"selected","customer_name":"金汉武家私"}]}'
        ),
    )
    upload = SimpleNamespace(file_name="侯雪梅.xlsx", storage_path=str(tmp_path / "source.xlsx"))
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    service = _TemplateService(run, upload)

    with (
        patch("app.application.etl.service_shipment_templates.tenant_id_for_write", return_value=7),
        patch("app.application.etl.service_shipment_templates.get_app_data_dir", return_value=str(tmp_path)),
        patch(
            "app.application.etl.service_shipment_templates.extract_shipment_template",
            return_value={"source_region_id": "侯雪梅!R3C1:9"},
        ),
    ):
        result = service.save_run_shipment_template(
            db,
            run_id="run-1",
            owner_user_id=9,
        )

    saved = [call.args[0] for call in db.add.call_args_list]
    template = next(item for item in saved if isinstance(item, EtlTemplate))
    version = next(item for item in saved if isinstance(item, EtlTemplateVersion))
    assert template.name == "金汉武家私-发货单版式"
    assert template.tenant_id == 7
    assert template.owner_user_id == 9
    assert template.description == "ETL_SHIPMENT_DOCUMENT_TEMPLATE"
    assert version.tenant_id == 7
    assert version.owner_user_id == 9
    assert '"owner_user_id": 9' in version.source_features_json
    assert result["name"] == "金汉武家私-发货单版式"
    assert result["template_id"].startswith("etl:")
    assert "金汉武家私-发货单版式-aaaaaaaaaaaa.xlsx" in result["file_path"]
    assert db.commit.called
