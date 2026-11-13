"""Synthetic account/session tests; no live account, credential or model is used."""

import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import HTTPException, Request

from app.application import elt_login_authorization as auth
from app.application.reviewed_excel_audit import ModelRequestNotSent


def publication_record():
    return {
        "notice_version": "2026-11-01",
        "recipient_disclosure_version": "2026-11-01",
        "published_at": datetime.now(UTC).isoformat(),
    }


def request(session="synthetic-session", notice=""):
    cookies = SimpleCookie()
    if session:
        cookies["session_id"] = session
    if notice:
        cookies["xcagi_elt_notice"] = notice
    return Request(
        {"type": "http", "headers": [(b"cookie", cookies.output(header="", sep=";").encode())]}
    )


@pytest.fixture
def account(monkeypatch):
    from app.fastapi_routes import market_account

    identity = {"owner": 7, "tenant": 9, "expires": int(time.time()) + 3600}
    monkeypatch.setattr(
        auth, "_active_session", lambda sid: identity if sid == "synthetic-session" else None
    )
    exact = Mock(
        side_effect=lambda sid: "synthetic-current-token" if sid == "synthetic-session" else ""
    )
    monkeypatch.setattr(market_account, "session_market_token", exact)
    return identity, exact


def test_bundled_publication_uses_same_strict_validation_when_env_absent(monkeypatch, tmp_path):
    record = publication_record()
    monkeypatch.setenv(auth.NOTICE_PUBLICATION_ENV, json.dumps(record))
    expected = auth.notice_publication()
    target = tmp_path / "elt_notice_publication.json"
    target.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(auth, "_NOTICE_PUBLICATION_FILE", target)
    monkeypatch.delenv(auth.NOTICE_PUBLICATION_ENV)
    assert auth.notice_publication() == expected


@pytest.mark.parametrize("raw", ["", "not-json", "{}"])
def test_invalid_explicit_env_cannot_fall_back_to_bundled_publication(monkeypatch, tmp_path, raw):
    target = tmp_path / "elt_notice_publication.json"
    target.write_text(json.dumps(publication_record()), encoding="utf-8")
    monkeypatch.setattr(auth, "_NOTICE_PUBLICATION_FILE", target)
    monkeypatch.setenv(auth.NOTICE_PUBLICATION_ENV, raw)
    assert auth.notice_publication() is None


def test_explicit_env_takes_precedence_over_bundled_publication(monkeypatch, tmp_path):
    target = tmp_path / "elt_notice_publication.json"
    target.write_text(
        json.dumps({**publication_record(), "published_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(auth, "_NOTICE_PUBLICATION_FILE", target)
    record = publication_record()
    monkeypatch.setenv(auth.NOTICE_PUBLICATION_ENV, json.dumps(record))
    assert auth.notice_publication()["published_at"] == record["published_at"]


@pytest.mark.parametrize("mutation", ["missing", "json", "extra", "version", "future", "oversized"])
def test_invalid_bundled_publication_is_rejected(monkeypatch, tmp_path, mutation):
    target = tmp_path / "elt_notice_publication.json"
    record = publication_record()
    if mutation == "extra":
        record["enabled"] = True
    elif mutation == "version":
        record["notice_version"] = "old"
    elif mutation == "future":
        record["published_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    if mutation != "missing":
        target.write_text(
            "not-json"
            if mutation == "json"
            else " " * 4097
            if mutation == "oversized"
            else json.dumps(record),
            encoding="utf-8",
        )
    monkeypatch.setattr(auth, "_NOTICE_PUBLICATION_FILE", target)
    monkeypatch.delenv(auth.NOTICE_PUBLICATION_ENV, raising=False)
    assert auth.notice_publication() is None


@pytest.mark.parametrize("notice", ["", "old-receipt", '{"scopes":{"template_candidates":{}}}'])
def test_existing_session_needs_no_separate_receipt_or_operation_scopes(
    account, monkeypatch, notice
):
    monkeypatch.setenv(auth.NOTICE_PUBLICATION_ENV, "not-published")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    grant = auth.require_model_session(request(notice=notice), 9, 7)
    assert dict(grant) == {"owner": 7, "tenant": 9}
    assert "synthetic-session" not in json.dumps(grant)
    assert "synthetic-session" not in repr(grant)
    assert auth.model_session_identity(request(notice=notice), 9, 7) == {
        "actor": "9:7",
        "model_access": {"status": "available"},
    }


@pytest.mark.parametrize(
    "session,tenant,owner",
    [("", 9, 7), ("other", 9, 7), ("synthetic-session", 8, 7), ("synthetic-session", 9, 8)],
)
def test_anonymous_wrong_session_account_or_tenant_cannot_select_a_model(
    account, session, tenant, owner
):
    with pytest.raises(HTTPException) as error:
        auth.require_model_session(request(session), tenant, owner)
    assert error.value.status_code in {401, 403}
    assert (
        auth.model_session_identity(request(session), tenant, owner)["model_access"]["status"]
        == "market_login_required"
    )


def test_missing_market_token_fails_instead_of_selecting_another_session(account):
    _, exact = account
    exact.side_effect = None
    exact.return_value = ""
    with pytest.raises(HTTPException) as error:
        auth.require_model_session(request(), 9, 7)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "model_configuration_error"
    assert (
        auth.model_session_identity(request(), 9, 7)["model_access"]["status"]
        == "market_login_required"
    )


@pytest.mark.parametrize("mutation", ["absent", "expired", "inactive", "tenant", "impersonated"])
def test_active_session_rejects_invalid_local_identity(monkeypatch, mutation):
    from app.db import session as db_session

    row = SimpleNamespace(
        user_id=7,
        user=SimpleNamespace(is_active=True, tenant_id=9),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        impersonating_market_user_id=None,
    )
    if mutation == "expired":
        row.expires_at -= timedelta(hours=2)
    elif mutation == "inactive":
        row.user.is_active = False
    elif mutation == "tenant":
        row.user.tenant_id = None
    elif mutation == "impersonated":
        row.impersonating_market_user_id = 99
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = (
        None if mutation == "absent" else row
    )

    @contextmanager
    def host_db():
        yield db

    monkeypatch.setattr(db_session, "get_host_db", host_db)
    assert auth._active_session("synthetic-session") is None


@pytest.mark.asyncio
async def test_exact_session_propagates_to_worker_and_resets_after_failure(account, monkeypatch):
    from starlette.concurrency import run_in_threadpool

    from app.application.elt.llm_session_provider import (
        bind_elt_llm_owner,
        current_owner_market_provider,
        reset_elt_llm_owner,
    )
    from app.fastapi_routes import market_account

    grant = auth.require_model_session(request(), 9, 7)
    _, exact = account
    exact.reset_mock()
    latest = Mock(return_value="synthetic-other-session-token")
    monkeypatch.setattr(market_account, "latest_session_market_token", latest)
    owner = bind_elt_llm_owner(7)
    try:
        with pytest.raises(RuntimeError, match="synthetic worker failure"):
            with auth.bind_model_session(grant):
                assert auth.current_model_session_id(7) == "synthetic-session"
                assert auth.current_model_session_id(8) == ""
                provider = await run_in_threadpool(current_owner_market_provider, timeout_seconds=1)
                assert provider._token == "synthetic-current-token"
                other = bind_elt_llm_owner(8)
                try:
                    assert current_owner_market_provider(timeout_seconds=1) is None
                finally:
                    reset_elt_llm_owner(other)
                exact.assert_called_once_with("synthetic-session")
                latest.assert_not_called()
                raise RuntimeError("synthetic worker failure")
        assert auth.current_model_session_id(7) is None
        with pytest.raises(ModelRequestNotSent), auth.bind_model_session(dict(grant)):
            pytest.fail("serialized identity cannot select a credential")
    finally:
        reset_elt_llm_owner(owner)


@pytest.fixture
def route_http(monkeypatch):
    client_type = httpx.AsyncClient

    def install(payload, status_code=200):
        seen = []

        def respond(request):
            seen.append(request)
            assert request.method == "GET"
            assert request.url.path == "/api/llm/resolve-chat-default"
            assert not request.url.params
            if isinstance(payload, Exception):
                raise payload
            return httpx.Response(status_code, json=payload)

        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
        )
        return seen

    return install


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["platform", "user_override"])
async def test_each_call_resolves_current_account_route_without_login_snapshot(
    account, monkeypatch, route_http, source
):
    from app.application.elt.llm_session_provider import SessionMarketProvider
    from app.domain.shared_services.conversation import modstore_adapter

    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com/market/")
    route = {
        "ok": True,
        "provider": "deepseek",
        "model": "synthetic-chat-A",
        "key_source": source,
        "config_revision": "revision-A",
        "route_token": "synthetic-snapshot-A",
    }
    seen = route_http(route)
    adapter = SimpleNamespace(
        chat_completion=AsyncMock(return_value={"model": route["model"]}), close=AsyncMock()
    )
    create = Mock(return_value=adapter)
    monkeypatch.setattr(modstore_adapter, "ModstorePlatformAdapter", create)
    grant = auth.require_model_session(request(), 9, 7)
    audit = Mock()
    with auth.bind_model_session(grant):
        provider = SessionMarketProvider(7, "synthetic-current-token", timeout_seconds=1)
        for revision in ["A", "B"]:
            route.update(
                model=f"synthetic-chat-{revision}",
                config_revision=f"revision-{revision}",
                route_token=f"synthetic-snapshot-{revision}",
            )
            await provider.chat_completion(
                [],
                provider="caller-other",
                model="caller-other",
                allow_failover=True,
                route_token="caller-snapshot",
                key_source="caller-source",
                config_revision="caller-revision",
                _reviewed_excel_audit_response=audit,
            )
            sent = adapter.chat_completion.await_args.kwargs
            assert sent["provider"] == "deepseek" and sent["model"] == route["model"]
            assert sent["allow_failover"] is False
            assert {key: sent[key] for key in ("route_token", "key_source", "config_revision")} == {
                key: route[key] for key in ("route_token", "key_source", "config_revision")
            }
            assert sent["_reviewed_excel_audit_response"] is audit
    assert len(seen) == 2
    assert all(item.headers["Authorization"] == "Bearer synthetic-current-token" for item in seen)
    assert create.call_args.kwargs["auth_token"] == "synthetic-current-token"
    assert adapter.close.await_count == 2


@pytest.mark.asyncio
async def test_intake_call_id_reaches_platform_adapter(monkeypatch, route_http):
    from app.application.elt.llm_session_provider import SessionMarketProvider
    from app.application.reviewed_excel_audit import call_key
    from app.domain.shared_services.conversation import modstore_adapter

    route_http({"ok": True, "provider": "xiaomi", "model": "synthetic-model"})
    adapter = SimpleNamespace(chat_completion=AsyncMock(return_value={}), close=AsyncMock())
    monkeypatch.setattr(modstore_adapter, "ModstorePlatformAdapter", Mock(return_value=adapter))
    with call_key("synthetic-call-123"):
        await SessionMarketProvider(7, "synthetic-token", timeout_seconds=1).chat_completion([])
    assert adapter.chat_completion.await_args.kwargs["client_request_id"] == "synthetic-call-123"


@pytest.mark.asyncio
async def test_older_platform_metadata_cannot_inherit_caller_snapshot(monkeypatch, route_http):
    from app.application.elt.llm_session_provider import SessionMarketProvider
    from app.domain.shared_services.conversation import modstore_adapter

    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com")
    route_http({"ok": True, "provider": "synthetic", "model": "synthetic-model"})
    adapter = SimpleNamespace(
        chat_completion=AsyncMock(return_value={"choices": []}), close=AsyncMock()
    )
    monkeypatch.setattr(modstore_adapter, "ModstorePlatformAdapter", lambda **kwargs: adapter)
    await SessionMarketProvider(7, "synthetic-token", timeout_seconds=1).chat_completion(
        [],
        route_token="caller-snapshot",
        key_source="caller-source",
        config_revision="caller-revision",
    )
    assert not any(
        key in adapter.chat_completion.await_args.kwargs
        for key in ("route_token", "key_source", "config_revision")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload",
    [
        (503, {"detail": {"code": "NO_CHAT_MODEL"}}),
        (403, {"detail": "quota"}),
        (200, {"ok": False}),
        (200, {"ok": True, "provider": "synthetic"}),
        (200, []),
        (200, {"ok": True, "provider": 42, "model": "synthetic-model"}),
        (200, {"ok": True, "provider": "synthetic", "model": 42}),
        (200, httpx.ConnectError("synthetic resolution unavailable")),
        (200, httpx.ReadTimeout("synthetic resolution timeout")),
    ],
)
async def test_route_failure_does_not_dispatch_or_use_a_local_substitute(
    monkeypatch, route_http, status, payload
):
    from app.application.elt.llm_session_provider import SessionMarketProvider
    from app.domain.shared_services.conversation import modstore_adapter

    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com")
    route_http(payload, status)
    create = Mock()
    monkeypatch.setattr(modstore_adapter, "ModstorePlatformAdapter", create)
    with pytest.raises(ModelRequestNotSent):
        await SessionMarketProvider(7, "synthetic-token", timeout_seconds=1).chat_completion([])
    create.assert_not_called()


@pytest.mark.parametrize("legacy_provider", ["mimo", "unsupported"])
def test_legacy_template_overrides_cannot_bypass_normal_account_routing(
    monkeypatch, legacy_provider
):
    from app.application import reviewed_excel_template as template

    monkeypatch.setenv("FHD_TEMPLATE_LLM_PROVIDER", legacy_provider)
    monkeypatch.setenv("FHD_TEMPLATE_MIMO_BASE_URL", "https://synthetic-direct.invalid/v1")
    monkeypatch.setenv("FHD_TEMPLATE_MIMO_MODEL", "synthetic-direct-model")
    monkeypatch.setenv("FHD_TEMPLATE_PLATFORM_MODEL", "synthetic-hardcoded-model")
    result = object()
    complete = Mock(return_value=result)
    monkeypatch.setattr(template, "_template_platform_complete", complete)
    messages, schema = [{"role": "user", "content": "synthetic"}], {"type": "object"}
    assert template.configured_template_llm_provider() == "platform"
    assert template.template_llm_model_label() == "platform-default"
    assert template._template_llm_complete(messages, schema, 123, owner_id=7) is result
    complete.assert_called_once_with(messages, schema, 123, owner_id=7)


@pytest.mark.asyncio
async def test_dispatch_failure_is_propagated_and_adapter_is_closed(monkeypatch, route_http):
    from app.application.elt.llm_session_provider import SessionMarketProvider
    from app.domain.shared_services.conversation import modstore_adapter

    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com")
    route_http({"ok": True, "provider": "synthetic", "model": "synthetic-model"})
    adapter = SimpleNamespace(
        chat_completion=AsyncMock(side_effect=RuntimeError("synthetic model failed")),
        close=AsyncMock(),
    )
    monkeypatch.setattr(modstore_adapter, "ModstorePlatformAdapter", lambda **kwargs: adapter)
    with pytest.raises(RuntimeError, match="synthetic model failed"):
        await SessionMarketProvider(7, "synthetic-token", timeout_seconds=1).chat_completion([])
    adapter.chat_completion.assert_awaited_once()
    adapter.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_elt_recovery_uses_explicit_market_proxy(monkeypatch):
    from app.application.elt.llm_session_provider import SessionMarketProvider

    monkeypatch.setenv("XCAGI_MARKET_PROXY", "http://127.0.0.1:7890")
    client_factory = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs.copy())
        kwargs.pop("proxy")
        return client_factory(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"state": "completed"})
            ),
            **kwargs,
        )

    monkeypatch.setattr(httpx, "AsyncClient", client)
    result = await SessionMarketProvider(7, "synthetic-token", timeout_seconds=1).lookup_call(
        "attempt-123"
    )
    assert result == {"supported": True, "state": "completed"}
    assert options[0]["proxy"] == "http://127.0.0.1:7890"
    assert options[0]["trust_env"] is False


@pytest.mark.asyncio
async def test_transient_route_connection_failure_retries_only_route_get(monkeypatch):
    from app.application.elt.llm_session_provider import SessionMarketProvider
    from app.domain.shared_services.conversation import modstore_adapter

    monkeypatch.delenv("XCAGI_MARKET_PROXY", raising=False)
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://synthetic.invalid")
    real_client = httpx.AsyncClient
    seen = []

    def respond(request):
        seen.append(request.method)
        if len(seen) == 1:
            raise httpx.ConnectError("synthetic connection reset")
        return httpx.Response(200, json={"ok": True, "provider": "synthetic", "model": "model"})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    adapter = SimpleNamespace(
        chat_completion=AsyncMock(return_value={"choices": []}), close=AsyncMock()
    )
    monkeypatch.setattr(modstore_adapter, "ModstorePlatformAdapter", lambda **kwargs: adapter)
    await SessionMarketProvider(7, "synthetic-token", timeout_seconds=1).chat_completion([])
    assert seen == ["GET", "GET"]
    assert adapter.chat_completion.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure, expected_calls",
    [
        (httpx.ConnectError("no connection"), 2),
        (httpx.ReadTimeout("result unknown"), 1),
    ],
)
async def test_intake_retries_only_definitely_unsent_model_calls(
    monkeypatch, route_http, failure, expected_calls
):
    from app.application.elt.llm_session_provider import SessionMarketProvider
    from app.domain.shared_services.conversation import modstore_adapter

    route_http({"ok": True, "provider": "synthetic", "model": "model"})
    adapter = SimpleNamespace(
        chat_completion=AsyncMock(side_effect=[failure, {"choices": []}]), close=AsyncMock()
    )
    monkeypatch.setattr(modstore_adapter, "ModstorePlatformAdapter", lambda **kwargs: adapter)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    if expected_calls == 1:
        with pytest.raises(httpx.ReadTimeout):
            await SessionMarketProvider(7, "synthetic-token", timeout_seconds=1).chat_completion([])
    else:
        await SessionMarketProvider(7, "synthetic-token", timeout_seconds=1).chat_completion([])
    assert adapter.chat_completion.await_count == expected_calls
