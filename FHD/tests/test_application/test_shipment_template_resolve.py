"""打单模版解析：闭合模版库 → generate 断点。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.application.shipment_template_resolve import (
    resolve_products_for_unit,
    resolve_shipment_template,
)


def test_resolve_by_template_id(tmp_path: Path):
    tpl = tmp_path / "发货单模板.xlsx"
    tpl.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = str(tpl)
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(template_id="db:12")
    assert out["ok"] is True
    assert out["path"] == str(tpl)
    assert out["source"] == "template_id"
    store.resolve_template_file.assert_called_once_with("db:12")


def test_resolve_intent_default_prefers_shipment_type(tmp_path: Path):
    good = tmp_path / "客户发货单.xlsx"
    good.write_bytes(b"xlsx")
    other = tmp_path / "杂项.xlsx"
    other.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = [
        {
            "id": "db:1",
            "name": "杂项",
            "path": str(other),
            "template_type": "Excel",
            "source": "db",
            "db_id": 1,
        },
        {
            "id": "db:9",
            "name": "客户发货单",
            "path": str(good),
            "template_type": "发货单",
            "source": "db",
            "db_id": 9,
        },
    ]
    store.get_default_for_type.return_value = None
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(intent="shipment_generate")
    assert out["ok"] is True
    assert out["path"] == str(good)
    assert out["reason"].startswith("intent_default")


def test_resolve_explicit_path(tmp_path: Path):
    tpl = tmp_path / "自定义.xlsx"
    tpl.write_bytes(b"xlsx")
    store = MagicMock()
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(template_name=str(tpl))
    assert out["ok"] is True
    assert out["source"] == "explicit_path"
    store.resolve_template_file.assert_not_called()


def test_resolve_products_for_unit_from_orders():
    svc = MagicMock(spec=["get_orders"])
    svc.get_orders.return_value = [
        {"customer_name": "星光贸易", "products": [{"name": "A", "qty": 1}]},
    ]
    with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
        rows = resolve_products_for_unit("星光贸易")
    assert rows == [{"name": "A", "qty": 1}]
