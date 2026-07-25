"""打单模版解析：生产级行为单测。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application.shipment_template_resolve import (
    clear_template_list_cache,
    resolve_products_for_unit,
    resolve_shipment_template,
    shipment_template_strict_enabled,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_template_list_cache()
    yield
    clear_template_list_cache()


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
            "is_active": 1,
        },
        {
            "id": "db:9",
            "name": "客户发货单",
            "path": str(good),
            "template_type": "发货单",
            "source": "db",
            "db_id": 9,
            "is_active": 1,
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


def test_resolve_unit_name_match_wins(tmp_path: Path):
    unit_tpl = tmp_path / "星光贸易发货单.xlsx"
    unit_tpl.write_bytes(b"xlsx")
    generic = tmp_path / "通用发货单.xlsx"
    generic.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = [
        {
            "id": "db:1",
            "name": "通用发货单",
            "path": str(generic),
            "template_type": "发货单",
            "source": "db",
            "db_id": 99,
            "is_active": 1,
        },
        {
            "id": "db:2",
            "name": "星光贸易发货单",
            "path": str(unit_tpl),
            "template_type": "发货单",
            "source": "db",
            "db_id": 2,
            "is_active": 1,
        },
    ]
    store.get_default_for_type.return_value = None
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(unit_name="星光贸易有限公司")
    assert out["ok"] is True
    assert out["path"] == str(unit_tpl)
    assert str(out["reason"]).startswith("unit_match")


def test_resolve_preferred_by_name(tmp_path: Path):
    tpl = tmp_path / "我的默认.xlsx"
    tpl.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = [
        {
            "id": "db:7",
            "name": "我的默认",
            "path": str(tpl),
            "template_type": "发货单",
            "is_active": 1,
        }
    ]
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(preferred="我的默认")
    assert out["ok"] is True
    assert out["source"] == "user_preference"


def test_resolve_skips_inactive_and_non_layout(tmp_path: Path):
    dead = tmp_path / "旧版.xlsx"
    dead.write_bytes(b"xlsx")
    pdf = tmp_path / "说明书.pdf"
    pdf.write_bytes(b"%PDF")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = [
        {
            "id": "db:1",
            "name": "旧版发货单",
            "path": str(dead),
            "template_type": "发货单",
            "is_active": 0,
            "db_id": 1,
        },
        {
            "id": "db:2",
            "name": "说明书",
            "path": str(pdf),
            "template_type": "发货单",
            "is_active": 1,
            "db_id": 2,
        },
    ]
    store.get_default_for_type.return_value = None
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template()
    assert out["ok"] is False
    assert out["error_code"] == "TEMPLATE_NOT_FOUND"


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


def test_strict_env_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XCAGI_SHIPMENT_TEMPLATE_STRICT", raising=False)
    assert shipment_template_strict_enabled() is False
    monkeypatch.setenv("XCAGI_SHIPMENT_TEMPLATE_STRICT", "1")
    assert shipment_template_strict_enabled() is True
    assert shipment_template_strict_enabled(False) is False
