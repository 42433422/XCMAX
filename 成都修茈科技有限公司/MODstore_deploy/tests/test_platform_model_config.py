"""Platform settings exercise authorization, durable secrets and the real dispatch path."""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import llm_key_resolver as keys
from modstore_server import platform_model_config as config
from modstore_server import platform_model_config_api as api
from modstore_server.api.deps import get_current_user
from modstore_server.llm_crypto import decrypt_secret, encrypt_secret

KEY = "opaque-platform-test-key-alpha"
NEXT_KEY = "opaque-platform-test-key-beta"
BASE = "https://gateway.example.com/compatible/v1"
PATH = "/api/llm/admin/platform-model-config"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("MODSTORE_DATA_DIR", raising=False)
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MODSTORE_LLM_RUNTIME_ROUTE_PATH", str(tmp_path / "runtime-route.json"))
    monkeypatch.setenv("MODSTORE_EMPLOYEE_PLATFORM_FALLBACK_ENABLED", "0")
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", raising=False)
    monkeypatch.delenv("MODSTORE_EMPLOYEE_BENCH_MODEL", raising=False)
    for name in list(os.environ):
        if name.endswith(("_API_KEY", "_BASE_URL")) or name in {
            "XIAOMI_MIMO_API_KEY",
            "MINIMAX_CODING_PLAN_API_KEY",
        }:
            monkeypatch.delenv(name, raising=False)


def payload(**changes):
    return {
        "base_url": BASE,
        "model": "custom-model",
        "display_name": "平台对话模型",
        "api_key": KEY,
        "expected_revision": None,
        **changes,
    }


def save(provider="openai", **changes):
    body = payload(**changes)
    if body.get("api_key") is not None:
        body["api_key"] = SecretStr(body["api_key"])
    return config.save_config(provider, body, actor="admin:7")


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/llm")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, is_admin=True)
    monkeypatch.setattr(api, "_pin_url", lambda _url: None)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "method,suffix", [("get", ""), ("put", "/openai"), ("post", "/openai/test")]
)
@pytest.mark.parametrize("authenticated", [False, True])
def test_admin_gate_precedes_body_parsing(client, method, suffix, authenticated):
    def identity():
        if not authenticated:
            raise HTTPException(401, "请登录")
        return SimpleNamespace(id=5, is_admin=False)

    client.app.dependency_overrides[get_current_user] = identity
    response = getattr(client, method)(PATH + suffix)
    assert response.status_code == (403 if authenticated else 401)
    assert response.headers["cache-control"] == "no-store"
    assert not config.config_path().exists()


def test_save_mask_readback_and_restart(client):
    response = client.put(PATH + "/openai", json=payload())
    assert response.status_code == 200
    assert response.json()["config"]["has_key"] is True
    assert KEY not in response.text
    assert response.headers["cache-control"] == "no-store"
    saved = config.config_path().read_text()
    assert KEY not in saved
    assert decrypt_secret(json.loads(saved)["providers"]["openai"]["api_key_encrypted"]) == KEY
    if os.name != "nt":
        assert config.config_path().stat().st_mode & 0o777 == 0o600
    response = client.get(PATH)
    assert KEY not in response.text
    assert response.json()["default_provider"] == "openai"
    row = next(row for row in response.json()["providers"] if row["provider"] == "openai")
    assert row["masked_key"] and row["display_name"] == "平台对话模型"
    check = "from modstore_server.llm_key_resolver import platform_api_key; assert platform_api_key('openai') == 'opaque-platform-test-key-alpha'"
    assert (
        subprocess.run(
            [sys.executable, "-c", check], capture_output=True, timeout=20, check=False
        ).returncode
        == 0
    )


def test_retain_key_and_reject_changed_endpoint_or_stale_revision(client):
    first = client.put(PATH + "/openai", json=payload()).json()["config"]
    before = config.config_path().read_bytes()
    invalid = payload(
        base_url="https://other.example.com/v1",
        api_key=None,
        expected_revision=first["revision"],
    )
    assert client.put(PATH + "/openai", json=invalid).status_code == 400
    assert config.config_path().read_bytes() == before
    update = payload(api_key=None, display_name="新名称", expected_revision=first["revision"])
    response = client.put(PATH + "/openai", json=update)
    assert response.status_code == 200
    assert keys.platform_api_key("openai") == KEY
    assert response.json()["config"]["revision"] != first["revision"]
    assert client.put(PATH + "/openai", json=update).status_code == 409


def test_missing_encryption_and_corruption_fail_closed(client, monkeypatch):
    monkeypatch.delenv("MODSTORE_LLM_MASTER_KEY")
    assert client.put(PATH + "/openai", json=payload()).status_code == 503
    assert not config.config_path().exists()
    monkeypatch.setenv("OPENAI_API_KEY", "environment-only-test-key")
    config.config_path().parent.mkdir(parents=True)
    config.config_path().write_text("{invalid")
    assert client.get(PATH).status_code == 503
    with pytest.raises(config.PlatformConfigError):
        keys.platform_api_key("openai")


def test_rotated_master_key_can_recover_with_new_secret(client, monkeypatch):
    first = client.put(PATH + "/openai", json=payload()).json()["config"]
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode())
    row = next(row for row in client.get(PATH).json()["providers"] if row["provider"] == "openai")
    assert row["has_key"] is False
    with pytest.raises(config.PlatformConfigError):
        keys.platform_api_key("openai")
    response = client.put(
        PATH + "/openai",
        json=payload(api_key=NEXT_KEY, expected_revision=first["revision"]),
    )
    assert response.status_code == 200
    assert keys.platform_api_key("openai") == NEXT_KEY


@pytest.mark.parametrize(
    "changes",
    [
        {"api_key": {"nested": KEY}},
        {"model": {"secret": KEY}},
        {"base_url": f"https://account:{KEY}@gateway.example.com/v1"},
        {"base_url": f"https://gateway.example.com/v1?key={KEY}"},
        {"display_name": KEY},
        {"api_key": "****"},
        {"base_url": "http://gateway.example.com/v1"},
    ],
)
def test_invalid_input_never_echoes_secret(client, changes):
    response = client.put(PATH + "/openai", json=payload(**changes))
    assert response.status_code == 400
    assert KEY not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert not config.config_path().exists()


def test_environment_urls_are_not_exposed_or_created(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setenv(
        "OPENAI_BASE_URL", f"https://user:{KEY}@gateway.example.com/v1?token={NEXT_KEY}"
    )
    response = client.get(PATH)
    assert KEY not in response.text and NEXT_KEY not in response.text
    assert not config.config_path().parent.exists()


@pytest.mark.parametrize(
    "outcome,status", [(True, 200), (False, 502), ("timeout", 504), ("error", 502)]
)
def test_connection_test_feedback_never_persists_or_returns_secrets(
    client, monkeypatch, outcome, status
):
    async def probe(provider, draft, secret):
        assert provider == "openai" and draft["model"] == "custom-model" and secret == KEY
        if outcome == "timeout":
            raise TimeoutError(KEY)
        if outcome == "error":
            raise httpx.ConnectError(KEY)
        return outcome

    monkeypatch.setattr(api, "_probe", probe)
    response = client.post(PATH + "/openai/test", json=payload())
    assert response.status_code == status
    assert KEY not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert not config.config_path().exists()
    if status == 200:
        assert "尚未保存" in response.json()["message"]


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/v1",
        "https://169.254.169.254/v1",
        "https://[::1]/v1",
        "https://metadata.google.internal/v1",
    ],
)
def test_private_connection_targets_are_blocked(url):
    with pytest.raises(config.PlatformConfigError, match="公网 HTTPS"):
        api._pin_url(url)


def test_mixed_public_private_dns_is_blocked(monkeypatch):
    from modstore_server import openapi_connector_runtime as outbound

    monkeypatch.setattr(
        outbound.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(config.PlatformConfigError):
        api._pin_url("https://mixed.example.com/v1")


def test_concurrent_edits_allow_only_one_revision_and_failed_write_preserves_file(
    monkeypatch,
):
    state = save()
    revision = state["providers"]["openai"]["revision"]

    def edit(label):
        try:
            save(display_name=label, api_key=None, expected_revision=revision)
            return 200
        except config.PlatformConfigError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, ("名称甲", "名称乙"))) == [200, 409]
    before = config.config_path().read_bytes()
    monkeypatch.setattr(
        config.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("permission")),
    )
    with pytest.raises(config.PlatformConfigError, match="保存失败"):
        save(expected_revision=config.stored_config("openai")["revision"])
    assert config.config_path().read_bytes() == before
    assert not list(config.config_path().parent.glob("*.tmp"))


@pytest.fixture
def database(tmp_path, monkeypatch):
    from modstore_server import models

    engine = create_engine(
        f"sqlite:///{tmp_path / 'users.db'}", connect_args={"check_same_thread": False}
    )
    models.User.__table__.create(engine)
    models.UserLlmCredential.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(models, "get_session_factory", lambda: factory)
    with factory() as db:
        db.add_all(
            [models.User(id=i, username=f"user-{i}", password_hash="test-only") for i in (1, 2)]
        )
        db.commit()
        yield db
    engine.dispose()


def test_byok_ownership_and_endpoint_never_mix(database):
    from modstore_server.models import UserLlmCredential

    save()
    byok = UserLlmCredential(
        user_id=1,
        provider="openai",
        api_key_encrypted=encrypt_secret("user-one-test-key"),
        base_url_encrypted=encrypt_secret("https://byok.example.com/v1"),
    )
    database.add(byok)
    database.commit()
    assert keys.resolve_credentials(database, 1, "openai") == (
        "user-one-test-key",
        "https://byok.example.com/v1",
        "user_override",
    )
    assert keys.resolve_credentials(database, 2, "openai") == (KEY, BASE, "platform")
    byok.base_url_encrypted = None
    database.commit()
    assert keys.resolve_credentials(database, 1, "openai")[1] == "https://api.openai.com"
    byok.api_key_encrypted = "unreadable"
    byok.base_url_encrypted = encrypt_secret("https://untrusted.example.com/v1")
    database.commit()
    assert keys.resolve_credentials(database, 1, "openai") == (None, None, "none")


@pytest.mark.asyncio
async def test_catalog_and_defaults_respect_user_and_explicit_employee_route(database, monkeypatch):
    from modstore_server import llm_api, llm_catalog, llm_runtime_route
    from modstore_server.models import User, UserLlmCredential
    from modstore_server.services.llm import resolve_platform_bench_llm

    save()
    catalog = await llm_catalog.get_models_for_provider(database, 2, "openai")
    assert catalog["models"] == ["custom-model"]
    assert catalog["models_detailed"][0]["display_name"] == "平台对话模型"
    assert (await llm_api.resolve_default_llm_route(database, 2))["model"] == "custom-model"
    assert resolve_platform_bench_llm() == ("openai", "custom-model")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-environment-test-key")
    user = database.get(User, 2)
    user.default_llm_json = json.dumps({"provider": "deepseek", "model": "user-preferred"})
    database.commit()
    assert (await llm_api.resolve_default_llm_route(database, 2))["model"] == "user-preferred"
    database.add(
        UserLlmCredential(
            user_id=1,
            provider="deepseek",
            api_key_encrypted=encrypt_secret("byok-test-key"),
        )
    )
    database.commit()

    async def catalog_for_user(*_args, **_kwargs):
        return {"models": ["byok-model"]}

    monkeypatch.setattr(llm_api, "get_models_for_provider", catalog_for_user)
    selected = await llm_api.resolve_default_llm_route(database, 1)
    assert selected["source"] == "byok" and selected["provider"] == "deepseek"
    llm_runtime_route.commit_runtime_route(
        "deepseek", "explicit-employee", actor="test", reason="selected"
    )
    assert resolve_platform_bench_llm() == ("deepseek", "explicit-employee")


@pytest.fixture
def upstream(monkeypatch):
    from modstore_server import openapi_connector_runtime as outbound
    from modstore_server import platform_model_transport as transport

    real_client = httpx.AsyncClient
    observed = {
        "requests": [],
        "pinned": [],
        "options": [],
        "status": 200,
        "stream": False,
        "gzip": False,
    }

    def pin(url):
        observed["pinned"].append(url)
        parsed = httpx.URL(url)
        return outbound.PinnedOutboundTarget(
            str(parsed.copy_with(host="93.184.216.34")), parsed.host, parsed.host
        )

    def respond(request):
        observed["requests"].append(request)
        if observed["status"] != 200:
            return httpx.Response(observed["status"], text=f"header echoed: {KEY}")
        if observed["stream"]:
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n',
            )
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"content": [{"type": "text", "text": "OK"}]})
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})
        if request.url.path.endswith("/token_plan/remains"):
            return httpx.Response(
                200,
                json={
                    "model_remains": [
                        {
                            "model_name": "general",
                            "current_interval_remaining_percent": 80,
                        }
                    ]
                },
            )
        if observed["gzip"]:
            return httpx.Response(
                200,
                content=gzip.compress(
                    json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
                ),
                headers={"Content-Encoding": "gzip"},
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "OK"}}], "debug": {KEY: KEY}}
        )

    def client(**kwargs):
        observed["options"].append(kwargs)
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(outbound, "pin_url_outbound_safe", pin)
    monkeypatch.setattr(transport.httpx, "AsyncClient", client)
    return observed


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_environment", [False, True])
async def test_rotation_keeps_key_and_endpoint_bound(upstream, monkeypatch, initial_environment):
    from modstore_server.llm_chat_proxy import chat_dispatch

    if initial_environment:
        monkeypatch.setenv("OPENAI_API_KEY", KEY)
        monkeypatch.setenv("OPENAI_BASE_URL", BASE)
    else:
        save()
    snapshot = keys.platform_api_key("openai")
    revision = (config.stored_config("openai") or {}).get("revision")
    save(
        base_url="https://new.example.com/api/v1",
        api_key=NEXT_KEY,
        expected_revision=revision,
    )
    result = await chat_dispatch(
        "openai",
        api_key=snapshot,
        base_url=keys.platform_base_url("openai"),
        model="custom-model",
        messages=[{"role": "user", "content": "test"}],
    )
    assert result["ok"] is True
    assert KEY not in json.dumps(result)
    request = upstream["requests"][0]
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["host"] == "gateway.example.com"
    if not initial_environment:
        assert upstream["pinned"] == [BASE + "/chat/completions"]
        assert request.extensions["sni_hostname"] == "gateway.example.com"
        assert upstream["options"][0]["follow_redirects"] is False
        assert upstream["options"][0]["trust_env"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_real_chat_errors_never_return_upstream_keys(upstream, caplog, stream):
    from modstore_server.llm_chat_proxy import chat_dispatch, chat_dispatch_stream

    save()
    upstream["status"] = 401
    kwargs = {
        "api_key": keys.platform_api_key("openai"),
        "base_url": BASE,
        "model": "custom-model",
        "messages": [{"role": "user", "content": "test"}],
    }
    result = (
        [item async for item in chat_dispatch_stream("openai", **kwargs)]
        if stream
        else await chat_dispatch("openai", **kwargs)
    )
    assert KEY not in json.dumps(result) and KEY not in caplog.text
    assert upstream["pinned"] == [BASE + "/chat/completions"]


@pytest.mark.asyncio
async def test_stream_and_byok_keep_their_own_endpoints(upstream):
    from modstore_server.llm_chat_proxy import chat_dispatch, chat_dispatch_stream

    save()
    upstream["stream"] = True
    events = [
        event
        async for event in chat_dispatch_stream(
            "openai",
            api_key=keys.platform_api_key("openai"),
            base_url="https://wrong.example.com/v1",
            model="custom-model",
            messages=[{"role": "user", "content": "test"}],
        )
    ]
    assert events == [{"type": "delta", "delta": "OK"}]
    assert upstream["pinned"] == [BASE + "/chat/completions"]
    upstream["stream"] = False
    await chat_dispatch(
        "openai",
        api_key="user-only-test-key",
        base_url="https://byok.example.com/v1",
        model="user-model",
        messages=[{"role": "user", "content": "test"}],
    )
    assert upstream["requests"][-1].url.host == "byok.example.com"
    assert upstream["requests"][-1].headers["authorization"] == "Bearer user-only-test-key"


@pytest.mark.asyncio
async def test_probe_uses_real_dispatch_without_saving(upstream):
    assert await api._probe(
        "openai",
        {
            "provider": "openai",
            "base_url": BASE,
            "model": "custom-model",
            "display_name": "test",
        },
        KEY,
    )
    assert not config.config_path().exists()
    request = upstream["requests"][0]
    assert json.loads(request.content)["model"] == "custom-model"
    assert upstream["pinned"] == [BASE + "/chat/completions"]


@pytest.mark.asyncio
async def test_platform_key_cannot_leak_to_fallback_provider(upstream):
    from modstore_server.llm_chat_proxy import chat_dispatch

    save()
    upstream["status"] = 401
    result = await chat_dispatch(
        "openai",
        api_key=keys.platform_api_key("openai"),
        base_url=BASE,
        model="custom-model",
        messages=[{"role": "user", "content": "test"}],
        timeout_fallback_s=1,
        fallback_provider="anthropic",
        fallback_model="fallback-model",
    )
    assert result["ok"] is False
    assert len(upstream["requests"]) == 1


@pytest.mark.parametrize(
    "base,expected",
    [
        ("https://gateway.example.com", "https://gateway.example.com/v1"),
        (BASE + "/chat/completions", BASE),
        ("https://gateway.example.com/custom/", "https://gateway.example.com/custom"),
    ],
)
def test_api_address_normalization_matches_managed_dispatch(base, expected):
    from modstore_server.llm_chat_proxy import _normalize_openai_base

    save(base_url=base)
    assert config.public_config("openai")["base_url"] == expected
    assert (
        _normalize_openai_base(
            "openai", "https://wrong.example.com/v1", keys.platform_api_key("openai")
        )
        == expected
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("draft", [False, True])
async def test_minimax_managed_and_draft_dispatch_pin_saved_base(upstream, monkeypatch, draft):
    from modstore_server.llm_chat_proxy import chat_dispatch

    secret = "minimaxsk-cp-platform-test-only"
    monkeypatch.setenv("MINIMAX_ANTHROPIC_BASE_URL", "https://old.example.com/anthropic")
    if draft:
        assert await api._probe(
            "minimax",
            {
                "provider": "minimax",
                "base_url": BASE,
                "model": "MiniMax-M2.7",
                "display_name": "test",
            },
            secret,
        )
        assert not config.config_path().exists()
    else:
        save("minimax", api_key=secret, model="MiniMax-M2.7")
        result = await chat_dispatch(
            "minimax",
            api_key=keys.platform_api_key("minimax"),
            base_url="https://wrong.example.com/v1",
            model="MiniMax-M2.7",
            messages=[{"role": "user", "content": "test"}],
        )
        assert result["ok"] is True and result["content"] == "OK"
    assert upstream["pinned"] == [BASE.removesuffix("/v1") + "/anthropic/v1/messages"]
    request = upstream["requests"][0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == request.extensions["sni_hostname"] == "gateway.example.com"
    assert request.headers["x-api-key"] == "sk-cp-platform-test-only"
    assert upstream["options"][0]["follow_redirects"] is False
    assert upstream["options"][0]["trust_env"] is False


def test_minimax_legacy_environment_override_is_preserved(monkeypatch):
    monkeypatch.setenv("MINIMAX_ANTHROPIC_BASE_URL", "https://legacy.example.com/anthropic")
    assert keys.minimax_anthropic_base_url(BASE) == "https://legacy.example.com/anthropic"


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_base", [None, "https://wrong.example.com/v1"])
async def test_minimax_fallback_reused_key_keeps_its_saved_endpoint(
    upstream, monkeypatch, fallback_base
):
    from modstore_server.llm_chat_proxy import chat_dispatch

    monkeypatch.setenv("MINIMAX_ANTHROPIC_BASE_URL", "https://old.example.com/anthropic")
    save("minimax", api_key="sk-cp-platform-test-only", model="MiniMax-M2.7")
    upstream["status"] = 401
    result = await chat_dispatch(
        "minimax",
        api_key=keys.platform_api_key("minimax"),
        base_url=BASE,
        model="MiniMax-M2.7",
        messages=[{"role": "user", "content": "test"}],
        timeout_fallback_s=1,
        fallback_provider="minimax",
        fallback_model="MiniMax-M2.7",
        fallback_base_url=fallback_base,
    )
    assert result["ok"] is False
    expected = BASE.removesuffix("/v1") + "/anthropic/v1/messages"
    assert upstream["pinned"] == [expected, expected]


@pytest.mark.asyncio
async def test_managed_embedding_uses_same_secret_endpoint_snapshot(
    upstream, database, monkeypatch
):
    from modstore_server.embedding_service import embed_texts

    save()
    monkeypatch.setenv("MODSTORE_EMBEDDING_DIM_OPENAI", "3")
    monkeypatch.setattr(keys, "resolve_base_url", lambda *_args: "https://wrong.example.com/v1")
    assert await embed_texts(["test"], session=database, user_id=2, provider="openai") == [
        [0.1, 0.2, 0.3]
    ]
    assert upstream["pinned"] == [BASE + "/embeddings"]
    assert upstream["requests"][0].headers["authorization"] == f"Bearer {KEY}"


@pytest.mark.asyncio
@pytest.mark.parametrize("base", [BASE, "https://api.minimaxi.com/v1"])
async def test_managed_quota_never_sends_key_to_unrelated_environment_endpoint(
    upstream, monkeypatch, base
):
    from modstore_server.llm_quota_monitor import fetch_minimax_token_plan_quota

    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_REMAINS_URL", "https://wrong.example.com/remains")
    save("minimax", base_url=base)
    result = await fetch_minimax_token_plan_quota(
        keys.platform_api_key("minimax"), base_url="https://wrong.example.com"
    )
    if base == BASE:
        assert result["visibility"] == "usage_only"
        assert upstream["requests"] == []
    else:
        assert result["state"] == "healthy"
        assert upstream["pinned"] == ["https://www.minimaxi.com/v1/token_plan/remains"]
        assert upstream["requests"][0].method == "GET"


@pytest.mark.asyncio
async def test_managed_gzip_response_is_decoded_once(upstream):
    from modstore_server.llm_chat_proxy import chat_dispatch

    save()
    upstream["gzip"] = True
    result = await chat_dispatch(
        "openai",
        api_key=keys.platform_api_key("openai"),
        base_url=BASE,
        model="custom-model",
        messages=[{"role": "user", "content": "test"}],
    )
    assert result["ok"] is True and result["content"] == "OK"
    assert len(upstream["requests"]) == 1
