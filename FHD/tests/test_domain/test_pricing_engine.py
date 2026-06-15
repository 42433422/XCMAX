"""app/domain/services/pricing_engine 单测：定价/折扣/阶梯纯逻辑。

无外部边界（铁律4）；逐档覆盖 VIP/经销商/批发/零售折扣与批量/阶梯分支（铁律3）。
"""

from __future__ import annotations

import pytest

from app.domain.services.pricing_engine import (
    CustomerType,
    PriceBreakdown,
    PricingEngine,
    get_pricing_engine,
)


@pytest.fixture()
def engine() -> PricingEngine:
    return PricingEngine()


class TestCalculatePrice:
    def test_retail_no_discount(self, engine: PricingEngine):
        bd = engine.calculate_price(100.0, 2, CustomerType.RETAIL)
        assert isinstance(bd, PriceBreakdown)
        assert bd.discount == 0.0
        assert bd.tax == pytest.approx(26.0)
        assert bd.total == pytest.approx(226.0)

    def test_vip_high_tier(self, engine: PricingEngine):
        bd = engine.calculate_price(100.0, 100, CustomerType.VIP)  # subtotal 10000
        assert bd.discount == pytest.approx(1500.0)

    def test_vip_mid_tier(self, engine: PricingEngine):
        bd = engine.calculate_price(100.0, 60, CustomerType.VIP)  # subtotal 6000
        assert bd.discount == pytest.approx(600.0)

    def test_vip_low_tier(self, engine: PricingEngine):
        bd = engine.calculate_price(100.0, 10, CustomerType.VIP)  # subtotal 1000
        assert bd.discount == pytest.approx(50.0)

    def test_distributor_tiers(self, engine: PricingEngine):
        assert engine.calculate_price(100.0, 250, CustomerType.DISTRIBUTOR).discount == pytest.approx(5000.0)
        assert engine.calculate_price(100.0, 120, CustomerType.DISTRIBUTOR).discount == pytest.approx(1800.0)
        assert engine.calculate_price(100.0, 10, CustomerType.DISTRIBUTOR).discount == pytest.approx(100.0)

    def test_wholesale_tiers(self, engine: PricingEngine):
        assert engine.calculate_price(100.0, 60, CustomerType.WHOLESALE).discount == pytest.approx(480.0)
        assert engine.calculate_price(100.0, 10, CustomerType.WHOLESALE).discount == pytest.approx(30.0)

    def test_default_customer_type_is_retail(self, engine: PricingEngine):
        bd = engine.calculate_price(50.0, 1)
        assert bd.discount == 0.0


class TestBulkDiscount:
    def _items(self, n: int) -> list[dict]:
        return [{"price": 100.0, "quantity": 1} for _ in range(n)]

    def test_below_threshold(self, engine: PricingEngine):
        assert engine.calculate_bulk_discount(self._items(5)) == 0.0

    def test_ten_items_3pct(self, engine: PricingEngine):
        assert engine.calculate_bulk_discount(self._items(10)) == pytest.approx(30.0)

    def test_twenty_items_5pct(self, engine: PricingEngine):
        assert engine.calculate_bulk_discount(self._items(20)) == pytest.approx(100.0)

    def test_custom_threshold(self, engine: PricingEngine):
        assert engine.calculate_bulk_discount(self._items(8), threshold=20) == 0.0

    def test_missing_price_defaults_zero(self, engine: PricingEngine):
        items = [{} for _ in range(10)]
        assert engine.calculate_bulk_discount(items) == 0.0


class TestVolumeTier:
    @pytest.mark.parametrize(
        ("qty", "expected"),
        [(1000, "tier_1"), (500, "tier_2"), (100, "tier_3"), (50, "tier_4"), (10, "standard")],
    )
    def test_tiers(self, engine: PricingEngine, qty: int, expected: str):
        assert engine.get_volume_tier(qty) == expected


def test_get_pricing_engine_factory():
    assert isinstance(get_pricing_engine(), PricingEngine)
