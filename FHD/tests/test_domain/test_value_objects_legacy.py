"""app/domain/value_objects.py（遗留单文件）单测 — 与 compat 同构，提升独立模块覆盖。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _legacy_vo():
    path = _ROOT / "app/domain/value_objects.py"
    spec = importlib.util.spec_from_file_location("legacy_domain_value_objects", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestLegacyValueObjectsModule:
    def test_money_and_quantity(self):
        vo = _legacy_vo()
        m = vo.Money(10.0)
        assert m.to_yuan() == 10.0
        q = vo.Quantity.from_tins_and_spec(2, 10.0)
        assert q.kg == 20.0

    def test_order_number_generate(self):
        vo = _legacy_vo()
        n = vo.OrderNumber.generate()
        assert n.value.isdigit()

    def test_contact_empty(self):
        vo = _legacy_vo()
        c = vo.ContactInfo.empty()
        assert c.person == ""

    def test_money_negative_raises(self):
        vo = _legacy_vo()
        with pytest.raises(ValueError):
            vo.Money(-1)
