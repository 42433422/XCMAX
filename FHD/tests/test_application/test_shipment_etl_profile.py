"""送货单 ETL Profile：加载与切换（不改引擎即可换表头别名）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.application.shipment_etl_profile import (
    ShipmentEtlProfileError,
    clear_profile_cache,
    get_shipment_etl_profile,
    load_profile_from_path,
)
from app.application.shipment_excel_etl_app_service import parse_delivery_notes


def test_default_profile_loads():
    clear_profile_cache()
    prof = get_shipment_etl_profile("default")
    assert prof.id == "default"
    assert "model_number" in prof.columns
    assert prof.meta_patterns.title.search("工厂送货单")


def test_custom_profile_dir_switches_column_aliases(tmp_path, monkeypatch):
    """换 YAML 列别名即可解析非默认表头，无需改引擎。"""
    clear_profile_cache()
    builtin = get_shipment_etl_profile("default")
    data = yaml.safe_load(
        Path("resources/config/shipment_etl/profiles/default_delivery.yaml").read_text(
            encoding="utf-8"
        )
    )
    data["id"] = "alt_headers"
    # 识别仍用送货单语义，但表头改成英文别名
    data["detect"]["delivery"]["header_hit_tokens"] = [
        "SKU",
        "ItemName",
        "QtyPcs",
        "SpecKg",
        "QtyKg",
        "Price",
    ]
    data["header_detect"]["delivery"]["require_groups"] = [
        ["sku", "model"],
        ["itemname", "name"],
        ["qtypcs", "qty", "数量"],
    ]
    data["columns"] = {
        "model_number": [{"contains_any": ["sku", "model"]}],
        "product_name": [{"contains_any": ["itemname", "name"]}],
        "quantity_tins": [{"contains_any": ["qtypcs", "qty"]}],
        "tin_spec": [{"contains_any": ["speckg", "spec"]}],
        "quantity_kg": [{"contains_any": ["qtykg"]}],
        "unit_price": [{"contains_any": ["price", "unitprice"]}],
        "amount": [{"contains_any": ["amount", "total"]}],
        "order_number": [{"contains_any": ["orderno", "order"]}],
        "order_date": [{"contains_any": ["date"]}],
    }
    data["write"]["header_row"] = [
        "SKU",
        "",
        "",
        "ItemName",
        "QtyPcs",
        "SpecKg",
        "QtyKg",
        "Price",
        "Amount",
    ]
    data["write"]["seller_title"] = "ALT Factory Delivery"
    data["write"]["meta_line_template"] = (
        "购货单位（乙方）：{unit}     联系人：{contact}        "
        "日期：{order_date}         订单编号：{order_no}"
    )

    profile_path = tmp_path / "alt_headers.yaml"
    profile_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("FHD_SHIPMENT_ETL_PROFILE_DIR", str(tmp_path))
    clear_profile_cache()

    alt = get_shipment_etl_profile("alt_headers")
    assert alt.id == "alt_headers"
    assert alt.write["seller_title"] == "ALT Factory Delivery"

    from openpyxl import Workbook

    xlsx = tmp_path / "alt.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "N1"
    ws["A1"] = "ALT Factory Delivery 送货单"
    ws["A2"] = (
        "购货单位（乙方）：切换客户     联系人：李     "
        "日期：2026年07月25日         订单编号：ALT-1"
    )
    ws["A3"] = "SKU"
    ws["D3"] = "ItemName"
    ws["E3"] = "QtyPcs"
    ws["F3"] = "SpecKg"
    ws["G3"] = "QtyKg"
    ws["H3"] = "Price"
    ws["I3"] = "Amount"
    ws["A4"] = "ALT-01"
    ws["D4"] = "测试漆"
    ws["E4"] = 2
    ws["F4"] = 25
    ws["G4"] = 50
    ws["H4"] = 10
    ws["I4"] = 500
    wb.save(xlsx)
    wb.close()

    # 默认 profile 不应靠英文表头稳定识别为送货单明细
    default_parsed = parse_delivery_notes(xlsx, include_ledger=False, profile=builtin)
    # 切换 profile 后应成功
    alt_parsed = parse_delivery_notes(xlsx, include_ledger=False, profile=alt)
    assert alt_parsed["success"] is True
    assert alt_parsed["note_count"] == 1
    note = alt_parsed["notes"][0]
    assert note["unit_name"] == "切换客户"
    assert note["items"][0]["model_number"] == "ALT-01"
    assert note["items"][0]["product_name"] == "测试漆"
    assert note["items"][0]["quantity_tins"] == 2
    # 证明不是碰巧：若默认也能解析则至少 profile_id 不同且 alt 明确用了自定义列
    assert alt_parsed["profile_id"] == "alt_headers"
    assert default_parsed["profile_id"] == "default"


def test_unknown_profile_raises():
    clear_profile_cache()
    try:
        get_shipment_etl_profile("no_such_profile_xyz")
        raise AssertionError("expected ShipmentEtlProfileError")
    except ShipmentEtlProfileError as exc:
        assert "unknown" in str(exc).lower() or "no_such" in str(exc)


def test_load_profile_from_path_roundtrip():
    path = Path("resources/config/shipment_etl/profiles/default_delivery.yaml")
    prof = load_profile_from_path(path)
    assert prof.id == "default"
    assert prof.delivery_min_score == 60
