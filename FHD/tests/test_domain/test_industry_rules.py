"""行业规则引擎测试：证明"不同行业走不同业务规则"由 profile 数据驱动、无行业分支。"""

import json
from pathlib import Path

from app.domain.services.industry_rules import (
    FieldError,
    compute_subsystem_derived,
    register_validator,
    validate_subsystem_record,
)

FHD = Path(__file__).resolve().parents[2]


def _subsystems(manifest_path: Path) -> dict:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data["industry"]["subsystems"]


COATING = _subsystems(FHD / "mods" / "coating-industry" / "manifest.json")
ATTENDANCE = _subsystems(FHD / "XCAGI" / "mods" / "attendance-industry" / "manifest.json")


# --- 校验：oneOf（考勤班次）------------------------------------------------
def test_attendance_shift_oneof_rejects_invalid():
    schema = ATTENDANCE["products"]
    ok = validate_subsystem_record("products", {"name": "张三", "specification": "早"}, schema=schema)
    assert ok == []
    bad = validate_subsystem_record("products", {"name": "张三", "specification": "夜"}, schema=schema)
    assert any(e.field == "specification" for e in bad)
    assert "之一" in bad[0].message


def test_coating_products_no_shift_constraint():
    """涂料 products 的 specification(规格) 是自由文本，同一引擎不报 oneOf——差异纯由数据。"""
    schema = COATING["products"]
    errs = validate_subsystem_record("products", {"name": "白漆", "specification": "任意规格"}, schema=schema)
    assert errs == []


# --- 校验：required --------------------------------------------------------
def test_required_field_missing():
    schema = ATTENDANCE["products"]  # name required
    errs = validate_subsystem_record("products", {"specification": "早"}, schema=schema)
    assert any(e.field == "name" for e in errs)


# --- 校验：not_expired（涂料保质期）----------------------------------------
def test_coating_expire_date_not_expired():
    schema = COATING["products"]
    assert validate_subsystem_record("products", {"name": "A", "expire_date": "2000-01-01"}, schema=schema), (
        "过期日期应报错"
    )
    assert validate_subsystem_record("products", {"name": "A", "expire_date": "2099-12-31"}, schema=schema) == []
    # 空保质期跳过
    assert validate_subsystem_record("products", {"name": "A", "expire_date": ""}, schema=schema) == []


# --- 派生计算：涂料 orders 换算/金额 --------------------------------------
def test_coating_orders_derivation():
    schema = COATING["orders"]
    out = compute_subsystem_derived(
        "orders",
        {"quantity_tins": 3, "tin_spec": 20, "unit_price": 5},
        schema=schema,
    )
    assert out["quantity_kg"] == 60.0  # 3 桶 × 20 规格
    assert out["amount"] == 300.0      # 60 kg × 5 单价


def test_attendance_orders_no_rules_unchanged():
    """考勤 orders 未声明 rules，同一引擎不计算派生——差异纯由数据。"""
    schema = ATTENDANCE["orders"]
    record = {"quantity_tins": 3, "unit_price": 5}
    out = compute_subsystem_derived("orders", dict(record), schema=schema)
    assert out == record


# --- 注册表可扩展性 --------------------------------------------------------
def test_register_custom_validator():
    register_validator("even", lambda v, p: None if (not v or float(v) % 2 == 0) else "必须为偶数")
    schema = {"fields": [{"key": "n", "label": "数值", "validators": [{"type": "even"}]}]}
    assert validate_subsystem_record("x", {"n": 4}, schema=schema) == []
    assert validate_subsystem_record("x", {"n": 3}, schema=schema)


# --- 与 ShipmentRulesEngine 集成（真实方法，非孤儿）-----------------------
def test_shipment_rules_engine_delegates():
    from app.domain.services.shipment_rules_engine import get_shipment_rules_engine

    engine = get_shipment_rules_engine()
    result = engine.validate_subsystem(
        "products", {"name": "张三", "specification": "夜"}, schema=ATTENDANCE["products"]
    )
    assert not result.is_valid
    derived = engine.compute_subsystem_derived(
        "orders", {"quantity_tins": 2, "tin_spec": 20, "unit_price": 10}, schema=COATING["orders"]
    )
    assert derived["amount"] == 400.0


def test_field_error_to_dict():
    e = FieldError("name", "姓名", "姓名不能为空")
    assert e.to_dict() == {"field": "name", "label": "姓名", "message": "姓名不能为空"}
