from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.application.tools import customer_crud_tools, report_config_tools
from app.infrastructure.payment import modstore_payment_proxy


def test_customer_field_aliases_and_none_filtering() -> None:
    assert customer_crud_tools._normalize_customer_fields([]) == {}
    assert customer_crud_tools._normalize_customer_fields(
        {
            "customer_name": "甲",
            "contact_person": "张三",
            "contact_phone": "1",
            "contact_address": "路",
        }
    ) == {
        "customer_name": "甲",
        "contact_person": "张三",
        "contact_phone": "1",
        "contact_address": "路",
    }
    assert customer_crud_tools._normalize_customer_fields(
        {"name": "乙", "person": "李四", "phone": "2", "address": None}
    ) == {"customer_name": "乙", "contact_person": "李四", "contact_phone": "2"}


def test_customer_update_contracts() -> None:
    assert "customer_id" in customer_crud_tools.update_customer({"customer_id": "bad"})["error"]
    assert "fields" in customer_crud_tools.update_customer({"customer_id": 1})["error"]
    preview = customer_crud_tools.update_customer({"customer_id": 1, "fields": {"name": "甲"}})
    assert preview["needs_confirm"] is True
    unsupported = customer_crud_tools.update_customer(
        {"customer_id": 1, "fields": {"unknown": "x"}, "confirm": True}
    )
    assert "supported" in unsupported["error"]

    service = MagicMock()
    service.update.return_value = {"success": True}
    with patch.object(customer_crud_tools, "_get_service", return_value=service):
        result = customer_crud_tools.update_customer(
            {"customer_id": 7, "fields": {"name": "甲"}, "confirm": True}
        )
    assert result == {"success": True, "customer_id": 7}
    service.update.assert_called_once_with(7, {"customer_name": "甲"})

    with patch.object(customer_crud_tools, "_get_service", side_effect=RuntimeError("down")):
        failure = customer_crud_tools.update_customer(
            {"customer_id": 7, "fields": {"name": "甲"}, "confirm": True}
        )
    assert failure["success"] is False


def test_customer_delete_and_list_contracts() -> None:
    assert "customer_id" in customer_crud_tools.delete_customer({"customer_id": "bad"})["error"]
    preview = customer_crud_tools.delete_customer({"customer_id": 3, "force": True})
    assert preview["needs_confirm"] is True and preview["force"] is True

    service = MagicMock()
    service.delete.return_value = {"success": True}
    service.get_all.return_value = {"success": True, "data": []}
    with patch.object(customer_crud_tools, "_get_service", return_value=service):
        deleted = customer_crud_tools.delete_customer(
            {"customer_id": 3, "confirm": True, "force": True}
        )
        listed = customer_crud_tools.list_customers(
            {"filters": {"keyword": " 甲 ", "page": "bad", "per_page": 999}}
        )
        fallback = customer_crud_tools.list_customers({"filters": [], "limit": "bad"})
    assert deleted["customer_id"] == 3
    assert listed["filters"]["keyword"] == " 甲 "
    service.get_all.assert_any_call(keyword="甲", page=1, per_page=200)
    service.get_all.assert_any_call(keyword=None, page=1, per_page=20)
    assert fallback["success"] is True

    with patch.object(customer_crud_tools, "_get_service", side_effect=RuntimeError("down")):
        assert (
            customer_crud_tools.delete_customer({"customer_id": 3, "confirm": True})["success"]
            is False
        )
        assert customer_crud_tools.list_customers({})["data"] == []


@pytest.fixture
def report_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: str(tmp_path))
    return tmp_path / "reports" / "report_configs.json"


def test_report_storage_load_shapes(report_store: Path) -> None:
    assert report_config_tools._load_configs() == []
    report_store.parent.mkdir(parents=True, exist_ok=True)
    report_store.write_text('{"not": "a list"}', encoding="utf-8")
    assert report_config_tools._load_configs() == []
    report_store.write_text("broken", encoding="utf-8")
    assert report_config_tools._load_configs() == []
    report_config_tools._save_configs([{"config_id": "a"}])
    assert report_config_tools._load_configs() == [{"config_id": "a"}]


def test_report_configure_validation_and_crud(report_store: Path) -> None:
    assert report_config_tools.configure_report({})["error"] == "invalid_report_type"
    assert "config" in report_config_tools.configure_report({"report_type": "sales"})["error"]
    assert (
        report_config_tools.configure_report(
            {"report_type": "sales", "config": {"chart_type": "bad"}}
        )["error"]
        == "invalid_chart_type"
    )
    assert (
        report_config_tools.configure_report(
            {"report_type": "sales", "config": {"group_by": "bad"}}
        )["error"]
        == "invalid_group_by"
    )
    assert (
        report_config_tools.configure_report(
            {"report_type": "sales", "config": {"chart_type": "bar"}}
        )["needs_confirm"]
        is True
    )

    created = report_config_tools.configure_report(
        {
            "report_type": "sales",
            "config": {"chart_type": "bar", "group_by": "month"},
            "confirm": True,
        }
    )
    assert created["success"] is True
    config_id = created["config_id"]
    assert report_config_tools.list_report_configs({})["count"] == 1
    assert report_config_tools.list_report_configs({"report_type": "inventory"})["count"] == 0

    missing = report_config_tools.configure_report(
        {
            "report_type": "sales",
            "config": {"chart_type": "line"},
            "config_id": "missing",
            "confirm": True,
        }
    )
    assert missing["error"] == "config_not_found"
    updated = report_config_tools.configure_report(
        {
            "report_type": "inventory",
            "config": {"chart_type": "line"},
            "config_id": config_id,
            "confirm": True,
        }
    )
    assert updated["success"] is True

    assert "config_id" in report_config_tools.delete_report_config({})["error"]
    assert report_config_tools.delete_report_config({"config_id": config_id})["needs_confirm"]
    assert (
        report_config_tools.delete_report_config({"config_id": "missing", "confirm": True})["error"]
        == "config_not_found"
    )
    deleted = report_config_tools.delete_report_config({"config_id": config_id, "confirm": True})
    assert deleted["success"] is True and deleted["deleted_count"] == 1
    assert json.loads(report_store.read_text(encoding="utf-8")) == []


def test_report_crud_storage_failures_are_stable(report_store: Path) -> None:
    args = {"report_type": "sales", "config": {"chart_type": "bar"}, "confirm": True}
    with patch.object(report_config_tools, "_save_configs", side_effect=OSError("disk")):
        assert report_config_tools.configure_report(args)["success"] is False
    with patch.object(report_config_tools, "_load_configs", side_effect=OSError("disk")):
        assert report_config_tools.list_report_configs({})["success"] is False
        assert (
            report_config_tools.delete_report_config({"config_id": "x", "confirm": True})["success"]
            is False
        )


def _response(status: int, data: object) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = data
    return response


def test_payment_proxy_base_auth_and_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
    monkeypatch.delenv("XCAGI_MARKET_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
    assert modstore_payment_proxy._market_base_url() == ""
    assert modstore_payment_proxy.wechat_checkout_redirect_url("p") is None

    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", " https://market.example/ ")
    assert modstore_payment_proxy.wechat_checkout_redirect_url("") is None
    assert modstore_payment_proxy.wechat_checkout_redirect_url(" pro ") == (
        "https://market.example/account-plans?plan=pro&pay_channel=wechat"
    )
    assert "market_user_id=7" in modstore_payment_proxy.wechat_checkout_redirect_url(
        "pro", market_user_id=7
    )

    monkeypatch.setenv("XCAGI_MARKET_AUTH_TOKEN", "Bearer token")
    assert modstore_payment_proxy._auth_token() == "token"
    monkeypatch.delenv("XCAGI_MARKET_AUTH_TOKEN")
    monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "fallback")
    assert modstore_payment_proxy._auth_token() == "fallback"
    monkeypatch.delenv("MODSTORE_AUTH_TOKEN")
    with patch("app.fastapi_routes.market_account.latest_session_market_token", return_value="s"):
        assert modstore_payment_proxy._auth_token(7) == "s"
    with patch(
        "app.fastapi_routes.market_account.latest_session_market_token",
        side_effect=RuntimeError("down"),
    ):
        assert modstore_payment_proxy._auth_token() == ""


def test_payment_proxy_post_json_response_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
    assert modstore_payment_proxy._post_json("/x", payload={})[1]
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example")
    with patch.object(modstore_payment_proxy, "_auth_token", return_value=""):
        assert "未登录" in modstore_payment_proxy._post_json("/x", payload={})[1]

    monkeypatch.setenv("MODSTORE_PAYMENT_TIMEOUT", "0")
    responses = [
        _response(200, {"ok": True}),
        _response(200, [1]),
        _response(400, {"message": "bad"}),
        _response(401, {"detail": "denied"}),
        _response(500, {}),
        _response(500, [1]),
    ]
    client = MagicMock()
    client.__enter__.return_value.post.side_effect = responses
    with (
        patch.object(modstore_payment_proxy, "_auth_token", return_value="t"),
        patch.object(modstore_payment_proxy.httpx, "Client", return_value=client),
    ):
        assert modstore_payment_proxy._post_json("/x", payload={}) == ({"ok": True}, None)
        assert "非对象" in modstore_payment_proxy._post_json("/x", payload={})[1]
        assert modstore_payment_proxy._post_json("/x", payload={})[1] == "bad"
        assert modstore_payment_proxy._post_json("/x", payload={})[1] == "denied"
        assert "HTTP 500" in modstore_payment_proxy._post_json("/x", payload={})[1]
        assert "HTTP 500" in modstore_payment_proxy._post_json("/x", payload={})[1]

    failing = MagicMock()
    failing.__enter__.return_value.post.side_effect = httpx.ConnectError("down")
    with (
        patch.object(modstore_payment_proxy, "_auth_token", return_value="t"),
        patch.object(modstore_payment_proxy.httpx, "Client", return_value=failing),
    ):
        assert "down" in modstore_payment_proxy._post_json("/x", payload={})[1]

    invalid_json = MagicMock()
    invalid_json.__enter__.return_value.post.return_value.json.side_effect = ValueError()
    with (
        patch.object(modstore_payment_proxy, "_auth_token", return_value="t"),
        patch.object(modstore_payment_proxy.httpx, "Client", return_value=invalid_json),
    ):
        assert modstore_payment_proxy._post_json("/x", payload={})[1] == "ValueError"


def test_checkout_and_metering_contracts() -> None:
    assert modstore_payment_proxy.proxy_checkout(plan_id="")["success"] is False
    with patch.object(modstore_payment_proxy, "_post_json", return_value=(None, "sign down")):
        assert modstore_payment_proxy.proxy_checkout(plan_id="pro")["error"] == "sign down"

    with patch.object(
        modstore_payment_proxy,
        "_post_json",
        side_effect=[({"signature": "s"}, None), (None, "checkout down")],
    ):
        assert modstore_payment_proxy.proxy_checkout(plan_id="pro")["error"] == "checkout down"
    with patch.object(
        modstore_payment_proxy,
        "_post_json",
        side_effect=[({"signature": "s"}, None), ({"order": "o"}, None)],
    ) as post:
        result = modstore_payment_proxy.proxy_checkout(plan_id="pro", channel=" ")
    assert result == {"success": True, "data": {"order": "o"}}
    assert "pay_channel" not in post.call_args_list[1].kwargs["payload"]

    record = SimpleNamespace(as_dict=lambda: {"amount_yuan": "1", "usage_key": "u"})
    with patch.object(modstore_payment_proxy, "_post_json", return_value=(None, "preauth down")):
        assert modstore_payment_proxy.record_market_metering(record)["error"] == "preauth down"
    with patch.object(modstore_payment_proxy, "_post_json", return_value=({}, None)):
        assert "hold_no" in modstore_payment_proxy.record_market_metering({})["error"]
    with patch.object(
        modstore_payment_proxy,
        "_post_json",
        side_effect=[({"hold": {"hold_no": "h"}}, None), (None, "settle down")],
    ):
        failed = modstore_payment_proxy.record_market_metering(record)
    assert failed["hold_no"] == "h"
    with patch.object(
        modstore_payment_proxy,
        "_post_json",
        side_effect=[({"hold": {"hold_no": "h"}}, None), ({"settled": True}, None)],
    ):
        settled = modstore_payment_proxy.record_market_metering(record)
    assert settled == {"success": True, "data": {"settled": True}, "hold_no": "h"}
