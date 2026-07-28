"""Safety regressions for one-use shipment data from ETL previews."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.etl.shipment_preview_fallback import (
    cleanup_ephemeral_preview_layout,
    find_latest_preview_layout_candidate,
    materialize_preview_layout_candidate,
    resolve_preview_product_candidate,
)
from app.application.shipment_template_resolve import resolve_shipment_template
from app.db.models.etl import EtlRun, EtlRunRow, EtlTemplate, EtlTemplateVersion, EtlUpload
from app.infrastructure.tenant_scope import tenant_scope
from app.services.shipment_number_mode_service import ShipmentNumberModeService


@contextmanager
def _session_context(engine):
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def _add_upload_and_run(
    db: Session,
    *,
    key: str,
    tenant_id: int,
    owner_user_id: int,
    target_type: str,
    source_features_json: str = "{}",
    storage_path: str = "",
) -> EtlRun:
    upload = EtlUpload(
        id=f"upload-{key}",
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        file_name=f"{key}.xlsx",
        suffix=".xlsx",
        size_bytes=128,
        sha256=(key * 64)[:64],
        storage_path=storage_path,
    )
    # There is intentionally no ORM relationship on EtlRun.upload_id.  Flush
    # the FK parent explicitly so SQLite's immediate FK enforcement mirrors a
    # real persisted upload before the preview run is inserted.
    db.add(upload)
    db.flush()
    run = EtlRun(
        id=f"run-{key}",
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        upload_id=upload.id,
        target_type=target_type,
        status="preview_ready",
        stage="preview_ready",
        progress=100,
        file_sha256=(key * 64)[:64],
        source_features_json=source_features_json,
    )
    db.add(run)
    return run


def _preview_engine():
    engine = create_engine("sqlite://")
    EtlUpload.__table__.create(engine)
    EtlTemplate.__table__.create(engine)
    EtlTemplateVersion.__table__.create(engine)
    EtlRun.__table__.create(engine)
    EtlRunRow.__table__.create(engine)
    return engine


def test_product_preview_candidate_is_exact_and_double_scoped():
    engine = _preview_engine()
    with Session(engine) as db:
        own_run = _add_upload_and_run(
            db,
            key="own",
            tenant_id=7,
            owner_user_id=9,
            target_type="customer_products",
        )
        foreign_owner_run = _add_upload_and_run(
            db,
            key="foreign-owner",
            tenant_id=7,
            owner_user_id=10,
            target_type="customer_products",
        )
        foreign_tenant_run = _add_upload_and_run(
            db,
            key="foreign-tenant",
            tenant_id=8,
            owner_user_id=9,
            target_type="customer_products",
        )
        for run, row_id, model, price in (
            (own_run, 1, "方和", "48"),
            (foreign_owner_run, 2, "越权型号", "1"),
            (foreign_tenant_run, 3, "跨租户型号", "2"),
        ):
            db.add(
                EtlRunRow(
                    run_id=run.id,
                    tenant_id=run.tenant_id,
                    owner_user_id=run.owner_user_id,
                    source_sheet="25年出货",
                    source_row=row_id,
                    normalized_json=(
                        '{"customer_name":"金汉武家私","name":"黑棕面用修色精",'
                        f'"model_number":"{model}","price":"{price}"}}'
                    ),
                    validation_json="[]",
                    suggested_action="new",
                    final_action="new",
                )
            )
        db.commit()

    with (
        patch(
            "app.application.etl.shipment_preview_fallback.get_db",
            side_effect=lambda: _session_context(engine),
        ),
        tenant_scope(7),
    ):
        candidate = resolve_preview_product_candidate(
            owner_user_id=9,
            unit_name="金汉武",
            product_name="黑棕面用修色精",
        )

    assert candidate is not None
    assert candidate["model_number"] == "方和"
    assert candidate["price"] == 48.0
    assert candidate["provenance"]["run_id"] == "run-own"
    assert candidate["provenance"]["resolved_product"]["unit_price"] == 48.0


def test_layout_candidate_is_owner_scoped_and_exposes_no_source_path():
    engine = _preview_engine()
    source_features = (
        '{"regions":[{"id":"r-own","sheet":"侯雪梅","header_row":3,'
        '"status":"selected","customer_name":"金汉武家私"}],'
        '"shipment_template_candidate":{"status":"detected","name":"金汉武家私-发货单版式",'
        '"source_region_id":"r-own","customer_name":"金汉武家私"}}'
    )
    with Session(engine) as db:
        _add_upload_and_run(
            db,
            key="own-layout",
            tenant_id=7,
            owner_user_id=9,
            target_type="shipment_records",
            source_features_json=source_features,
        )
        _add_upload_and_run(
            db,
            key="foreign-layout",
            tenant_id=7,
            owner_user_id=10,
            target_type="shipment_records",
            source_features_json=source_features.replace("r-own", "r-foreign"),
        )
        db.commit()

    with (
        patch(
            "app.application.etl.shipment_preview_fallback.get_db",
            side_effect=lambda: _session_context(engine),
        ),
        tenant_scope(7),
    ):
        candidate = find_latest_preview_layout_candidate(
            owner_user_id=9,
            unit_name="金汉武",
        )

    assert candidate is not None
    assert candidate["run_id"] == "run-own-layout"
    assert candidate["template_id"] == "etl-preview:run-own-layout"
    assert "path" not in candidate
    assert candidate["provenance"]["source_sheet"] == "侯雪梅"


def test_preview_layout_is_extracted_to_one_use_temp_file_then_cleaned(tmp_path: Path):
    engine = _preview_engine()
    runtime = tmp_path / "runtime"
    source = runtime / "etl" / "uploads" / "7" / "9" / "upload.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    source_features = (
        '{"regions":[{"id":"r-own","sheet":"侯雪梅","header_row":3,'
        '"status":"selected","customer_name":"金汉武家私"}],'
        '"shipment_template_candidate":{"status":"detected","name":"金汉武家私-发货单版式",'
        '"source_region_id":"r-own","customer_name":"金汉武家私"}}'
    )
    with Session(engine) as db:
        _add_upload_and_run(
            db,
            key="one-use-layout",
            tenant_id=7,
            owner_user_id=9,
            target_type="shipment_records",
            source_features_json=source_features,
            storage_path=str(source),
        )
        db.commit()

    def fake_extract(_source, *, source_features, destination):
        assert source_features["regions"][0]["id"] == "r-own"
        Path(destination).write_bytes(b"one-use-layout")
        return {"source_region_id": "r-own"}

    with (
        patch(
            "app.application.etl.shipment_preview_fallback.get_db",
            side_effect=lambda: _session_context(engine),
        ),
        patch(
            "app.application.etl.shipment_preview_fallback.get_app_data_dir",
            return_value=str(runtime),
        ),
        patch(
            "app.application.etl.shipment_preview_fallback.extract_shipment_template",
            side_effect=fake_extract,
        ),
        tenant_scope(7),
    ):
        candidate = materialize_preview_layout_candidate(
            owner_user_id=9,
            unit_name="金汉武",
        )

    assert candidate is not None
    temporary = Path(candidate["path"])
    assert temporary.is_file()
    assert candidate["source"] == "etl_preview_candidate"
    cleanup_ephemeral_preview_layout(candidate["cleanup_path"])
    assert not temporary.exists()


def test_preview_layout_beats_generic_template_but_not_saved_private_customer_layout(
    tmp_path: Path,
):
    generic = tmp_path / "通用发货单.xlsx"
    private = tmp_path / "金汉武家私-发货单版式.xlsx"
    preview = tmp_path / "preview.xlsx"
    for path in (generic, private, preview):
        path.write_bytes(b"xlsx")
    store = MagicMock()
    store.list_templates.return_value = [
        {
            "id": "db:1",
            "name": "通用发货单",
            "path": str(generic),
            "template_type": "发货单",
            "is_active": 1,
        }
    ]
    store.get_default_for_type.return_value = None
    preview_row = {
        "path": str(preview),
        "cleanup_path": str(preview),
        "template_id": "etl-preview:run-own-layout",
        "name": "金汉武家私-发货单版式",
        "warning": "only once",
        "provenance": {"run_id": "run-own-layout"},
    }
    with (
        patch("app.application.shipment_template_resolve._get_template_store", return_value=store),
        patch("app.application.shipment_template_resolve._private_layout_rows", return_value=[]),
        patch(
            "app.application.shipment_template_resolve._resolve_preview_layout_candidate",
            return_value={
                "ok": True,
                "path": str(preview),
                "template_id": "etl-preview:run-own-layout",
                "template_name": "金汉武家私-发货单版式",
                "template_type": "发货单",
                "source": "etl_preview_candidate",
                "reason": "resolved_etl_preview_layout_candidate",
                "warning": "only once",
                "provenance": {"run_id": "run-own-layout"},
                "_cleanup_path": str(preview),
            },
        ) as preview_resolver,
    ):
        out = resolve_shipment_template(unit_name="金汉武", owner_user_id=9)
    assert out["source"] == "etl_preview_candidate"
    assert out["path"] == str(preview)
    preview_resolver.assert_called_once()

    private_row = {
        "id": "etl:private-own",
        "name": "金汉武家私-发货单版式",
        "path": str(private),
        "template_type": "发货单",
        "source": "etl_private",
        "is_active": 1,
    }
    with (
        patch("app.application.shipment_template_resolve._get_template_store", return_value=store),
        patch(
            "app.application.shipment_template_resolve._private_layout_rows",
            return_value=[private_row],
        ),
        patch(
            "app.application.shipment_template_resolve._resolve_preview_layout_candidate",
            return_value=preview_row,
        ) as preview_resolver,
    ):
        saved = resolve_shipment_template(unit_name="金汉武", owner_user_id=9)
    assert saved["source"] == "etl_private"
    assert saved["path"] == str(private)
    preview_resolver.assert_not_called()


def test_number_mode_uses_preview_product_for_one_confirmed_document_only():
    service = ShipmentNumberModeService()
    service._query_active_purchase_unit_names = MagicMock(return_value=["金汉武家私"])
    service._load_active_product_catalog = MagicMock(return_value=[])
    app_service = MagicMock()
    app_service.generate_shipment_document.return_value = {
        "success": True,
        "doc_name": "9803.xlsx",
        "file_path": "/tmp/9803.xlsx",
        "order_number": "9803",
    }
    preview_candidate = {
        "name": "黑棕面用修色精",
        "model_number": "方和",
        "price": 48.0,
        "provenance": {
            "kind": "etl_preview_product_candidate",
            "run_id": "run-own",
            "source_sheet": "25年出货",
            "source_row": 354,
            "resolved_product": {
                "name": "黑棕面用修色精",
                "model_number": "方和",
                "unit_price": 48.0,
            },
        },
    }
    parsed = {
        "success": True,
        "unit_name": "金汉武",
        "order_number": "9803",
        "order_number_provenance": {
            "kind": "explicit_document_number",
            "label": "编号",
            "value": "9803",
        },
        "products": [{"name": "黑棕面用修色精", "quantity_tins": 3, "tin_spec": 28.0}],
    }
    with (
        patch(
            "app.services.shipment_number_mode_service.get_shipment_app_service",
            return_value=app_service,
        ),
        patch(
            "app.application.etl.shipment_preview_fallback.resolve_preview_product_candidate",
            return_value=preview_candidate,
        ) as preview_lookup,
    ):
        payload, status = service.execute(
            order_text="打印金汉武发货单，黑棕面用修色精，编号9803，规格28，3桶",
            custom_order_number="9803",
            direct_unit_name="金汉武",
            direct_products=list(parsed["products"]),
            parse_order_text=MagicMock(return_value=parsed),
            owner_user_id=9,
        )

    assert status == 200
    preview_lookup.assert_called_once_with(
        owner_user_id=9,
        unit_name="金汉武家私",
        product_name="黑棕面用修色精",
    )
    sent = app_service.generate_shipment_document.call_args.kwargs
    assert sent["owner_user_id"] == 9
    assert sent["order_number"] == "9803"
    assert sent["products"] == [
        {
            "name": "黑棕面用修色精",
            "product_name": "黑棕面用修色精",
            "model_number": "方和",
            "quantity_tins": 3,
            "tin_spec": 28.0,
            "unit_price": 48.0,
        }
    ]
    assert payload["order_number_provenance"]["kind"] == "explicit_document_number"
    assert (
        payload["etl_preview_provenance"]["products"][0]["resolved_product"]["unit_price"] == 48.0
    )
    assert payload["warnings"][0]["code"] == "ETL_PREVIEW_PRODUCT_CANDIDATE_USED"
