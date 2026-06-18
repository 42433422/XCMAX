"""COVERAGE_RAMP Phase 3 round 2: wechat_contact, purchase, xcagi_compat_product,
tools_workflow_registered, tools_payload_legacy, planner fallback."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _filter_tool_registry_for_profile,
    get_tool_registry,
)
from app.services.purchase_service import PurchaseService
from app.services.tools_payload_legacy import dispatch_legacy_tool_payload
from app.services.tools_workflow_registered import _registered_router_customers
from app.services.wechat_contact_service import WechatContactService

# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _db_ctx(db: MagicMock):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _contact_row(**kw):
    now = datetime(2026, 6, 14, 12, 0, 0)
    defaults = {
        "id": 1,
        "contact_name": "张三",
        "remark": "备注",
        "wechat_id": "wx_zhang",
        "contact_type": "contact",
        "is_starred": 0,
        "is_active": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# WechatContactService
# ---------------------------------------------------------------------------


@patch("app.services.wechat_contact_service.get_db")
def test_wechat_get_contacts_keyword(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = [_contact_row()]
    db.query.return_value = q
    mock_get_db.return_value = _db_ctx(db)
    out = WechatContactService().get_contacts(keyword="张")
    assert len(out) == 1
    assert out[0]["contact_name"] == "张三"


@patch("app.services.wechat_contact_service.get_db")
def test_wechat_get_contacts_starred_all(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = []
    db.query.return_value = q
    mock_get_db.return_value = _db_ctx(db)
    out = WechatContactService().get_contacts(contact_type="all")
    assert out == []


@patch("app.services.wechat_contact_service.get_db")
def test_wechat_get_contact_by_id(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = _contact_row(id=9)
    db.query.return_value = q
    mock_get_db.return_value = _db_ctx(db)
    out = WechatContactService().get_contact_by_id(9)
    assert out is not None
    assert out["id"] == 9


@patch("app.services.wechat_contact_service.get_db")
def test_wechat_add_and_delete_contact(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = None
    db.query.return_value = q
    mock_get_db.return_value = _db_ctx(db)
    add = WechatContactService().add_contact(
        contact_name="李四",
        wechat_id="wx_li",
        contact_type="contact",
    )
    assert add["success"] is True

    q.first.return_value = _contact_row(id=2, contact_name="李四")
    del_out = WechatContactService().delete_contact(2)
    assert del_out["success"] is True


@patch("app.services.wechat_contact_service.get_db")
def test_wechat_star_and_unstar_all(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = _contact_row()
    db.query.return_value = q
    mock_get_db.return_value = _db_ctx(db)
    star = WechatContactService().star_contact(1, starred=True)
    assert star["success"] is True

    q.update.return_value = 3
    unstar = WechatContactService().unstar_all()
    assert unstar["success"] is True


@patch("app.services.wechat_contact_service.get_db")
def test_wechat_resolve_send_message(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = [_contact_row(contact_name="张三")]
    db.query.return_value = q
    mock_get_db.return_value = _db_ctx(db)
    contact, text = WechatContactService().resolve_send_message("给张三发送：你好世界")
    assert contact == "张三"
    assert text == "你好世界"


# ---------------------------------------------------------------------------
# PurchaseService
# ---------------------------------------------------------------------------


@patch("app.services.purchase_service.get_db")
def test_purchase_get_suppliers(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.all.return_value = []
    db.query.return_value = q
    mock_get_db.return_value = _db_ctx(db)
    out = PurchaseService().get_suppliers(keyword="铜")
    assert out["success"] is True
    assert out["count"] == 0


@patch("app.services.purchase_service.get_db")
def test_purchase_get_supplier_missing(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = None
    db.query.return_value = q
    mock_get_db.return_value = _db_ctx(db)
    out = PurchaseService().get_supplier(999)
    assert out["success"] is False


# ---------------------------------------------------------------------------
# tools_workflow_registered + tools_payload_legacy
# ---------------------------------------------------------------------------


@patch("app.application.get_customer_app_service")
def test_registered_router_customers_query(mock_get: MagicMock) -> None:
    mock_get.return_value.get_all.return_value = {"success": True, "data": [{"id": 1}]}
    out = _registered_router_customers("query", {"keyword": "甲"}, {}, "pro", "查客户甲")
    assert out["success"] is True


@patch("app.application.get_customer_app_service")
def test_registered_router_customers_ensure_exists(mock_get: MagicMock) -> None:
    mock_get.return_value.match_purchase_unit.return_value = None
    mock_get.return_value.create.return_value = {"success": True}
    out = _registered_router_customers("ensure_exists", {"unit_name": "甲公司"}, {}, "pro", "")
    assert out["success"] is True


def test_dispatch_legacy_tool_products_search() -> None:
    def _j(data, status=200):
        return {"body": data, "status": status}

    with patch("app.bootstrap.get_products_service") as mock_ps:
        mock_ps.return_value.get_products.return_value = {
            "success": True,
            "data": [{"name": "漆"}],
        }
        resp = dispatch_legacy_tool_payload(
            "products",
            "query",
            {"keyword": "5003"},
            json_response_fn=_j,
            hdr_getter=lambda k: "",
            parse_order_text_fn=lambda t: {},
        )
    assert resp["body"]["success"] is True


# ---------------------------------------------------------------------------
# planner fallback / filter
# ---------------------------------------------------------------------------


def test_filter_tool_registry_pro_default() -> None:
    reg = {
        "normal_only_tool": {
            "availability": "normal_only",
            "actions": {"run": {"availability": "normal_only"}},
        },
        "shared": {"availability": "shared", "actions": {"query": {"availability": "shared"}}},
    }
    filtered = _filter_tool_registry_for_profile(reg, "pro_default")
    assert "normal_only_tool" not in filtered
    assert "shared" in filtered


def test_fallback_plan_export_price_list() -> None:
    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("p3", "导出甲公司报价表", get_tool_registry())
    assert plan.plan_id == "p3"
    assert plan.nodes


# ---------------------------------------------------------------------------
# xcagi_compat_product routes (0% file)
# ---------------------------------------------------------------------------


@pytest.fixture
def xcagi_product_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.fastapi_routes import xcagi_compat_product

    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header",
        lambda _req: None,
    )
    app = FastAPI()
    app.include_router(xcagi_compat_product.router)
    return TestClient(app, raise_server_exceptions=False)


def test_xcagi_products_units(xcagi_product_client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.xcagi_compat_product._products_units_for_select",
        return_value={"units": ["甲公司"]},
    ):
        r = xcagi_product_client.get("/products/units")
    assert r.status_code == 200


def test_xcagi_purchase_units_list(xcagi_product_client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.xcagi_compat_product._merged_purchase_unit_entries",
        return_value=[{"unit_name": "甲公司"}],
    ):
        r = xcagi_product_client.get("/purchase_units")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_xcagi_products_list(xcagi_product_client: TestClient) -> None:
    with (
        patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            return_value=None,
        ),
        patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ),
        patch(
            "app.fastapi_routes.xcagi_compat_product._load_products_list_impl_pg",
            return_value=([{"id": 1}], 1, None),
        ),
    ):
        r = xcagi_product_client.get("/products/list")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_xcagi_products_resolve_name_hints_501(xcagi_product_client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.xcagi_compat_product._business_mod_json_block",
        return_value=None,
    ):
        r = xcagi_product_client.post(
            "/products/resolve-name-hints",
            json={"hints": ["清漆"]},
        )
    assert r.status_code == 501


def test_xcagi_products_get_by_id(xcagi_product_client: TestClient) -> None:
    with (
        patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ),
        patch("app.bootstrap.get_products_service") as mock_ps,
    ):
        mock_ps.return_value.get_product.return_value = {
            "success": True,
            "data": {"id": 5, "name": "漆"},
        }
        r = xcagi_product_client.get("/products/5")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_xcagi_price_list_template_preview(xcagi_product_client: TestClient) -> None:
    with (
        patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
        patch(
            "app.infrastructure.documents.price_list_export.build_price_list_template_preview_json",
            return_value={"success": True, "headers": []},
        ),
    ):
        r = xcagi_product_client.get("/products/price-list-template-preview")
    assert r.status_code == 200
