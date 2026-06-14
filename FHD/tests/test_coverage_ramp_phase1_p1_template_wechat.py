"""COVERAGE_RAMP Phase 1 (p1-p0-core): template helpers + customer/wechat domain routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.template import routes as template_routes


# ---------------------------------------------------------------------------
# Template pure helpers
# ---------------------------------------------------------------------------


def test_excel_cell_to_text() -> None:
    assert template_routes._excel_cell_to_text(None) == ""
    assert template_routes._excel_cell_to_text(42) == "42"


def test_form_bool() -> None:
    assert template_routes._form_bool(None) is False
    assert template_routes._form_bool("true") is True
    assert template_routes._form_bool("0") is False


def test_pick_header_row() -> None:
    rows = [["", ""], ["名称", "数量", "单位"], ["A", "1", "kg"]]
    idx, header = template_routes._pick_header_row(rows)
    assert idx == 1
    assert "名称" in header


def test_detect_effective_col_count() -> None:
    rows = [["a", "", "c"], ["", "b", ""]]
    assert template_routes._detect_effective_col_count(rows, 1) == 3


def test_detect_effective_row_count() -> None:
    rows = [["a"], [""], ["b"]]
    assert template_routes._detect_effective_row_count(rows, 1) == 3


def test_excel_col_width_to_px() -> None:
    assert template_routes._excel_col_width_to_px(8.43) >= 40


def test_excel_row_height_to_px() -> None:
    assert template_routes._excel_row_height_to_px(15.0) >= 20


def test_merge_anchor_and_skip() -> None:
    ws = MagicMock()
    rg = MagicMock()
    rg.min_row, rg.min_col, rg.max_row, rg.max_col = 1, 1, 2, 2
    ws.merged_cells.ranges = [rg]
    anchor, skip = template_routes._merge_anchor_and_skip(ws, 3, 3)
    assert (1, 1) in anchor
    assert (2, 2) in skip


# ---------------------------------------------------------------------------
# Customer routes
# ---------------------------------------------------------------------------


@pytest.fixture
def customer_client() -> TestClient:
    from app.fastapi_routes.domains.customer import routes as customer_routes

    app = FastAPI()
    app.include_router(customer_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.fastapi_routes.domains.customer.routes._load_customers_rows")
def test_customers_all(mock_load: MagicMock, customer_client: TestClient) -> None:
    mock_load.return_value = [{"id": 1, "name": "甲公司"}]
    r = customer_client.get("/customers")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_customers_match_empty(customer_client: TestClient) -> None:
    r = customer_client.get("/customers/match")
    assert r.status_code == 200
    assert r.json()["matched"] is None


@patch("app.fastapi_routes.domains.customer.routes._business_mod_json_block")
def test_customers_match_blocked(mock_block: MagicMock, customer_client: TestClient) -> None:
    mock_block.return_value = {"blocked": True}
    r = customer_client.get("/customers/match", params={"customer_name": "甲"})
    assert r.json()["matched"] is None


@patch("app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled")
@patch("app.fastapi_routes.domains.customer.routes._customer_row_for_api")
@patch("app.fastapi_routes.domains.customer.routes._customer_find_by_id")
def test_customers_get_by_id(
    mock_find: MagicMock,
    mock_row: MagicMock,
    mock_enabled: MagicMock,
    customer_client: TestClient,
) -> None:
    mock_enabled.return_value = False
    mock_find.return_value = {"id": 3, "name": "乙"}
    mock_row.return_value = {"id": 3, "name": "乙"}
    r = customer_client.get("/customers/3")
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "乙"


@patch("app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled")
def test_customers_post_validation(
    mock_enabled: MagicMock, customer_client: TestClient
) -> None:
    mock_enabled.return_value = False
    with patch("app.fastapi_routes.domains.customer.routes._customers_write_raise"):
        r = customer_client.post("/customers", json={})
    assert r.status_code in (400, 422)


def test_customers_get_not_found(customer_client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.domains.customer.routes._customer_find_by_id",
        return_value=None,
    ):
        r = customer_client.get("/customers/999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Wechat routes
# ---------------------------------------------------------------------------


@pytest.fixture
def wechat_client() -> TestClient:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    app = FastAPI()
    app.include_router(wechat_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@patch("app.application.get_wechat_task_app_service")
def test_wechat_tasks(mock_get: MagicMock, wechat_client: TestClient) -> None:
    mock_get.return_value.get_tasks.return_value = []
    r = wechat_client.get("/wechat/tasks")
    assert r.status_code == 200
    assert r.json()["total"] == 0


@patch("app.desktop_automation.service.get_desktop_automation_service")
@patch("app.services.wechat_passive_group_monitor.assert_safe_outbound_group_reply")
def test_send_wechat_via_automation_success(
    mock_safe: MagicMock, mock_auto: MagicMock
) -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_safe.return_value = "hello"
    mock_auto.return_value.send_wechat_message.return_value = {"success": True}
    out = wechat_routes._send_wechat_via_automation("Bob", "hello")
    assert out["success"] is True


@patch("app.desktop_automation.service.get_desktop_automation_service")
@patch("app.services.wechat_passive_group_monitor.assert_safe_outbound_group_reply")
def test_send_wechat_blocked(mock_safe: MagicMock, mock_auto: MagicMock) -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_safe.return_value = None
    out = wechat_routes._send_wechat_via_automation("Bob", "bad")
    assert out["success"] is False


def test_wechat_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    monkeypatch.setenv("SECRET_KEY", "sek")
    assert wechat_routes._secret_key() == "sek"


def test_wechat_contacts_post_validation(wechat_client: TestClient) -> None:
    r = wechat_client.post("/wechat/contacts", json={})
    assert r.status_code in (200, 400, 422)


# ---------------------------------------------------------------------------
# Wechat compat routes (partial)
# ---------------------------------------------------------------------------


@pytest.fixture
def wechat_compat_client() -> TestClient:
    from app.fastapi_routes.domains.wechat import compat_routes

    app = FastAPI()
    app.include_router(compat_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_wechat_contacts_list(wechat_compat_client: TestClient) -> None:
    r = wechat_compat_client.get("/wechat_contacts")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_wechat_contacts_decrypt_status(wechat_compat_client: TestClient) -> None:
    r = wechat_compat_client.get("/wechat_contacts/decrypt_status")
    assert r.status_code == 200


def test_wechat_contacts_search(wechat_compat_client: TestClient) -> None:
    r = wechat_compat_client.get("/wechat_contacts/search", params={"q": "x"})
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_wechat_contacts_create(wechat_compat_client: TestClient) -> None:
    r = wechat_compat_client.post(
        "/wechat_contacts",
        json={"wechat_id": "wx_test_1", "contact_name": "测试"},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True
