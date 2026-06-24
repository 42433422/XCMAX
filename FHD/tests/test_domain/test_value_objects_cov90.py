"""app/domain/value_objects.py（遗留单文件）覆盖率补强单测。

注意：``import app.domain.value_objects`` 会解析到同名包目录(``value_objects/``)，
而本目标是同级的单文件 ``value_objects.py``。因此沿用 test_value_objects_legacy.py
的做法，用 importlib 按文件路径直接加载该模块，coverage 按真实文件路径计入。

全部为纯逻辑值对象（不可变构造校验/运算/工厂/多行业字段映射），离线、确定性；
对依赖行业配置的分支用确定性 fake config 注入或 patch 模块级 get_current_industry_config。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_legacy_vo():
    """按文件路径加载遗留单文件模块（与 legacy 测试同构）。"""
    path = _ROOT / "app/domain/value_objects.py"
    spec = importlib.util.spec_from_file_location("legacy_domain_value_objects_cov90", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def vo():
    return _load_legacy_vo()


# 涂料行业默认配置，供需要确定性行业上下文的测试注入。
_COATING_CONFIG = {
    "primary": "桶",
    "secondary": "kg",
    "primary_label": "桶数",
    "secondary_label": "公斤",
    "spec_label": "规格",
    "primary_field": "tins",
    "secondary_field": "kg",
    "spec_field": "spec_per_tin",
    "conversion": {"桶_to_kg": 20.0},
}


class TestMoneyArithmetic:
    def test_add_same_currency_returns_sum(self, vo):
        result = vo.Money(10.0, "CNY") + vo.Money(2.5, "CNY")
        assert result.amount == 12.5
        assert result.currency == "CNY"

    def test_add_mismatched_currency_raises(self, vo):
        with pytest.raises(ValueError, match="货币单位不一致"):
            vo.Money(10.0, "CNY") + vo.Money(5.0, "USD")

    def test_mul_scales_amount_keeps_currency(self, vo):
        result = vo.Money(10.0, "USD") * 3
        assert result.amount == 30.0
        assert result.currency == "USD"


class TestQuantityInitAliasesAndDefaults:
    def test_coating_aliases_override_positional(self, vo):
        q = vo.Quantity(tins=5, kg=50.0, spec_per_tin=8.0, industry_config=_COATING_CONFIG)
        assert q.primary == 5
        assert q.secondary == 50.0
        assert q.spec == 8.0

    def test_defaults_applied_when_all_none(self, vo):
        q = vo.Quantity(industry_config=_COATING_CONFIG)
        assert q.primary == 0
        assert q.secondary == 0.0
        assert q.spec == 10.0

    def test_negative_primary_raises(self, vo):
        with pytest.raises(ValueError, match="桶数不能为负数"):
            vo.Quantity(primary=-1, industry_config=_COATING_CONFIG)

    def test_negative_secondary_raises(self, vo):
        with pytest.raises(ValueError, match="重量不能为负数"):
            vo.Quantity(primary=1, secondary=-2.0, industry_config=_COATING_CONFIG)

    def test_int_and_float_coercion(self, vo):
        q = vo.Quantity(primary=3, secondary=7, spec=2, industry_config=_COATING_CONFIG)
        assert isinstance(q.primary, int)
        assert isinstance(q.secondary, float)
        assert isinstance(q.spec, float)
        assert q.secondary == 7.0


class TestQuantityCompatProperties:
    def test_coating_alias_properties(self, vo):
        q = vo.Quantity(tins=4, kg=40.0, spec_per_tin=12.0, industry_config=_COATING_CONFIG)
        assert q.tins == 4
        assert q.kg == 40.0
        assert q.spec_per_tin == 12.0

    def test_generic_value_properties(self, vo):
        q = vo.Quantity(primary=6, secondary=18.0, industry_config=_COATING_CONFIG)
        assert q.primary_value == 6
        assert q.secondary_value == 18.0

    def test_label_and_unit_properties_from_config(self, vo):
        q = vo.Quantity(tins=1, industry_config=_COATING_CONFIG)
        assert q.primary_label == "桶数"
        assert q.secondary_label == "公斤"
        assert q.spec_label == "规格"
        assert q.primary_unit == "桶"
        assert q.secondary_unit == "kg"

    def test_label_defaults_when_config_missing_keys(self, vo, monkeypatch):
        # 空 industry_config 在 __init__ 处会被 `or` 当作 falsy 回退，
        # 因此 patch 模块级 get_current_industry_config 返回真正的空 dict，
        # 以触发各 *_label / *_unit 属性的 .get(..., 默认值) 回退分支。
        monkeypatch.setattr(vo, "get_current_industry_config", dict)
        q = vo.Quantity(tins=1)
        assert q.primary_label == "数量"
        assert q.secondary_label == "重量"
        assert q.spec_label == "规格"
        assert q.primary_unit == "桶"
        assert q.secondary_unit == "kg"


class TestQuantityEqHashRepr:
    def test_eq_true_for_same_values(self, vo):
        a = vo.Quantity(tins=2, kg=20.0, spec_per_tin=10.0, industry_config=_COATING_CONFIG)
        b = vo.Quantity(tins=2, kg=20.0, spec_per_tin=10.0, industry_config=_COATING_CONFIG)
        assert a == b

    def test_eq_false_for_different_values(self, vo):
        a = vo.Quantity(tins=2, kg=20.0, industry_config=_COATING_CONFIG)
        c = vo.Quantity(tins=3, kg=20.0, industry_config=_COATING_CONFIG)
        assert a != c

    def test_eq_false_for_non_quantity(self, vo):
        a = vo.Quantity(tins=2, industry_config=_COATING_CONFIG)
        assert (a == "not-a-quantity") is False

    def test_hash_equal_for_equal_objects(self, vo):
        a = vo.Quantity(tins=2, kg=20.0, spec_per_tin=10.0, industry_config=_COATING_CONFIG)
        b = vo.Quantity(tins=2, kg=20.0, spec_per_tin=10.0, industry_config=_COATING_CONFIG)
        assert hash(a) == hash(b)

    def test_repr_contains_units_and_spec(self, vo):
        r = repr(vo.Quantity(tins=3, kg=30.0, spec_per_tin=10.0, industry_config=_COATING_CONFIG))
        assert "Quantity(" in r
        assert "桶" in r
        assert "spec=10.0" in r


class TestQuantitySerialization:
    def test_to_dict_uses_config_field_names(self, vo):
        d = vo.Quantity(
            tins=2, kg=20.0, spec_per_tin=10.0, industry_config=_COATING_CONFIG
        ).to_dict()
        assert d == {"tins": 2, "kg": 20.0, "spec_per_tin": 10.0}

    def test_to_dict_falls_back_to_default_field_names(self, vo, monkeypatch):
        # 真正的空配置 → to_dict 走 .get(field, 默认字段名) 回退到 tins/kg/spec_per_tin。
        monkeypatch.setattr(vo, "get_current_industry_config", dict)
        d = vo.Quantity(tins=1, kg=5.0, spec_per_tin=4.0).to_dict()
        assert d == {"tins": 1, "kg": 5.0, "spec_per_tin": 4.0}

    def test_to_industry_dict_includes_labels_and_units(self, vo):
        d = vo.Quantity(
            tins=2, kg=20.0, spec_per_tin=10.0, industry_config=_COATING_CONFIG
        ).to_industry_dict()
        assert d["primary"] == 2
        assert d["primary_label"] == "桶数"
        assert d["primary_unit"] == "桶"
        assert d["secondary"] == 20.0
        assert d["secondary_label"] == "公斤"
        assert d["secondary_unit"] == "kg"
        assert d["spec"] == 10.0
        assert d["spec_label"] == "规格"


class TestQuantityFactories:
    def test_from_tins_and_spec_computes_secondary(self, vo):
        q = vo.Quantity.from_tins_and_spec(4, 10.0)
        assert q.primary == 4
        assert q.secondary == 40.0
        assert q.spec == 10.0

    def test_from_primary_and_spec_uses_conversion_table(self, vo, monkeypatch):
        # 注入确定性涂料配置：conversion 桶_to_kg=20.0 应覆盖 spec 用于换算 secondary。
        monkeypatch.setattr(vo, "get_current_industry_config", lambda: dict(_COATING_CONFIG))
        q = vo.Quantity.from_primary_and_spec(3, 5.0)
        assert q.primary == 3
        # secondary = primary * conversion(20.0) = 60.0，而非 primary*spec(15.0)
        assert q.secondary == 60.0
        assert q.spec == 5.0

    def test_from_primary_and_spec_falls_back_to_spec_when_no_conversion(self, vo, monkeypatch):
        cfg = {
            "primary": "件",
            "secondary": "箱",
            "primary_field": "pieces",
            "secondary_field": "cartons",
            "spec_field": "spec_per_box",
            "conversion": {},  # 无匹配 key → 回退 spec
        }
        monkeypatch.setattr(vo, "get_current_industry_config", lambda: cfg)
        q = vo.Quantity.from_primary_and_spec(4, 2.5)
        assert q.primary == 4
        # 无 conversion 命中 → secondary = primary * spec
        assert q.secondary == 10.0
        assert q.spec == 2.5

    def test_from_dict_with_config_field_names(self, vo, monkeypatch):
        monkeypatch.setattr(vo, "get_current_industry_config", lambda: dict(_COATING_CONFIG))
        q = vo.Quantity.from_dict({"tins": 6, "kg": 60.0, "spec_per_tin": 12.0})
        assert q.primary == 6
        assert q.secondary == 60.0
        assert q.spec == 12.0

    def test_from_dict_generic_fallback_keys(self, vo, monkeypatch):
        # 行业字段名与数据键不匹配时，逐级回退到 primary/secondary/spec。
        cfg = {
            "primary_field": "pieces",
            "secondary_field": "cartons",
            "spec_field": "spec_per_box",
        }
        monkeypatch.setattr(vo, "get_current_industry_config", lambda: cfg)
        q = vo.Quantity.from_dict({"primary": 2, "secondary": 8.0, "spec": 4.0})
        assert q.primary == 2
        assert q.secondary == 8.0
        assert q.spec == 4.0

    def test_from_dict_defaults_when_empty(self, vo, monkeypatch):
        monkeypatch.setattr(vo, "get_current_industry_config", lambda: dict(_COATING_CONFIG))
        q = vo.Quantity.from_dict({})
        assert q.primary == 0
        assert q.secondary == 0.0
        assert q.spec == 10.0


class TestOrderNumber:
    def test_empty_value_raises(self, vo):
        with pytest.raises(ValueError, match="订单号不能为空"):
            vo.OrderNumber("")

    def test_str_returns_value(self, vo):
        assert str(vo.OrderNumber("ORD-001")) == "ORD-001"


class TestPrice:
    def test_negative_unit_price_raises(self, vo):
        with pytest.raises(ValueError, match="单价不能为负数"):
            vo.Price(-1.0)

    def test_discount_rate_above_one_raises(self, vo):
        with pytest.raises(ValueError, match="折扣率必须在 0-1 之间"):
            vo.Price(10.0, discount_rate=1.5)

    def test_discount_rate_below_zero_raises(self, vo):
        with pytest.raises(ValueError, match="折扣率必须在 0-1 之间"):
            vo.Price(10.0, discount_rate=-0.1)

    def test_final_price_applies_discount(self, vo):
        assert vo.Price(100.0, 0.8).final_price() == pytest.approx(80.0)

    def test_calculate_amount_uses_quantity_kg(self, vo):
        amount = vo.Price(10.0, 1.0).calculate_amount(
            vo.Quantity(tins=1, kg=5.0, industry_config=_COATING_CONFIG)
        )
        assert amount == pytest.approx(50.0)


class TestModelNumber:
    def test_empty_value_raises(self, vo):
        with pytest.raises(ValueError, match="型号不能为空"):
            vo.ModelNumber("")

    def test_str_returns_value(self, vo):
        assert str(vo.ModelNumber("ABC-123")) == "ABC-123"

    def test_matches_is_case_insensitive(self, vo):
        assert vo.ModelNumber("Abc").matches(vo.ModelNumber("aBC")) is True
        assert vo.ModelNumber("Abc").matches(vo.ModelNumber("xyz")) is False

    def test_contains_is_case_insensitive(self, vo):
        assert vo.ModelNumber("Hello-World").contains("WORLD") is True
        assert vo.ModelNumber("Hello").contains("zzz") is False
