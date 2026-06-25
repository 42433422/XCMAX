
from __future__ import annotations

from app.mod_sdk.customer_delivery import delivery_for_industry_mod, list_customer_deliveries
from app.mod_sdk.industry_mod_aliases import (
    canonical_mod_id,
    canonical_mod_id_for_industry,
    legacy_mod_ids_for,
)


def test_canonical_mod_id_from_legacy():
    assert canonical_mod_id("taiyangniao-pro") == "attendance-industry"
    assert canonical_mod_id("sz-qsm-pro") == "coating-industry"
    assert canonical_mod_id("attendance-industry") == "attendance-industry"


def test_legacy_mod_ids_for_canonical():
    assert "taiyangniao-pro" in legacy_mod_ids_for("attendance-industry")
    assert "sz-qsm-pro" in legacy_mod_ids_for("coating-industry")


def test_canonical_mod_id_for_industry():
    assert canonical_mod_id_for_industry("考勤") == "attendance-industry"
    assert canonical_mod_id_for_industry("涂料") == "coating-industry"


def test_customer_delivery_has_brand_not_in_baseline():
    row = delivery_for_industry_mod("attendance-industry")
    assert row is not None
    assert row.get("customer_brand") == "太阳鸟 PRO"
    deliveries = list_customer_deliveries()
    assert any(d.get("industry_mod_id") == "coating-industry" for d in deliveries)
