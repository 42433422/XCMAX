"""智能对话单据打印闭环：意图路由 + 统一输出目录 + 价格表 task 载荷。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.application.normal_chat_dispatch import route_normal_mode_message
from app.application.tools.exports import handle_price_list_export


def test_route_price_list_before_bare_print() -> None:
    rr = route_normal_mode_message("打印成都某某有限公司的价格表")
    assert rr["intent"] == "price_list"
    assert "成都某某有限公司" in str(rr["slots"].get("customer_name", ""))


def test_route_price_list_spaced_demo_customer() -> None:
    rr = route_normal_mode_message("打印XC 演示客户的价格表")
    assert rr["intent"] == "price_list"
    assert "演示客户" in str(rr["slots"].get("customer_name", ""))


def test_route_price_list_print_demo_unit() -> None:
    rr = route_normal_mode_message("打印演示客户有限公司的价格表")
    assert rr["intent"] == "price_list"
    assert rr["slots"].get("customer_name") == "演示客户有限公司"


def test_route_price_list_price_catalog_alias() -> None:
    rr = route_normal_mode_message("生成甲厂价目表")
    assert rr["intent"] == "price_list"
    assert rr["slots"].get("customer_name") == "甲厂"


def test_route_shipment_open_order_still_shipment() -> None:
    rr = route_normal_mode_message("开单给向总")
    assert rr["intent"] == "shipment"


def test_route_shipment_dadan_keyword() -> None:
    rr = route_normal_mode_message("打单")
    assert rr["intent"] == "shipment"


def test_handle_price_list_export_writes_app_data_shipment_outputs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

    mock_svc = MagicMock()
    mock_svc.get_all_products.return_value = [
        {"model_number": "A1", "name": "产品A", "price": 10}
    ]

    with (
        patch("app.application.get_product_app_service", return_value=mock_svc),
        patch(
            "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
            return_value=(tmp_path / "tpl.docx", "tpl"),
        ),
        patch(
            "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
            return_value=b"PK\x03\x04fake-docx",
        ),
        patch(
            "app.application.tools.exports.get_app_data_dir",
            return_value=str(tmp_path),
        ),
    ):
        result = handle_price_list_export({"customer_name": "成都路演客户有限公司"})

    assert result["success"] is True
    out = Path(result["file_path"])
    assert out.parent == tmp_path / "shipment_outputs"
    assert out.exists()
    assert result["doc_name"].endswith(".docx")
    assert result["download_url"].startswith("/api/shipment/download/")
    assert "成都路演客户有限公司" in result["filename"]
