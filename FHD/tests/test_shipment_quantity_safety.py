"""#2292: reject ambiguous new quantities before side effects; preserve stored facts."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.domain.shipment.shipment_quantities import (
    ShipmentQuantityValidationError,
    resolve_shipment_quantity,
)


@pytest.mark.parametrize("spec", [0, -1, "bad", float("nan"), float("inf"), True])
@pytest.mark.parametrize("alias", ["tin_spec", "spec", "weight_per_unit", "spec_per_tin"])
def test_invalid_explicit_spec_is_not_masked_by_kg(spec, alias):
    with pytest.raises(ShipmentQuantityValidationError) as error:
        resolve_shipment_quantity({"quantity_kg": 17, alias: spec})
    assert error.value.code == "SHIPMENT_SPEC_INVALID"


@pytest.mark.parametrize("unit", ["", "桶", "件", "个", "箱"])
def test_missing_spec_never_defaults(unit):
    with pytest.raises(ShipmentQuantityValidationError) as error:
        resolve_shipment_quantity({"quantity": 3, "unit": unit})
    assert error.value.code == "SHIPMENT_SPEC_REQUIRED"


@pytest.mark.parametrize(
    "product",
    [
        {"quantity_kg": 17.5},
        {"quantity": 17.5, "unit": "kg"},
        {"quantity": 17.5, "unit": "公斤"},
        {"quantity": 17.5, "unit": "千克"},
    ],
)
def test_real_weight_keeps_weight_without_inventing_package(product):
    assert resolve_shipment_quantity(product) == (0, 17.5, None)


def test_valid_spec_alias_and_explicit_weight_preserved():
    assert resolve_shipment_quantity({"quantity_tins": 2, "weight_per_unit": 12}) == (2, 24, 12)
    assert resolve_shipment_quantity({"quantity_tins": 2, "tin_spec": 12, "quantity_kg": 17}) == (
        2,
        17,
        12,
    )
    for product in (
        {"quantity": 2, "unit": "升", "tin_spec": 10},
        {"quantity_tins": 2, "tin_spec": 10, "spec": 20},
    ):
        with pytest.raises(ShipmentQuantityValidationError):
            resolve_shipment_quantity(product)


@pytest.mark.parametrize(
    "text",
    [
        "张三 送货单: 白色乳胶漆 数量3个 单价12.50",
        "张三 发货单：白色乳胶漆 数量24 单价3.5",
        "张三3桶ABC",
        "张三3件ABC",
    ],
)
def test_parser_cannot_manufacture_weight(text):
    from app.domain.shipment.shipment_product_parser import prepare_parsed_products
    from app.services.tools_execution.order_parser import _parse_order_text

    result = _parse_order_text(text)
    assert result["success"]
    with pytest.raises(ShipmentQuantityValidationError):
        prepare_parsed_products(input_products=result["products"], db_products=[])


def test_kg_parser_to_product_normalization():
    from app.domain.shipment.shipment_product_parser import prepare_parsed_products
    from app.services.tools_execution.order_parser import _parse_order_text

    parsed = _parse_order_text("张三 发货单：白色乳胶漆 数量3kg 单价12.50")
    product = prepare_parsed_products(input_products=parsed["products"], db_products=[])[0]
    assert (product["quantity_tins"], product["quantity_kg"], product["tin_spec"]) == (0, 3, None)
    assert product["amount"] == 37.5


def test_second_invalid_line_blocks_generator_store_repository_and_hooks():
    from app.application.shipment_app_service import ShipmentApplicationService

    repo, generator, store = MagicMock(), MagicMock(), MagicMock()
    service = ShipmentApplicationService(repo, generator, store)
    products = [
        {"name": "valid", "quantity_tins": 1, "tin_spec": 2},
        {"name": "missing", "quantity_tins": 3},
    ]
    with patch("app.infrastructure.mods.hooks.trigger") as hook:
        created = service.create_shipment("customer", products)
        generated = service.generate_shipment_document(unit_name="customer", products=products)
    for result in [created, generated]:
        assert not result["success"]
        assert result["error_code"] == "SHIPMENT_SPEC_REQUIRED"
        assert result["row_index"] == 2
        assert result["file_path"] is None
    repo.save.assert_not_called()
    generator.generate.assert_not_called()
    store.record_document_generation.assert_not_called()
    hook.assert_not_called()


def test_direct_store_and_legacy_generator_reject_before_write_or_number():
    from app.infrastructure.persistence.shipment_record_store_impl import (
        SQLAlchemyShipmentRecordStore,
    )
    from app.legacy.documents.legacy_shipment_document import (
        load_legacy_shipment_document_generator,
    )

    products = [{"name": "first", "quantity_kg": 2}, {"name": "bad", "quantity_tins": 3}]
    with patch("app.infrastructure.persistence.shipment_record_store_impl.get_db") as db:
        with pytest.raises(ShipmentQuantityValidationError):
            SQLAlchemyShipmentRecordStore().record_document_generation(
                unit_name="customer", unit_id=None, products=products, document_result={}
            )
    db.assert_not_called()
    cls = load_legacy_shipment_document_generator(caller_file=__file__).ShipmentDocumentGenerator
    generator = cls.__new__(cls)
    generator._generate_order_number = MagicMock()
    generator._find_template = MagicMock()
    with pytest.raises(ShipmentQuantityValidationError):
        generator.generate_document("", {"products": products}, purchase_unit=MagicMock())
    generator._generate_order_number.assert_not_called()
    generator._find_template.assert_not_called()


def test_direct_adapter_rejects_before_loading_generator_or_labels():
    from app.infrastructure.documents.shipment_document_generator_impl import (
        LegacyShipmentDocumentGenerator,
    )

    generator = LegacyShipmentDocumentGenerator.__new__(LegacyShipmentDocumentGenerator)
    with patch(
        "app.infrastructure.documents.shipment_document_generator_impl.load_legacy_shipment_document_generator"
    ) as loader:
        result = generator.generate(
            unit_name="customer", products=[{"name": "p", "quantity_tins": 2}]
        )
    assert result["error_code"] == "SHIPMENT_SPEC_REQUIRED"
    loader.assert_not_called()


@pytest.mark.parametrize("weight", [{"quantity_kg": 3}, {"quantity": 3, "unit": "kg"}])
def test_agent_clarification_and_schema_accept_actual_kg(weight):
    from jsonschema import validate

    from app.application.agent_orchestrator.tool_spec_data.input_schemas import (
        _SHIPMENT_PRODUCTS_SCHEMA,
    )
    from app.application.shipment_inputs import missing_shipment_fields

    product = {"name": "p", "unit_price": 2, **weight}
    assert missing_shipment_fields({"unit_name": "customer", "products": [product]}) == []
    validate([product], _SHIPMENT_PRODUCTS_SCHEMA)
    assert missing_shipment_fields(
        {"unit_name": "customer", "products": [{**product, "tin_spec": 0}]}
    )


def test_sqlite_old_fact_read_and_status_write_never_recalculate(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.shipment_app_service import ShipmentApplicationService
    from app.db.base import Base
    from app.db.models import ShipmentRecord
    from app.infrastructure.repositories import shipment_repository_impl as module

    engine = create_engine(f"sqlite:///{tmp_path / 'history.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with factory() as session:
            yield session

    monkeypatch.setattr(module, "get_db", get_db)
    try:
        with factory() as session:
            row = ShipmentRecord(
                purchase_unit="customer",
                product_name="p",
                model_number="P",
                quantity_tins=2,
                quantity_kg=17,
                tin_spec=None,
                unit_price=99,
                amount=123.45,
                status="pending",
                parsed_data="{}",
            )
            session.add(row)
            session.commit()
            record_id = row.id
        repo = module.SQLAlchemyShipmentRepository()
        shipment = repo.find_by_id(record_id)
        assert shipment.items[0].quantity.kg == 17
        assert shipment.items[0].quantity.spec is None
        assert shipment.items[0].amount.amount == 123.45
        service = ShipmentApplicationService(repo)
        assert service.mark_as_printed(record_id)["success"]
        assert service.cancel_shipment(record_id)["success"]
        with factory() as session:
            row = session.get(ShipmentRecord, record_id)
            assert (row.quantity_tins, row.quantity_kg, row.tin_spec, float(row.amount)) == (
                2,
                17,
                None,
                123.45,
            )
            assert row.status == "cancelled"
    finally:
        engine.dispose()


def test_event_and_customer_write_are_not_emitted_for_invalid_second_line():
    from app.application.shipment_business_record import remember_business_shipment
    from app.services.tools_workflow_shipments_docs import _registered_router_business_event

    payload = {
        "unit_name": "customer",
        "items": [{"name": "good", "quantity_kg": 2}, {"name": "bad", "quantity_tins": 1}],
    }
    with (
        patch("app.neuro_bus.application_neuro_bridge.publish_neuro_event") as publish,
        patch("app.application.shipment_business_record._customer_pg_insert") as customer,
        patch(
            "app.application.shipment_business_record.get_shipment_application_service_core"
        ) as service,
    ):
        result = _registered_router_business_event("shipment_create", payload, {}, "", "")
        direct = remember_business_shipment(payload)
    assert result["error_code"] == direct["error_code"] == "SHIPMENT_SPEC_REQUIRED"
    publish.assert_not_called()
    customer.assert_not_called()
    service.assert_not_called()


def test_structured_kg_has_no_missing_package_prompt():
    from app.services.tools_execution.order_parser_helpers import structured_order_result

    result = structured_order_result(
        {"unit_name": "张三", "model_number": "ABC", "quantity_kg": "3"}
    )
    assert result["success"]
    assert result["products"][0]["tin_spec"] is None
    assert result["products"][0]["quantity_kg"] == 3
    assert not structured_order_result(
        {"unit_name": "张三", "model_number": "ABC", "quantity_tins": "3"}
    )["success"]


def test_real_kg_document_and_record_keep_null_spec(tmp_path, monkeypatch):
    from openpyxl import load_workbook
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models import ShipmentRecord
    from app.infrastructure.persistence import shipment_record_store_impl as module
    from app.legacy.documents.legacy_shipment_document import (
        load_legacy_shipment_document_generator,
    )
    from tests.test_legacy.test_legacy_shipment_template_merge import (
        _build_merged_customer_template,
    )

    legacy = load_legacy_shipment_document_generator(caller_file=__file__)
    generator = legacy.ShipmentDocumentGenerator(
        db_path=str(tmp_path / "products.sqlite"), output_dir=str(tmp_path / "out")
    )
    product = {"name": "p", "quantity_kg": 17, "unit_price": 3, "amount": 51}
    doc = generator.generate_document(
        "",
        {"products": [product]},
        purchase_unit=legacy.PurchaseUnitInfo(name="测试客户"),
        template_name=str(_build_merged_customer_template(tmp_path / "template.xlsx")),
        custom_order_number="TEST-2292",
    )
    workbook = load_workbook(doc.filepath)
    try:
        assert workbook.active["F4"].value is None
        assert workbook.active["G4"].value == 17
        assert workbook.active["I4"].value == 51
    finally:
        workbook.close()
    engine = create_engine(f"sqlite:///{tmp_path / 'records.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with factory() as session:
            yield session

    monkeypatch.setattr(module, "get_db", get_db)
    try:
        result = module.SQLAlchemyShipmentRecordStore().record_document_generation(
            unit_name="测试客户", unit_id=None, products=[product], document_result={}
        )
        with factory() as session:
            record = session.get(ShipmentRecord, result["record_id"])
            assert (
                record.quantity_tins,
                record.quantity_kg,
                record.tin_spec,
                float(record.amount),
            ) == (0, 17, None, 51)
    finally:
        engine.dispose()


def test_kg_label_never_invents_twenty_kg_package(tmp_path):
    from app.infrastructure.documents import shipment_document_generator_impl as module

    draw = MagicMock()
    draw.textbbox.return_value = (0, 0, 20, 10)
    with (
        patch.object(module, "_PIL_AVAILABLE", True),
        patch.object(module.Image, "new"),
        patch.object(module.ImageDraw, "Draw", return_value=draw),
        patch.object(module.SimpleLabelGenerator, "_get_font", return_value=None),
    ):
        result = module.SimpleLabelGenerator(str(tmp_path)).generate_label(
            {"name": "p", "quantity_kg": 17, "tin_spec": None}, "TEST-2292"
        )
    assert result
    texts = [call.args[1] for call in draw.text.call_args_list]
    assert "按实际公斤数计量" in texts
    assert not any("20±" in value for value in texts)


@pytest.mark.parametrize("kind", ["agent", "workflow"])
def test_chat_uses_fixed_quantity_hint_not_tool_message(kind):
    import json

    from tests.test_application.ai_chat_test_helpers import (
        _make_node_result,
        _make_plan,
        _make_run_result,
        _make_svc,
    )
    from tests.test_application.test_ai_chat_app_service_branch_cov import (
        _make_agent_run,
        _make_step,
    )

    output = {
        "success": False,
        "error_code": "SHIPMENT_SPEC_REQUIRED",
        "message": "secret SQL /private/path",
    }
    service = _make_svc()
    if kind == "agent":
        step = _make_step(
            status="failed", tool_id="shipment_orders", action="generate", output=output
        )
        result = service._format_agent_run_response(
            _make_plan(), _make_agent_run(status="failed", steps=[step])
        )
    else:
        step = _make_node_result(
            success=False, tool_id="shipment_orders", action="generate", output=output
        )
        result = service._format_workflow_run_response(
            _make_plan(), _make_run_result(success=False, node_results=[step])
        )
    assert "计量单位" in result["response"]
    assert "secret" not in json.dumps(result)


def test_compat_http_quantity_error_is_400_and_sanitized():
    import json

    from app.fastapi_routes import ai_assistant

    with (
        patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": True, "unit_name": "客户", "products": [{"name": "p"}]},
        ),
        patch.object(ai_assistant, "_shipment_svc") as get_service,
        patch.object(
            ai_assistant, "_trace_ai_assistant_route", side_effect=lambda result, **kwargs: result
        ),
    ):
        get_service.return_value.generate_shipment_document.return_value = {
            "success": False,
            "error_code": "SHIPMENT_SPEC_REQUIRED",
            "message": "secret SQL",
        }
        response = ai_assistant.compat_ai_generate({"order_text": "客户 发货单"})
    body = json.loads(response.body)
    assert response.status_code == 400
    assert body["error_code"] == "SHIPMENT_SPEC_REQUIRED"
    assert "计量单位" in body["message"] and "secret" not in body["message"]


@pytest.mark.parametrize("key", ["tin_spec", "quantity_tins"])
@pytest.mark.parametrize("bad", ["-1", "abc", "NaN", "inf", True])
def test_structured_invalid_explicit_value_is_not_erased_by_kg(key, bad):
    from app.services.tools_execution.order_parser_helpers import structured_order_result

    result = structured_order_result(
        {"unit_name": "张三", "model_number": "M1", "quantity_kg": "5", key: bad}
    )
    assert result["error_code"] == "SHIPMENT_SPEC_INVALID"


@pytest.mark.parametrize(
    "fields",
    [
        {"quantity": 5, "unit": "KG"},
        {"quantity": 5, "quantity_unit": "公斤"},
        {"quantity": 5, "unit": "件", "weight_per_unit": 2},
        {"quantity_tins": 5, "spec": 2},
    ],
)
def test_schema_and_shared_validator_support_same_explicit_aliases(fields):
    from jsonschema import validate

    from app.application.agent_orchestrator.tool_spec_data.input_schemas import (
        _SHIPMENT_PRODUCTS_SCHEMA,
    )
    from app.application.shipment_inputs import missing_shipment_fields

    product = {"name": "p", "unit_price": 3, **fields}
    validate([product], _SHIPMENT_PRODUCTS_SCHEMA)
    assert missing_shipment_fields({"unit_name": "张三", "products": [product]}) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity_tins", 1.5),
        ("quantity_tins", True),
        ("quantity_tins", "invalid"),
        ("quantity_kg", float("inf")),
        ("quantity_kg", True),
    ],
)
def test_product_source_does_not_hide_invalid_quantity_fields(field, value):
    from app.application.shipment_inputs import missing_shipment_call_fields

    product = {
        "product_name": "Paint",
        "quantity_tins": 1,
        "tin_spec": 10,
        "unit_price": 1,
        field: value,
    }
    payload = {"unit_name": "Co", "products": [product], "product_source_node": "lookup"}
    assert missing_shipment_call_fields("shipment_records", "create", payload) == [
        f"products.0.{field}"
    ]


@pytest.mark.parametrize(
    "item",
    [
        {"quantity_tins": None, "quantity": 1.5, "unit": "桶", "tin_spec": 10},
        {"quantity_kg": None, "quantity": float("inf"), "unit": "kg"},
    ],
)
def test_quantity_error_uses_actual_non_null_source(item):
    from app.application.shipment_inputs import missing_shipment_call_fields

    payload = {
        "unit_name": "Co",
        "product_source_node": "lookup",
        "products": [{"product_name": "Paint", "unit_price": 1, **item}],
    }
    for tool, action, params in [
        ("shipment_records", "create", payload),
        ("business_db", "write", {"entity": "shipment_records", "payload": payload}),
    ]:
        assert missing_shipment_call_fields(tool, action, params) == ["products.0.quantity"]
