"""Real workbook/SQL conservation with a fixed advisory model response, not model qualification."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.application.elt import mapping_assist
from app.application.elt.llm_assist_runtime import LlmAssistResult
from app.application.elt.row_verification import verify_row_effects
from app.application.elt.service_support import load_json
from app.db.models import Product, PurchaseUnit
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from tests.test_application.test_etl_preview_task_boundaries import (
    preview_store as preview_store,
)


@pytest.mark.parametrize("header_depth", [1, 2])
def test_multisheet_entity_mapping_keeps_source_cells_and_rollback(
    preview_store, monkeypatch, header_depth
):
    store = preview_store
    monkeypatch.setenv("FHD_ELT_LLM", "off")
    book = Workbook()
    headers = ["客户名称", "电话", "型号", "产品名称", "规格", "价格", "审计零", "审计假"]
    aliases = ["购买单位", "联系电话", "产品型号", "品名", "规格型号", "单价", "审计零", "审计假"]
    source_rows = {
        "清单甲": [
            ["买方甲", "100", "shared", "螺栓", "M1", 10.25, 0, False],
            ["买方甲", "100", "sku-2", "垫片", "M2", 2.5, 0, False],
        ],
        "清单乙": [["买方乙", "200", "shared", "螺栓", "M1", 20.5, 0, False]],
    }
    for index, (name, values) in enumerate(source_rows.items()):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = name
        if header_depth == 2:
            sheet.append(
                ["客户信息", "客户信息", "产品信息", "产品信息", "产品信息", "计价", "审计", "审计"]
            )
        sheet.append(headers if index == 0 else aliases)
        for values_row in values:
            sheet.append(values_row)
    stream = BytesIO()
    book.save(stream)
    book.close()
    original_bytes = stream.getvalue()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    original = load_workbook(BytesIO(original_bytes), data_only=False)
    observed = []

    def advise(*, headers, **_kwargs):
        # The fixed answer models a proposal only. Source persistence and both
        # entity writes below use the actual parser, database and approval path.
        assert len(headers) == 8
        with store.factory() as db:
            run = db.query(EltRun).one()
            rows = db.query(EltRunRow).filter_by(run_id=run.id).order_by(EltRunRow.id).all()
            manifest = load_json(run.summary_json, {})["source_snapshot"]
            assert manifest["rows"] == len(rows) == 3
            assert db.query(PurchaseUnit).count() == db.query(Product).count() == 0
            assert all(load_json(row.normalized_json, {}) == {} for row in rows)
            observed.append((manifest, [(row.source_json, row.provenance_json) for row in rows]))
        targets = [
            "customer_name",
            "contact_phone",
            "model_number",
            "name",
            "specification",
            "price",
        ]
        return LlmAssistResult(
            used_llm=True,
            data={
                "mappings": [
                    {
                        "source": source,
                        "target": target,
                        "confidence": 0.99,
                        "transform": "number" if target == "price" else "trim",
                        "reason": "fixed regression proposal",
                    }
                    for source, target in zip(headers[:6], targets, strict=True)
                ]
            },
        )

    monkeypatch.setattr(mapping_assist, "advise_field_mappings", advise)
    with store.factory() as db:
        upload = store.service.save_upload(
            db,
            owner_user_id=7,
            file_name="multisheet-entities.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            stream=BytesIO(original_bytes),
        )
        db.commit()
        result = store.service.create_preview(
            db, owner_user_id=7, upload_id=upload["upload_id"], target_type="customer_products"
        )
        run_id = result["id"]
    store.executor.futures[-1].result(timeout=20)
    assert len(observed) == 1
    manifest, source_before = observed[0]
    with store.factory() as db:
        run = db.get(EltRun, run_id)
        assert run.status == "preview_ready", (run.error_code, run.error_message)
        rows = db.query(EltRunRow).filter_by(run_id=run.id).order_by(EltRunRow.id).all()
        assert (run.total_rows, run.new_rows, run.error_rows) == (3, 3, 0), [
            (row.source_sheet, row.source_json, row.normalized_json, row.validation_json)
            for row in rows
        ]
        assert [(row.source_sheet, row.source_row) for row in rows] == [
            ("清单甲", header_depth + 1),
            ("清单甲", header_depth + 2),
            ("清单乙", header_depth + 1),
        ]
        for row in rows:
            raw = load_json(row.source_json, {})
            provenance = load_json(row.provenance_json, {})
            assert len(raw) == 8
            for field, value in raw.items():
                native = original[row.source_sheet].cell(
                    row.source_row, provenance["columns"][field]
                )
                assert type(value) is type(native.value) and value == native.value
        features = load_json(run.source_features_json, {})
        assert features["llm_mapping"]["decision_source"] == "model"
        assert len(features["llm_mapping"]["unmapped_sources"]) == 2
        assert [(row.source_json, row.provenance_json) for row in rows] == source_before
        assert load_json(run.summary_json, {})["source_snapshot"] == manifest
        revision = store.service.get_run(db, run_id=run.id, owner_user_id=7)["preview_revision"]
        store.service.execute(
            db,
            run_id=run.id,
            owner_user_id=7,
            confirmed=True,
            valid_rows_only=False,
            preview_revision=revision,
        )
    store.executor.futures[-1].result(timeout=20)
    with store.factory() as db:
        run = db.get(EltRun, run_id)
        assert (run.status, run.executed_rows) == ("completed", 3), run.error_message
        assert {item.unit_name for item in db.query(PurchaseUnit)} == {"买方甲", "买方乙"}
        assert {(item.unit, item.model_number, item.price) for item in db.query(Product)} == {
            ("买方甲", "shared", Decimal("10.25")),
            ("买方甲", "sku-2", Decimal("2.50")),
            ("买方乙", "shared", Decimal("20.50")),
        }
        rows = db.query(EltRunRow).filter_by(run_id=run.id).order_by(EltRunRow.id).all()
        evidence = verify_row_effects(db, run, rows)
        assert evidence["rows_checked"] == 3
        assert evidence["verified_products_by_unit"] == {"买方甲": 2, "买方乙": 1}
        assert [(row.source_json, row.provenance_json) for row in rows] == source_before
        saved_path = Path(db.get(EltUpload, run.upload_id).storage_path)
        assert hashlib.sha256(saved_path.read_bytes()).hexdigest() == original_sha
        store.service.rollback(db, run_id=run.id, owner_user_id=7)
        assert db.query(Product).count() == db.query(PurchaseUnit).count() == 0
        assert [(row.source_json, row.provenance_json) for row in rows] == source_before
        assert load_json(run.summary_json, {})["source_snapshot"] == manifest
        assert hashlib.sha256(saved_path.read_bytes()).hexdigest() == original_sha
    original.close()


def test_alias_alignment_never_collapses_two_original_columns(tmp_path):
    from app.application.elt.parsers import parse_file

    book = Workbook()
    book.active.title = "canonical"
    book.active.append(["购买单位", "名称", "型号", "价格"])
    book.active.append(["甲", "original", "one", 10])
    second = book.create_sheet("two-names")
    second.append(["购买单位", "名称", "产品名称", "型号", "价格"])
    expected = ["乙", "first-source-value", "second-source-value", "two", 20]
    second.append(expected)
    path = tmp_path / "alias-collision.xlsx"
    book.save(path)
    book.close()
    dataset = parse_file(path, target_type="products")
    try:
        [row] = [item for item in dataset.rows if item.sheet == "two-names"]
        assert len(row.values) == len(expected)
        ordered = sorted(row.provenance["columns"], key=row.provenance["columns"].__getitem__)
        assert [row.values[field] for field in ordered] == expected
    finally:
        dataset.close()


def test_mixed_row_and_external_customer_sources_require_review(tmp_path):
    from app.application.elt.errors import EltError
    from app.application.elt.parsers import parse_file

    book = Workbook()
    book.active.title = "explicit-row-customer"
    book.active.append(["客户名称", "产品名称", "型号", "规格", "价格"])
    book.active.append(["明确客户", "螺栓", "row-1", "M1", 10])
    external = book.create_sheet("external-customer")
    external.append(["购买单位：表外客户"])
    external.append(["产品名称", "型号", "规格", "价格"])
    external.append(["垫片", "region-2", "M2", 20])
    path = tmp_path / "mixed-customer-source.xlsx"
    book.save(path)
    book.close()
    original = path.read_bytes()
    with pytest.raises(EltError) as failure:
        parse_file(path, target_type="customer_products")
    assert failure.value.code == "ELT_MIXED_SOURCE_MAPPING_REQUIRES_REVIEW"
    assert path.read_bytes() == original
