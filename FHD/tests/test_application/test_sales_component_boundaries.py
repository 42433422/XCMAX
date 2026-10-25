"""Closed-loop entity references must not silently select a different numeric ID."""

import pytest

from app.application.normal_chat_dispatch import route_normal_mode_message
from app.domain.sales_app_service import SalesAppService
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_services.test_erp_absorb_e2e import (
    EXACT_SENTENCE,
    _count_business_rows,
    _ledger_available,
    _patch_sessionlocal,
    _seed_tenant,
)
from tests.test_services.test_erp_absorb_e2e import _e2e_db as _e2e_db


@pytest.fixture
def seeded_sales(_e2e_db, monkeypatch):
    _patch_sessionlocal(monkeypatch, _e2e_db)
    return _e2e_db, _seed_tenant(_e2e_db, 1, "SYNTH-BOUNDARY-WH")


@pytest.mark.parametrize("invalid_id", [True, 1.5, float("inf")])
@pytest.mark.parametrize(
    ("entity", "step"),
    [
        ("customer", "resolve_customer"),
        ("product", "resolve_product"),
        ("warehouse", "resolve_warehouse"),
    ],
)
def test_invalid_numeric_entity_id_has_no_business_side_effects(
    seeded_sales, entity, step, invalid_id
):
    factory, seed = seeded_sales
    payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
    section = (
        payload["order"]
        if entity == "customer"
        else payload["order"]["items"][0]
        if entity == "product"
        else payload["fulfillment"]
    )
    section[f"{entity}_id"] = invalid_id
    before = _count_business_rows(factory, 1)
    inventory = _ledger_available(factory, 1, seed["product_id"])
    with tenant_scope(1):
        result = SalesAppService().execute_closed_loop(payload)
    assert result["success"] is False
    assert result["error_code"] == "CLOSED_LOOP_EXECUTION_FAILED"
    assert result["failed_step"] == step
    assert _count_business_rows(factory, 1) == before
    assert _ledger_available(factory, 1, seed["product_id"]) == inventory


@pytest.mark.parametrize("id_kind", ["text", "integral_float"])
def test_exact_numeric_reference_remains_supported(seeded_sales, id_kind):
    factory, seed = seeded_sales
    payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
    for target, name in [
        (payload["order"], "customer"),
        (payload["order"]["items"][0], "product"),
        (payload["fulfillment"], "warehouse"),
    ]:
        value = seed[f"{name}_id"]
        target[f"{name}_id"] = str(value) if id_kind == "text" else float(value)
    with tenant_scope(1):
        result = SalesAppService().execute_closed_loop(payload)
    assert result["success"] is True
    assert result["data"]["postconditions"]["state"] == "confirmed"
    assert result["data"]["postconditions"]["payment_state"] == "paid"
    assert _count_business_rows(factory, 1)["orders"] == 1
    assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
