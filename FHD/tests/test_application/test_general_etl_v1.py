from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.application.etl.adviser import EtlRowAdviser
from app.application.etl.errors import EtlConflict, EtlError, EtlNotFound
from app.application.etl.parsers import parse_file
from app.application.etl.service import EtlService, mark_interrupted_runs_on_startup
from app.application.etl.targets import (
    ExportCsvAdapter,
    KnowledgeAdapter,
    ProductAdapter,
    PurchaseOrderAdapter,
    ShipmentAdapter,
    WebhookAdapter,
    get_adapter,
    target_capabilities,
)
from app.application.etl.transforms import (
    apply_mapping,
    apply_transform,
    neutralize_spreadsheet_formula,
)
from app.application.excel_etl_kb import ExcelEtlKnowledgeBase, TemplateMemory
from app.application.shipment_excel_etl_app_service import write_delivery_note_workbook
from app.db.base import Base
from app.db.models.customer import Customer
from app.db.models.etl import (
    EtlRun,
    EtlRunRow,
    EtlTargetConfig,
    EtlTemplate,
    EtlTemplateVersion,
    EtlUpload,
)
from app.db.models.inventory import Warehouse
from app.db.models.product import Product
from app.db.models.purchase import PurchaseOrder, PurchaseOrderItem, Supplier
from app.db.models.shipment import ShipmentRecord
from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint
from app.infrastructure.tenant_scope import tenant_scope
from app.services.ocr_service import OCRService


@pytest.fixture()
def etl_db(tmp_path, monkeypatch):
    db_path = tmp_path / "etl.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(
        engine,
        tables=[
            EtlUpload.__table__,
            EtlTemplate.__table__,
            EtlTemplateVersion.__table__,
            EtlRun.__table__,
            EtlRunRow.__table__,
            EtlTargetConfig.__table__,
            Customer.__table__,
            Product.__table__,
            Supplier.__table__,
            Warehouse.__table__,
            PurchaseOrder.__table__,
            PurchaseOrderItem.__table__,
            ShipmentRecord.__table__,
            ShipmentEtlImportFingerprint.__table__,
        ],
    )
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setattr("app.application.etl.service.SessionLocal", maker)
    return maker


def test_safe_transform_dsl_rejects_dynamic_execution():
    with pytest.raises(EtlError, match="不允许的转换操作"):
        apply_transform("x", {"op": "python", "code": "__import__('os')"}, {})

    with pytest.raises(EtlError, match="不允许的公式操作符"):
        apply_transform("1", {"op": "formula", "operator": "eval", "operands": ["1"]}, {})

    result = apply_mapping(
        {"单价": "1,200.50", "数量": "2"},
        [
            {"source": "单价", "target": "price", "transforms": [{"op": "number"}]},
            {
                "source": "",
                "target": "amount",
                "transforms": [
                    {
                        "op": "formula",
                        "operator": "mul",
                        "operands": [{"field": "price"}, {"field": "数量"}],
                    }
                ],
            },
        ],
    )
    assert result == {"price": "1200.50", "amount": "2401.00"}
    assert neutralize_spreadsheet_formula("=HYPERLINK('x')").startswith("'")


def test_global_excel_etl_knowledge_base_is_read_only_in_runtime(tmp_path):
    path = tmp_path / "excel_etl_kb.json"
    path.write_text(
        json.dumps(
            {
                "templates": {
                    "existing": TemplateMemory(
                        fingerprint="existing",
                        columns={"product_name": 1},
                    ).to_dict()
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    original = path.read_bytes()
    kb = ExcelEtlKnowledgeBase(path)
    assert kb.touch("existing") is not None
    kb.remember(TemplateMemory(fingerprint="new", columns={"product_name": 2}))
    assert kb.get_template("new") is None
    assert path.read_bytes() == original


def test_csv_parser_preserves_source_row_and_rejects_word_business_target(tmp_path):
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("客户名称,电话\n甲公司,13800000000\n", encoding="utf-8")
    dataset = parse_file(csv_path, target_type="customers")
    assert dataset.headers == ["客户名称", "电话"]
    assert dataset.rows[0].row_number == 2
    assert dataset.rows[0].provenance["original_fragment"]["客户名称"] == "甲公司"

    doc_path = tmp_path / "memo.docx"
    doc_path.write_bytes(b"placeholder")
    with pytest.raises(EtlError, match="仅可导入知识库"):
        parse_file(doc_path, target_type="customers")


def test_delivery_profile_converts_to_general_etl_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("FHD_SHIPMENT_ETL_LLM", "0")
    path = tmp_path / "delivery.xlsx"
    result = write_delivery_note_workbook(
        [
            {
                "unit_name": "兼容客户",
                "order_number": "COMPAT-1",
                "items": [
                    {
                        "model_number": "A1",
                        "product_name": "底漆",
                        "quantity_tins": 1,
                        "tin_spec": 20,
                        "quantity_kg": 20,
                        "unit_price": 10,
                        "amount": 200,
                    },
                    {
                        "model_number": "B2",
                        "product_name": "面漆",
                        "quantity_tins": 2,
                        "tin_spec": 20,
                        "quantity_kg": 40,
                        "unit_price": 12,
                        "amount": 480,
                    },
                ],
            }
        ],
        path,
    )
    assert result["success"] is True

    with tenant_scope(1):
        dataset = parse_file(path, target_type="shipment_records")

    assert dataset.source_features["kind"] == "shipment_profile"
    assert dataset.source_features["compatibility_preset"] is True
    assert len(dataset.rows) == 2
    values = [row.values for row in dataset.rows]
    assert {row["product_name"] for row in values} == {"底漆", "面漆"}
    assert len({row["source_fingerprint"] for row in values}) == 2
    assert len({row["legacy_note_fingerprint"] for row in values}) == 1


def test_macos_vision_fallback_returns_auditable_positioned_blocks(monkeypatch):
    service = OCRService.__new__(OCRService)
    service.macos_vision_available = True
    monkeypatch.setattr(
        "app.services.ocr_service.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "text": "客户名称",
                        "confidence": 0.92,
                        "x": 0.1,
                        "y": 0.7,
                        "width": 0.2,
                        "height": 0.1,
                    }
                ]
            ),
            stderr="",
        ),
    )
    blocks = service._recognize_macos_vision_blocks(np.zeros((100, 200, 3), dtype=np.uint8))
    assert blocks == [
        {
            "text": "客户名称",
            "left": 20.0,
            "top": pytest.approx(20.0),
            "width": 40.0,
            "height": 10.0,
            "confidence": 0.92,
            "center": (40.0, pytest.approx(25.0)),
            "y_center": pytest.approx(25.0),
        }
    ]


def test_llm_adviser_failure_never_changes_deterministic_action(etl_db, monkeypatch):
    def unavailable(_payload):
        raise RuntimeError("model unavailable")

    service = EtlService(adviser=EtlRowAdviser(unavailable))
    monkeypatch.setattr(
        service,
        "_submit_preview",
        lambda run_id, _tenant_id, owner_user_id: service._preview_worker(run_id, owner_user_id),
    )
    with tenant_scope(6):
        db = etl_db()
        upload = service.save_upload(
            db,
            owner_user_id=10,
            file_name="llm-fallback.csv",
            content_type="text/csv",
            stream=BytesIO("客户名称\n确定性客户\n".encode()),
        )
        db.commit()
        run = service.create_preview(
            db,
            owner_user_id=10,
            upload_id=upload["upload_id"],
            target_type="customers",
        )
        rows = service.get_rows(
            db,
            run_id=run["id"],
            owner_user_id=10,
            page=1,
            page_size=10,
        )
        assert rows["items"][0]["suggested_action"] == "new"
        assert rows["items"][0]["final_action"] == "new"
        assert rows["items"][0]["llm_suggestion"]["degradation_code"] == "ETL_LLM_UNAVAILABLE"
        persisted = service.get_run(db, run_id=run["id"], owner_user_id=10)
        assert persisted["details"]["llm_degraded"] is True
        db.close()


def test_preview_blocks_invalid_rows_execute_valid_rows_and_rollback(etl_db, monkeypatch):
    service = EtlService()

    def run_inline(run_id: str, _tenant_id: int, owner_user_id: int) -> None:
        service._preview_worker(run_id, owner_user_id)

    monkeypatch.setattr(service, "_submit_preview", run_inline)
    monkeypatch.setattr(
        service,
        "_submit_execution",
        lambda run_id, _tenant_id, owner_user_id, valid_rows_only: service._execute_worker(
            run_id, owner_user_id, valid_rows_only
        ),
    )
    with tenant_scope(7):
        db = etl_db()
        upload = service.save_upload(
            db,
            owner_user_id=11,
            file_name="customers.csv",
            content_type="text/csv",
            stream=BytesIO("客户名称,联系人,电话\n甲公司,张三,138\n,李四,139\n".encode()),
        )
        db.commit()
        run = service.create_preview(
            db,
            owner_user_id=11,
            upload_id=upload["upload_id"],
            target_type="customers",
        )
        assert run["status"] == "preview_ready"
        assert run["summary"] == {
            "new": 1,
            "update": 0,
            "skip": 0,
            "error": 1,
            "executed": 0,
        }

        with pytest.raises(EtlConflict) as blocked:
            service.execute(
                db,
                run_id=run["id"],
                owner_user_id=11,
                confirmed=True,
                valid_rows_only=False,
            )
        assert blocked.value.code == "ETL_INVALID_ROWS_BLOCKED"

        completed = service.execute(
            db,
            run_id=run["id"],
            owner_user_id=11,
            confirmed=True,
            valid_rows_only=True,
        )
        assert completed["status"] == "completed"
        assert completed["receipt"]["partial"] is True
        assert db.query(Customer).filter(Customer.customer_name == "甲公司").count() == 1

        rolled_back = service.rollback(db, run_id=run["id"], owner_user_id=11)
        assert rolled_back["rollback_status"] == "completed"
        assert db.query(Customer).filter(Customer.customer_name == "甲公司").count() == 0
        db.close()


def test_internal_partial_failure_retries_only_unfinished_rows(etl_db, monkeypatch):
    service = EtlService()

    def run_inline(run_id: str, _tenant_id: int, owner_user_id: int) -> None:
        service._preview_worker(run_id, owner_user_id)

    monkeypatch.setattr(service, "_submit_preview", run_inline)
    monkeypatch.setattr(
        service,
        "_submit_execution",
        lambda run_id, _tenant_id, owner_user_id, valid_rows_only: service._execute_worker(
            run_id, owner_user_id, valid_rows_only
        ),
    )
    monkeypatch.setattr(
        service,
        "_submit_revalidation",
        lambda run_id, _tenant_id, owner_user_id, _overrides=None: (
            service._revalidate_existing_rows(db, run_id, owner_user_id)
        ),
    )
    adapter = get_adapter("customers")
    original_execute = adapter.execute_row
    failed_once = False

    def fail_second_row(db, data, **kwargs):
        nonlocal failed_once
        if data.get("customer_name") == "乙公司" and not failed_once:
            failed_once = True
            raise EtlError("ETL_TEST_TRANSIENT", "模拟第二行瞬时失败")
        return original_execute(db, data, **kwargs)

    monkeypatch.setattr(adapter, "execute_row", fail_second_row)
    with tenant_scope(8):
        db = etl_db()
        upload = service.save_upload(
            db,
            owner_user_id=12,
            file_name="retry.csv",
            content_type="text/csv",
            stream=BytesIO("客户名称\n甲公司\n乙公司\n".encode()),
        )
        db.commit()
        run = service.create_preview(
            db,
            owner_user_id=12,
            upload_id=upload["upload_id"],
            target_type="customers",
        )
        failed = service.execute(
            db,
            run_id=run["id"],
            owner_user_id=12,
            confirmed=True,
            valid_rows_only=False,
        )
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "ETL_TEST_TRANSIENT"
        assert db.query(Customer).filter(Customer.customer_name == "甲公司").count() == 1
        assert db.query(Customer).filter(Customer.customer_name == "乙公司").count() == 0

        retried = service.retry(db, run_id=run["id"], owner_user_id=12)
        assert retried["status"] == "preview_ready"
        completed = service.execute(
            db,
            run_id=run["id"],
            owner_user_id=12,
            confirmed=True,
            valid_rows_only=False,
        )
        assert completed["summary"]["executed"] == 2
        assert db.query(Customer).count() == 2

        service.rollback(db, run_id=run["id"], owner_user_id=12)
        assert db.query(Customer).count() == 0
        db.close()


def test_templates_are_private_and_versions_are_immutable(etl_db):
    service = EtlService()
    draft = {
        "field_mappings": [
            {
                "source": "客户",
                "target": "customer_name",
                "transforms": [{"op": "trim"}],
                "confidence": 1,
                "required": True,
            }
        ],
        "allowed_update_fields": [],
        "match_keys": ["customer_name"],
        "action_rules": {"duplicate": "skip"},
    }
    with tenant_scope(9):
        db = etl_db()
        template = service.create_template(
            db,
            owner_user_id=1,
            name="客户导入",
            target_type="customers",
            draft=draft,
        )
        db.commit()
        service.update_template(
            db,
            template_id=template["id"],
            owner_user_id=1,
            draft={**draft, "allowed_update_fields": ["contact_phone"]},
        )
        db.commit()
        versions = service.template_versions(db, template_id=template["id"], owner_user_id=1)
        assert [item["version"]["number"] for item in versions] == [2, 1]
        assert versions[1]["version"]["allowed_update_fields"] == []
        with pytest.raises(EtlNotFound):
            service.template_versions(db, template_id=template["id"], owner_user_id=2)
        db.close()
    with tenant_scope(10):
        db = etl_db()
        with pytest.raises(EtlNotFound):
            service.get_template(db, template_id=template["id"], owner_user_id=1)
        db.close()


def test_product_adapter_requires_confirmed_update_fields_and_rolls_back(etl_db):
    adapter = ProductAdapter()
    with tenant_scope(12):
        db = etl_db()
        data = {"unit": "甲公司", "model_number": "A1", "name": "底漆", "price": "10"}
        preview = adapter.preview(db, data, allowed_update_fields=set(), context={})
        assert preview.action == "new"
        created = adapter.execute_row(
            db,
            data,
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
        db.commit()

        unchanged = adapter.preview(
            db,
            {**data, "price": "12"},
            allowed_update_fields=set(),
            context={},
        )
        assert unchanged.action == "skip"
        update = adapter.preview(
            db,
            {**data, "price": "12"},
            allowed_update_fields={"price"},
            context={},
        )
        assert update.action == "update"
        adapter.execute_row(
            db,
            {**data, "price": "12"},
            action="update",
            match_ref=update.match_ref,
            allowed_update_fields={"price"},
            context={},
        )
        db.commit()
        assert str(db.get(Product, int(created["match_ref"])).price) == "12.00"
        adapter.rollback_row(
            db,
            match_ref=update.match_ref,
            before=update.before or {},
            after=update.after or {},
            context={},
        )
        db.commit()
        assert str(db.get(Product, int(created["match_ref"])).price) == "10.00"
        db.close()


def test_purchase_order_v1_add_skip_and_rollback(etl_db):
    adapter = PurchaseOrderAdapter()
    with tenant_scope(14):
        db = etl_db()
        supplier = Supplier(tenant_id=14, code="SUP-1", name="甲供应商")
        product = Product(
            tenant_id=14,
            unit="内部采购",
            model_number="M1",
            name="树脂",
        )
        db.add_all([supplier, product])
        db.commit()
        data = {
            "external_order_no": "PO-100",
            "supplier_name": "甲供应商",
            "order_date": "2026-07-26",
            "product_model": "M1",
            "product_name": "树脂",
            "quantity": "2",
            "unit": "桶",
            "unit_price": "88",
        }
        preview = adapter.preview(db, data, allowed_update_fields=set(), context={})
        assert preview.action == "new"
        created = adapter.execute_row(
            db,
            data,
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
        db.commit()
        duplicate = adapter.preview(db, data, allowed_update_fields=set(), context={})
        assert duplicate.action == "skip"
        assert duplicate.reason == "existing_order_v1_no_update"

        adapter.rollback_row(
            db,
            match_ref=created["match_ref"],
            before={},
            after=created["after"],
            context={},
        )
        db.commit()
        assert db.query(PurchaseOrderItem).count() == 0
        assert db.query(PurchaseOrder).count() == 0
        db.close()


def test_shipment_adapter_consults_legacy_and_general_fingerprints(etl_db):
    adapter = ShipmentAdapter()
    with tenant_scope(15):
        db = etl_db()
        legacy = ShipmentRecord(
            tenant_id=15,
            purchase_unit="甲公司",
            product_name="底漆",
            quantity_kg=20,
            quantity_tins=1,
            status="pending",
            raw_text="source=shipment_excel_etl|external_order_number=SO-1",
        )
        db.add(legacy)
        db.flush()
        db.add(
            ShipmentEtlImportFingerprint(
                tenant_key="tenant:15",
                fingerprint="legacy-fingerprint",
                shipment_id=legacy.id,
                unit_name="甲公司",
                order_number="SO-1",
                file_name="legacy.xlsx",
                source_kind="shipment",
            )
        )
        db.commit()
        data = {
            "purchase_unit": "甲公司",
            "external_order_no": "SO-1",
            "product_name": "底漆",
            "quantity_tins": "1",
        }
        legacy_duplicate = adapter.preview(
            db,
            data,
            allowed_update_fields=set(),
            context={
                "file_sha256": "different-hash",
                "file_name": "renamed.xlsx",
                "source_row": 2,
            },
        )
        assert legacy_duplicate.action == "skip"
        assert legacy_duplicate.reason == "legacy_source_duplicate"

        fresh = {**data, "external_order_no": "SO-2"}
        context = {
            "file_sha256": "new-hash",
            "file_name": "new.xlsx",
            "source_row": 2,
            "run_id": "shipment-run",
        }
        preview = adapter.preview(db, fresh, allowed_update_fields=set(), context=context)
        assert preview.action == "new"
        created = adapter.execute_row(
            db,
            fresh,
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context=context,
        )
        db.commit()
        duplicate = adapter.preview(db, fresh, allowed_update_fields=set(), context=context)
        assert duplicate.action == "skip"
        assert duplicate.reason == "legacy_fingerprint_duplicate"

        adapter.rollback_row(
            db,
            match_ref=created["match_ref"],
            before={},
            after=created["after"],
            context=context,
        )
        db.commit()
        assert db.get(ShipmentRecord, int(created["match_ref"])) is None
        assert (
            db.query(ShipmentEtlImportFingerprint)
            .filter(ShipmentEtlImportFingerprint.source_kind == "general_etl")
            .count()
            == 0
        )
        db.close()


def test_export_neutralizes_formulas_and_webhook_chunks_have_idempotency(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "app-data"))
    export = ExportCsvAdapter().execute_batch(
        [{"name": "=HYPERLINK('https://bad')", "value": 1}],
        {"run_id": "export-run"},
    )
    assert export["executed"] == 1
    exported_path = tmp_path / "app-data" / "etl" / "exports" / "etl-export-run.csv"
    assert "'=HYPERLINK" in exported_path.read_text(encoding="utf-8-sig")

    calls: list[dict] = []

    class Response:
        status_code = 200

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, endpoint, *, json, headers):
            calls.append({"endpoint": endpoint, "json": json, "headers": headers})
            return Response()

    monkeypatch.setattr("httpx.Client", Client)
    monkeypatch.setattr("app.application.etl.targets._assert_safe_webhook_url", lambda _url: None)
    result = WebhookAdapter().execute_batch(
        [{"index": index} for index in range(501)],
        {
            "run_id": "webhook-run",
            "target_config": {
                "endpoint_url": "https://example.com/hook",
                "headers": {},
                "secret_ref": None,
            },
        },
    )
    assert result["executed"] == 501
    assert len(calls) == 2
    assert calls[0]["headers"]["Idempotency-Key"] == "webhook-run:0"
    assert calls[1]["headers"]["Idempotency-Key"] == "webhook-run:1"
    assert len(calls[0]["json"]["rows"]) == 500
    assert len(calls[1]["json"]["rows"]) == 1


def test_target_contract_catalog_covers_v1_targets_without_secret_fields():
    capabilities = {item["type"]: item for item in target_capabilities()}
    assert set(capabilities) == {
        "knowledge",
        "customers",
        "products",
        "purchase_orders",
        "shipment_records",
        "attendance",
        "export_xlsx",
        "export_csv",
        "webhook",
    }
    assert capabilities["customers"]["reversible"] is True
    assert capabilities["attendance"]["reversible"] is True
    assert capabilities["webhook"]["reversible"] is False
    assert all("secret" not in field for item in capabilities.values() for field in item["fields"])


def test_knowledge_hash_dedup_source_replacement_and_rollback(tmp_path, monkeypatch):
    rag = DatasetRagApplicationService(
        storage_path=tmp_path / "knowledge.json",
        rebuild_workers_enabled=False,
    )
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        lambda: rag,
    )
    adapter = KnowledgeAdapter()

    def context() -> dict[str, object]:
        return {
            "owner_user_id": 8,
            "file_name": "制度.md",
            "file_sha256": "upload-hash",
            "run_id": "knowledge-run",
            "_preview_cache": {},
        }

    with tenant_scope(22):
        original = {"content": "第一版", "source_key": "员工制度"}
        preview = adapter.preview(None, original, allowed_update_fields=set(), context=context())
        assert preview.action == "new"
        first = adapter.execute_row(
            None,
            original,
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context=context(),
        )

        duplicate = adapter.preview(None, original, allowed_update_fields=set(), context=context())
        assert duplicate.action == "skip"
        assert duplicate.reason == "duplicate_content_hash"

        changed = {"content": "第二版", "source_key": "员工制度"}
        unconfirmed = adapter.preview(None, changed, allowed_update_fields=set(), context=context())
        assert unconfirmed.action == "skip"
        confirmed = adapter.preview(
            None,
            changed,
            allowed_update_fields={"content"},
            context=context(),
        )
        assert confirmed.action == "update"
        second = adapter.execute_row(
            None,
            changed,
            action="update",
            match_ref=confirmed.match_ref,
            allowed_update_fields={"content"},
            context=context(),
        )
        assert second["match_ref"] != first["match_ref"]

        adapter.rollback_row(
            None,
            match_ref=second["match_ref"],
            before=confirmed.before or {},
            after=second["after"],
            context=context(),
        )
        status = rag.status(
            "office-docking",
            tenant_id="22",
            access_context={
                "actor_id": "8",
                "tenant_id": "22",
                "permissions": ["dataset.read"],
            },
        )
        assert status["document_count"] == 1
        assert status["documents"][0]["document_id"] == first["match_ref"]


def test_webhook_headers_cannot_bypass_credential_store(etl_db):
    service = EtlService()
    with tenant_scope(30):
        db = etl_db()
        with pytest.raises(EtlError) as forbidden:
            service.create_target_config(
                db,
                owner_user_id=3,
                name="危险配置",
                endpoint_url="https://example.com/hook",
                headers={"Authorization": "Bearer plaintext"},
                secret=None,
            )
        assert forbidden.value.code == "ETL_WEBHOOK_SECRET_HEADER_FORBIDDEN"
        db.close()


def test_retention_removes_payloads_but_keeps_run_summary(etl_db):
    service = EtlService()
    with tenant_scope(31):
        db = etl_db()
        upload_data = service.save_upload(
            db,
            owner_user_id=4,
            file_name="old.csv",
            content_type="text/csv",
            stream=BytesIO(b"name\nold\n"),
        )
        upload = db.get(EtlUpload, upload_data["upload_id"])
        assert upload is not None
        upload.expires_at = datetime.now(UTC) - timedelta(days=1)
        run = EtlRun(
            id="old-run",
            tenant_id=31,
            owner_user_id=4,
            upload_id=upload.id,
            target_type="customers",
            status="completed",
            stage="completed",
            file_sha256=upload.sha256,
            reversible=True,
            created_at=datetime.now(UTC) - timedelta(days=91),
        )
        db.add(run)
        db.add(
            EtlRunRow(
                tenant_id=31,
                owner_user_id=4,
                run_id=run.id,
                source_sheet="Sheet1",
                source_row=2,
            )
        )
        db.commit()
        stored_path = upload.storage_path

        result = service.cleanup_retention(db, owner_user_id=4)

        assert result == {"removed_upload_files": 1, "removed_run_rows": 1}
        assert not Path(stored_path).exists()
        assert db.get(EtlUpload, upload.id).storage_path == ""
        retained = db.get(EtlRun, run.id)
        assert retained is not None
        assert retained.reversible is False
        assert retained.rollback_status == "expired"
        db.close()


def test_dynamic_export_preserves_source_columns_and_values(etl_db, monkeypatch, tmp_path):
    service = EtlService()
    monkeypatch.setattr(
        service,
        "_submit_preview",
        lambda run_id, _tenant_id, owner_user_id: service._preview_worker(run_id, owner_user_id),
    )
    monkeypatch.setattr(
        service,
        "_submit_execution",
        lambda run_id, _tenant_id, owner_user_id, valid_rows_only: service._execute_worker(
            run_id, owner_user_id, valid_rows_only
        ),
    )
    with tenant_scope(40):
        db = etl_db()
        upload = service.save_upload(
            db,
            owner_user_id=5,
            file_name="export.csv",
            content_type="text/csv",
            stream=BytesIO("姓名,金额\n甲,10\n乙,20\n".encode()),
        )
        db.commit()
        run = service.create_preview(
            db,
            owner_user_id=5,
            upload_id=upload["upload_id"],
            target_type="export_csv",
        )
        assert [item["target"] for item in run["draft"]["field_mappings"]] == ["姓名", "金额"]
        rows = service.get_rows(
            db,
            run_id=run["id"],
            owner_user_id=5,
            page=1,
            page_size=10,
        )
        assert rows["items"][0]["normalized"] == {"姓名": "甲", "金额": "10"}
        completed = service.execute(
            db,
            run_id=run["id"],
            owner_user_id=5,
            confirmed=True,
            valid_rows_only=False,
        )
        assert completed["status"] == "completed"
        exported = service.download_path(db, run_id=run["id"], owner_user_id=5)
        text = exported.read_text(encoding="utf-8-sig")
        assert "姓名,金额" in text
        assert "甲,10" in text
        db.close()


def test_duplicate_customers_inside_one_file_are_skipped(etl_db, monkeypatch):
    service = EtlService()
    monkeypatch.setattr(
        service,
        "_submit_preview",
        lambda run_id, _tenant_id, owner_user_id: service._preview_worker(run_id, owner_user_id),
    )
    monkeypatch.setattr(
        service,
        "_submit_execution",
        lambda run_id, _tenant_id, owner_user_id, valid_rows_only: service._execute_worker(
            run_id, owner_user_id, valid_rows_only
        ),
    )
    with tenant_scope(41):
        db = etl_db()
        upload = service.save_upload(
            db,
            owner_user_id=6,
            file_name="duplicates.csv",
            content_type="text/csv",
            stream=BytesIO("客户名称,电话\n甲公司,138\n甲公司,138\n".encode()),
        )
        db.commit()
        run = service.create_preview(
            db,
            owner_user_id=6,
            upload_id=upload["upload_id"],
            target_type="customers",
        )
        assert run["summary"]["new"] == 1
        assert run["summary"]["skip"] == 1
        completed = service.execute(
            db,
            run_id=run["id"],
            owner_user_id=6,
            confirmed=True,
            valid_rows_only=False,
        )
        assert completed["summary"]["executed"] == 1
        assert db.query(Customer).filter(Customer.customer_name == "甲公司").count() == 1
        db.close()


def test_knowledge_adapter_rejects_arbitrary_local_document_path(tmp_path):
    adapter = KnowledgeAdapter()
    upload = tmp_path / "safe.docx"
    upload.write_bytes(b"safe")
    with tenant_scope(42):
        decision = adapter.preview(
            None,
            {"document_path": "/etc/passwd"},
            allowed_update_fields=set(),
            context={
                "upload_path": str(upload),
                "file_sha256": "hash",
                "file_name": upload.name,
                "_preview_cache": {},
            },
        )
    assert decision.action == "error"
    assert decision.issues[0]["code"] == "ETL_DOCUMENT_PATH_FORBIDDEN"


def test_rollback_refuses_to_overwrite_post_import_changes(etl_db):
    adapter = ProductAdapter()
    with tenant_scope(43):
        db = etl_db()
        created = adapter.execute_row(
            db,
            {"unit": "甲公司", "model_number": "A1", "name": "底漆", "price": "10"},
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
        db.commit()
        product = db.get(Product, int(created["match_ref"]))
        product.description = "导入后人工补充"
        db.commit()
        with pytest.raises(EtlError) as conflict:
            adapter.rollback_row(
                db,
                match_ref=created["match_ref"],
                before={},
                after=created["after"],
                context={},
            )
        assert conflict.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"
        assert db.get(Product, int(created["match_ref"])) is not None
        db.close()


def test_shipment_rollback_refuses_post_import_status_change(etl_db):
    adapter = ShipmentAdapter()
    with tenant_scope(45):
        db = etl_db()
        data = {
            "purchase_unit": "甲公司",
            "external_order_no": "ROLLBACK-SHIPMENT-1",
            "product_name": "底漆",
            "quantity_tins": "1",
        }
        context = {
            "file_sha256": "rollback-shipment",
            "file_name": "shipment.csv",
            "source_row": 2,
            "run_id": "rollback-shipment-run",
        }
        created = adapter.execute_row(
            db,
            data,
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context=context,
        )
        db.commit()
        shipment = db.get(ShipmentRecord, int(created["match_ref"]))
        shipment.status = "shipped"
        db.commit()
        with pytest.raises(EtlError) as conflict:
            adapter.rollback_row(
                db,
                match_ref=created["match_ref"],
                before={},
                after=created["after"],
                context=context,
            )
        assert conflict.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"
        assert db.get(ShipmentRecord, int(created["match_ref"])) is not None
        db.close()


def test_startup_recovery_marks_inflight_runs_interrupted(etl_db):
    with tenant_scope(44):
        db = etl_db()
        upload = EtlUpload(
            id="startup-upload",
            tenant_id=44,
            owner_user_id=7,
            file_name="run.csv",
            suffix=".csv",
            size_bytes=1,
            sha256="a" * 64,
            storage_path="/tmp/missing",
        )
        run = EtlRun(
            id="startup-run",
            tenant_id=44,
            owner_user_id=7,
            upload_id=upload.id,
            target_type="customers",
            status="executing",
            stage="executing",
            file_sha256=upload.sha256,
        )
        db.add(upload)
        db.commit()
        db.add(run)
        db.commit()
        assert mark_interrupted_runs_on_startup(db.get_bind()) == 1
        db.expire_all()
        recovered = db.get(EtlRun, run.id)
        assert recovered.status == "interrupted"
        assert recovered.error_code == "ETL_EXECUTION_INTERRUPTED"
        db.close()
