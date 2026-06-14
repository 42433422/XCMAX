"""COVERAGE_RAMP Phase 4 round 34: market transport errors + client shell referer/clear."""

from __future__ import annotations

import httpx
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.fastapi_routes import market_account as market_mod
from app.infrastructure.auth.client_shell_session import (
    ADMIN_SHELL,
    clear_session_cookie,
    client_shell_from_request,
)


def _make_request(*, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "headers": headers or [],
        "method": "GET",
        "path": "/",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_transport_error_message_read_timeout() -> None:
    msg, code = market_mod._transport_error_message(httpx.ReadTimeout("slow"))
    assert code == 503
    assert "超时" in msg


def test_transport_error_message_generic_connect() -> None:
    msg, code = market_mod._transport_error_message(ConnectionError("refused"))
    assert code == 502
    assert "无法连接" in msg


def test_is_local_market_base() -> None:
    assert market_mod._is_local_market_base("http://127.0.0.1:9000") is True
    assert market_mod._is_local_market_base("http://localhost:9000") is True
    assert market_mod._is_local_market_base("https://market.example.com") is False


def test_error_message_from_dict_payload() -> None:
    out = market_mod._error_message({"message": "bad token"}, 401)
    assert "bad token" in out


def test_client_shell_from_referer_admin() -> None:
    req = _make_request(
        headers=[(b"referer", b"http://127.0.0.1:5011/admin/dashboard")],
    )
    assert client_shell_from_request(req) == ADMIN_SHELL


def test_clear_session_cookie_deletes_shell_cookie() -> None:
    req = _make_request(headers=[(b"x-xcmax-client-shell", b"admin")])
    resp = clear_session_cookie(JSONResponse({}), req)
    cookie_hdr = resp.headers.get("set-cookie", "")
    assert "admin_session_id=" in cookie_hdr
