"""Synthetic session/route receipts; no external model or real account is used."""

import json
import logging
import time
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from app.application import elt_login_authorization as auth
from app.application.reviewed_excel_audit import ModelRequestNotSent
from app.fastapi_routes.domains.auth.credential_login import CredentialLogin


@pytest.fixture
def login(monkeypatch):
    monkeypatch.setattr(auth, "NOTICE_PUBLISHED", True)
    monkeypatch.setenv("SECRET_KEY", "synthetic-login-notice-signing-key-1234567890")
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://synthetic-platform.invalid")
    monkeypatch.setenv("FHD_TEMPLATE_LLM_PROVIDER", "platform")
    identity = {"owner": 7, "tenant": 9, "expires": int(time.time()) + 3600}
    route = {
        "base": "https://synthetic-platform.invalid",
        "provider": "synthetic",
        "model": "synthetic-model",
    }
    monkeypatch.setattr(
        auth, "_active_session", lambda sid: identity if sid == "synthetic-session" else None
    )
    monkeypatch.setattr(auth, "_resolve_login_route", AsyncMock(return_value=route))
    return {"success": True, "session_id": "synthetic-session", "user": {"id": 7}}, route


def request(receipt="", session="synthetic-session"):
    cookie = SimpleCookie()
    cookie["session_id"] = session
    if receipt:
        cookie[auth.NOTICE_COOKIE] = receipt
    return Request(
        {
            "type": "http",
            "headers": [(b"cookie", cookie.output(header="", sep=";").encode())],
            "path": "/preview",
        }
    )


async def receipt_for(result):
    response = await auth.attach_login_notice(
        JSONResponse({}), result, {"data_processing_notice_version": auth.NOTICE_VERSION}
    )
    cookie = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        cookie.load(header)
    return cookie[auth.NOTICE_COOKIE].value, response


@pytest.mark.asyncio
async def test_successful_explicit_login_records_version_scope_identity_and_session_expiry(login):
    result, route = login
    receipt, response = await receipt_for(result)
    grant = auth.login_notice_grant(request(receipt), 9, 7)
    assert grant["version"] == auth.NOTICE_VERSION
    assert grant["purpose"] == "elt_template_candidates"
    assert grant["max_cells"] == 100 and grant["max_chars_per_cell"] == 160
    assert grant["route"] == route
    assert grant["exp"] <= int(time.time()) + 3600
    assert result["session_id"] not in json.dumps(grant)
    assert "HttpOnly" in response.headers.getlist("set-cookie")[-1]
    assert auth.login_notice_status(request(receipt), 9, 7)["status"] == "authorized"


@pytest.mark.asyncio
async def test_unpublished_draft_cannot_issue_or_reuse_model_authorization(login, monkeypatch):
    result, _ = login
    receipt, _ = await receipt_for(result)
    monkeypatch.setattr(auth, "NOTICE_PUBLISHED", False)
    assert (await receipt_for(result))[0] == ""
    assert auth.login_notice_grant(request(receipt), 9, 7) is None
    assert auth.login_notice_status(request(receipt), 9, 7)["status"] == "notice_not_published"


@pytest.mark.asyncio
async def test_login_resolves_only_metadata_with_the_exact_new_session(monkeypatch):
    from app.fastapi_routes import market_account

    monkeypatch.setenv("FHD_TEMPLATE_LLM_PROVIDER", "platform")
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://synthetic-platform.invalid/")
    monkeypatch.setattr(
        market_account,
        "session_market_token",
        lambda sid: "synthetic-token" if sid == "new-session" else "",
    )
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"ok": True, "provider": "synthetic", "model": "synthetic-model"},
    )
    client = SimpleNamespace(get=AsyncMock(return_value=response))
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kwargs: context)
    assert await auth._resolve_login_route("old-session") is None
    assert await auth._resolve_login_route("new-session") == {
        "base": "https://synthetic-platform.invalid",
        "provider": "synthetic",
        "model": "synthetic-model",
    }
    client.get.assert_awaited_once_with(
        "https://synthetic-platform.invalid/api/llm/resolve-chat-default"
    )


@pytest.mark.asyncio
async def test_missing_old_version_failed_login_unknown_session_and_unavailable_route_do_not_grant(
    login, monkeypatch
):
    result, _ = login
    for payload, body in [
        (result, {}),
        (result, {"data_processing_notice_version": "old"}),
        ({**result, "success": False}, {"data_processing_notice_version": auth.NOTICE_VERSION}),
        (
            {**result, "session_id": "other"},
            {"data_processing_notice_version": auth.NOTICE_VERSION},
        ),
    ]:
        response = await auth.attach_login_notice(JSONResponse({}), payload, body)
        assert not any(
            f"{auth.NOTICE_COOKIE}=ey" in value for value in response.headers.getlist("set-cookie")
        )
    monkeypatch.setattr(auth, "_resolve_login_route", AsyncMock(return_value=None))
    assert (await receipt_for(result))[0] == ""
    monkeypatch.delenv("SECRET_KEY")
    assert (await receipt_for(result))[0] == ""
    assert auth.login_notice_status(request(), 9, 7)["status"] == "login_notice_required"


@pytest.mark.asyncio
async def test_receipt_rejects_other_account_session_platform_tampering_expiry_and_purpose(
    login, monkeypatch
):
    result, _ = login
    token, _ = await receipt_for(result)
    assert auth.login_notice_grant(request(token), 8, 7) is None
    assert auth.login_notice_grant(request(token), 9, 8) is None
    assert auth.login_notice_grant(request(token, "other"), 9, 7) is None
    assert auth.login_notice_grant(request(token + "tampered"), 9, 7) is None
    claims = jwt.decode(token, auth._secret(), algorithms=["HS256"], audience=auth._AUDIENCE)
    for changes in [
        {"exp": int(time.time()) - 1},
        {"purpose": "all_files"},
        {"version": "old"},
        {"max_cells": 1000},
    ]:
        altered = jwt.encode({**claims, **changes}, auth._secret(), algorithm="HS256")
        assert auth.login_notice_grant(request(altered), 9, 7) is None
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://other-platform.invalid")
    assert auth.login_notice_grant(request(token), 9, 7) is None


@pytest.mark.asyncio
async def test_route_scope_blocks_changed_supplier_or_model_before_dispatch_and_resets(login):
    result, route = login
    token, _ = await receipt_for(result)
    grant = auth.login_notice_grant(request(token), 9, 7)
    with auth.bind_login_notice_grant(grant):
        auth.assert_login_notice_route(route["base"], route["provider"], route["model"])
        for provider, model in [
            ("other-supplier", route["model"]),
            (route["provider"], "other-model"),
        ]:
            with pytest.raises(ModelRequestNotSent):
                auth.assert_login_notice_route(route["base"], provider, model)
    auth.assert_login_notice_route("admin-existing-route", "admin", "admin")


@pytest.mark.asyncio
async def test_final_resolved_route_change_cannot_reach_model_adapter(login, monkeypatch):
    from unittest.mock import Mock

    from app.application.elt.llm_session_provider import SessionMarketProvider
    from app.domain.shared_services.conversation import modstore_adapter

    result, _ = login
    token, _ = await receipt_for(result)
    grant = auth.login_notice_grant(request(token), 9, 7)
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"ok": True, "provider": "changed", "model": "changed"},
    )
    client = SimpleNamespace(get=AsyncMock(return_value=response))
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kwargs: context)
    adapter = Mock()
    monkeypatch.setattr(modstore_adapter, "ModstorePlatformAdapter", adapter)
    with auth.bind_login_notice_grant(grant), pytest.raises(ModelRequestNotSent):
        await SessionMarketProvider(7, "synthetic-token", timeout_seconds=1).chat_completion([])
    adapter.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["password", "phone_code"])
async def test_credential_entry_attaches_receipt_only_after_success(method, login):
    result, _ = login
    flow = CredentialLogin(
        backend=lambda: object(),
        product_sku=lambda: "enterprise",
        normalize_kind=lambda raw, default: default,
        run_login=AsyncMock(return_value=(result, None)),
        login_market=AsyncMock(),
        login_phone=AsyncMock(return_value={"success": True}),
        jit_create=lambda *args: None,
        market_email=lambda raw: "",
        issue_tokens=lambda *args: {},
        attach_cookie=lambda response, sid: response,
        clock=lambda: 0,
        observe_login=lambda *args: None,
        infra_errors=lambda: (RuntimeError,),
        logger=logging.getLogger(__name__),
    )
    body = {
        "username": "synthetic",
        "password": "synthetic",
        "phone": "12345",
        "code": "1234",
        "data_processing_notice_version": auth.NOTICE_VERSION,
    }
    response = await getattr(flow, method)(request(), body, None)
    assert any(
        f"{auth.NOTICE_COOKIE}=ey" in value for value in response.headers.getlist("set-cookie")
    )
    flow.run_login.return_value = (None, JSONResponse({"success": False}, status_code=401))
    failure = await getattr(flow, method)(request(), body, None)
    assert not failure.headers.getlist("set-cookie")
