"""onboarding 演示种子：购买单位 + 打印话术 + 模板联动。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.onboarding_seed_app_service import (
    PRINT_DEMO_MODEL,
    PRINT_DEMO_UNIT_NAME,
    seed_onboarding_demo_data,
)


def test_seed_onboarding_creates_purchase_unit_and_phrases() -> None:
    customer = MagicMock(id=1, customer_name="XC 演示客户", contact_person="张三", contact_phone="1", contact_address="a")
    product = MagicMock(id=2, name="XC 演示产品", model_number=PRINT_DEMO_MODEL, price=12.5)
    unit = MagicMock(id=3, unit_name="XC 演示客户")
    print_unit = MagicMock(id=4, unit_name=PRINT_DEMO_UNIT_NAME)

    db = MagicMock()
    # Customer query → none; PurchaseUnit x2 → none then none; Product queries → none
    query_chain = MagicMock()
    # We'll drive filter().first() returns via side_effect on a simple list
    first_results = [
        None,  # existing customer
        None,  # purchase unit demo customer
        None,  # print purchase unit
        None,  # product by model
        None,  # product by name
        None,  # extra product by model
        None,  # extra product by name
    ]

    def _first():
        return first_results.pop(0) if first_results else None

    filter_mock = MagicMock()
    filter_mock.first.side_effect = _first
    query_chain.filter.return_value = filter_mock
    db.query.return_value = query_chain

    flush_ids = {"c": 1, "u": 3, "pu": 4, "p": 2, "ep": 5}

    def _flush():
        # assign ids to last added objects loosely
        for obj in db.add.call_args_list:
            target = obj.args[0]
            if getattr(target, "customer_name", None) and not getattr(target, "id", None):
                target.id = flush_ids["c"]
            if getattr(target, "unit_name", None) == "XC 演示客户":
                target.id = flush_ids["u"]
            if getattr(target, "unit_name", None) == PRINT_DEMO_UNIT_NAME:
                target.id = flush_ids["pu"]
            if getattr(target, "model_number", None) == PRINT_DEMO_MODEL:
                target.id = flush_ids["p"]
                target.name = getattr(target, "name", "XC 演示产品")
            if getattr(target, "model_number", None) == "9803":
                target.id = flush_ids["ep"]
                target.name = getattr(target, "name", "演示哑光清面漆")

    db.flush.side_effect = _flush

    cm = MagicMock()
    cm.__enter__.return_value = db
    cm.__exit__.return_value = False

    with (
        patch("app.application.onboarding_seed_app_service.get_db", return_value=cm),
        patch(
            "app.db.seeds.document_templates_seed.ensure_initial_document_templates",
            return_value={"success": True, "inserted": ["SEED_SHIPMENT_DEFAULT"]},
        ) as ensure_tpl,
    ):
        out = seed_onboarding_demo_data(tenant_id=9, industry_id="涂料")

    assert out["customer"]["name"] == "XC 演示客户"
    assert out["purchase_unit"]["name"] == "XC 演示客户"
    assert out["print_purchase_unit"]["name"] == PRINT_DEMO_UNIT_NAME
    assert out["product"]["model_number"] == PRINT_DEMO_MODEL
    assert PRINT_DEMO_UNIT_NAME in out["demo_queries"]["price_list"]
    assert PRINT_DEMO_MODEL in out["demo_queries"]["shipment"]
    assert out["templates"]["success"] is True
    ensure_tpl.assert_called_once()
    db.commit.assert_called()
