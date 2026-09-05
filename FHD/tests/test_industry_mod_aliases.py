from __future__ import annotations

from app.mod_sdk.customer_delivery import (
    delivery_for_account,
    delivery_for_account_custom_mod,
    delivery_for_industry_mod,
    delivery_for_runtime_mod,
    industry_id_for_account,
    list_customer_deliveries,
)
from app.mod_sdk.industry_mod_aliases import (
    canonical_mod_id,
    canonical_mod_id_for_industry,
    is_retired_runtime_mod_id,
    legacy_mod_ids_for,
)


def test_canonical_mod_id_from_legacy():
    assert canonical_mod_id("taiyangniao-pro") == "attendance-industry"
    assert canonical_mod_id("sz-qsm-pro") == "coating-industry"
    assert canonical_mod_id("attendance-industry") == "attendance-industry"


def test_legacy_mod_ids_for_canonical():
    assert "taiyangniao-pro" in legacy_mod_ids_for("attendance-industry")
    assert "sz-qsm-pro" in legacy_mod_ids_for("coating-industry")


def test_sunbird_legacy_mod_is_retired_from_runtime():
    assert is_retired_runtime_mod_id("taiyangniao-pro") is True
    assert is_retired_runtime_mod_id("attendance-industry") is False


def test_canonical_mod_id_for_industry():
    assert canonical_mod_id_for_industry("饰品包装") == "accessories-packaging-industry"
    assert canonical_mod_id_for_industry("考勤") == "attendance-industry"
    assert canonical_mod_id_for_industry("涂料") == "coating-industry"


def test_customer_delivery_has_brand_not_in_baseline():
    assert delivery_for_industry_mod("attendance-industry") is None
    row = delivery_for_industry_mod("sunbird-attendance-custom")
    assert row is not None
    assert row.get("customer_brand") == "太阳鸟 PRO"
    assert row.get("industry_id") == "饰品包装"
    assert row.get("industry_mod_id") == "accessories-packaging-industry"
    assert row.get("runtime_mod_id") == "sunbird-attendance-custom"
    assert row.get("delivery_mode") == "private_mod"
    deliveries = list_customer_deliveries()
    assert any(d.get("industry_mod_id") == "coating-industry" for d in deliveries)


def test_customer_delivery_custom_mod_resolves_private_runtime_not_public_attendance():
    assert delivery_for_account_custom_mod("taiyangniao-pro", "attendance-industry") is None
    row = delivery_for_account_custom_mod("taiyangniao-pro", "sunbird-attendance-custom")
    assert row is not None
    assert row.get("delivery_seed_package", {}).get("pkg_id") == "sunbird-delivery-seed"
    assert row == delivery_for_account_custom_mod("taiyangniao-pro", "饰品包装")
    assert row == delivery_for_runtime_mod("sunbird-attendance-custom", account_username="sunbird")
    assert delivery_for_runtime_mod("sunbird-attendance-custom", account_username="OTHER") is None
    assert delivery_for_runtime_mod("sunbird-attendance-custom") is None


def test_sunbird_account_industry_comes_from_delivery_ssot():
    row = delivery_for_account("sunbird")
    assert row is not None
    assert industry_id_for_account("SUNBIRD") == "饰品包装"
    assert industry_id_for_account("unknown") == ""
