"""app/domain/services/shipment_rules_engine 单测。"""

from __future__ import annotations

from app.domain.services.shipment_rules_engine import ShipmentRulesEngine, get_shipment_rules_engine


def _valid_shipment() -> dict:
    return {
        "unit_name": "七彩涂料",
        "date": "2026-06-14",
        "items": [{"name": "漆", "quantity": 2, "price": 100.0}],
    }


class TestShipmentRulesEngine:
    def test_valid_shipment(self) -> None:
        result = ShipmentRulesEngine().validate(_valid_shipment())
        assert result.is_valid is True
        assert result.to_dict()["violations"] == []

    def test_missing_unit(self) -> None:
        data = dict(_valid_shipment())
        data.pop("unit_name")
        result = ShipmentRulesEngine().validate(data)
        assert result.is_valid is False

    def test_empty_items(self) -> None:
        data = dict(_valid_shipment())
        data["items"] = []
        result = ShipmentRulesEngine().validate(data)
        assert result.is_valid is False

    def test_non_positive_quantity(self) -> None:
        data = dict(_valid_shipment())
        data["items"] = [{"quantity": 0, "price": 1}]
        result = ShipmentRulesEngine().validate(data)
        assert result.is_valid is False

    def test_invalid_date(self) -> None:
        data = dict(_valid_shipment())
        data["date"] = "not-a-date"
        result = ShipmentRulesEngine().validate(data)
        assert result.is_valid is False

    def test_calculate_total(self) -> None:
        total = ShipmentRulesEngine().calculate_total(_valid_shipment())
        assert total == 200.0

    def test_suggest_priority_urgent(self) -> None:
        data = dict(_valid_shipment())
        data["unit_name"] = "加急客户"
        assert ShipmentRulesEngine().suggest_priority(data) == 1

    def test_singleton_factory(self) -> None:
        assert isinstance(get_shipment_rules_engine(), ShipmentRulesEngine)
