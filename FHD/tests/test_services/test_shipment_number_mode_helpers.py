"""Phase 2: ShipmentNumberModeService 纯逻辑辅助方法。"""

from __future__ import annotations

from app.services.shipment_number_mode_service import ShipmentNumberModeService


class TestShipmentNumberModeHelpers:
    def test_normalize_unit_name_strips_suffix(self):
        out = ShipmentNumberModeService._normalize_unit_name("七彩乐园家具有限公司")
        assert "有限公司" not in out
        assert "家具" not in out
        assert len(out) > 0

    def test_normalize_empty(self):
        assert ShipmentNumberModeService._normalize_unit_name("") == ""
        assert ShipmentNumberModeService._normalize_unit_name("   ") == ""

    def test_resolve_unit_alias_exact(self):
        svc = ShipmentNumberModeService()
        pool = ["七彩乐园", "蕊芯化工"]
        assert svc._resolve_unit_alias("七彩乐园", pool) == "七彩乐园"

    def test_resolve_unit_alias_fuzzy_contains(self):
        svc = ShipmentNumberModeService()
        pool = ["成都七彩乐园家具有限公司", "蕊芯化工"]
        hit = svc._resolve_unit_alias("七彩乐园", pool)
        assert hit == "成都七彩乐园家具有限公司"

    def test_resolve_unit_alias_strips_qty_tail(self):
        svc = ShipmentNumberModeService()
        pool = ["蕊芯化工"]
        assert svc._resolve_unit_alias("蕊芯1", pool) == "蕊芯化工"

    def test_resolve_unit_alias_empty_pool(self):
        svc = ShipmentNumberModeService()
        assert svc._resolve_unit_alias("甲公司", []) == ""

    def test_modify_verb_pattern(self):
        pat = ShipmentNumberModeService.MODIFY_VERB_PATTERN
        assert pat.search("再加两桶")
        assert not pat.search("查询库存")
