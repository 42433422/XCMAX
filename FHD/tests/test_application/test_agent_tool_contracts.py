from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.infrastructure.payment import modstore_payment_proxy


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
        assert (
            modstore_payment_proxy.proxy_checkout(plan_id="pro", auth_token="synthetic-token")[
                "error"
            ]
            == "sign down"
        )

    with patch.object(
        modstore_payment_proxy,
        "_post_json",
        side_effect=[({"signature": "s"}, None), (None, "checkout down")],
    ):
        assert (
            modstore_payment_proxy.proxy_checkout(plan_id="pro", auth_token="synthetic-token")[
                "error"
            ]
            == "checkout down"
        )
    with patch.object(
        modstore_payment_proxy,
        "_post_json",
        side_effect=[({"signature": "s"}, None), ({"order": "o"}, None)],
    ) as post:
        result = modstore_payment_proxy.proxy_checkout(
            plan_id="pro", channel=" ", auth_token="synthetic-token"
        )
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
