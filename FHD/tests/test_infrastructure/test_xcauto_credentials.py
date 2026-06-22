from __future__ import annotations


def _clear_llm_env(monkeypatch) -> None:
    for key in (
        "XCAUTO_API_KEY",
        "XCAUTO_PAT",
        "XIUCI_API_KEY",
        "XCAUTO_BASE_URL",
        "XCAUTO_API_BASE",
        "XCAUTO_API_URL",
        "XCAUTO_CHAT_COMPLETIONS_URL",
        "XCAUTO_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_URL",
        "DEEPSEEK_MODEL",
        "LLM_PROVIDER",
        "XCAGI_LLM_PROVIDER",
        "LLM_MODEL",
        "DP_MODEL",
        "FHD_EMPLOYEE_LLM_PROVIDER",
        "FHD_EMPLOYEE_LLM_MODEL",
        "XCAGI_EMPLOYEE_LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_xcauto_explicit_env_resolves_openai_compatible_defaults(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("XCAUTO_API_KEY", "pat-test")

    from app.infrastructure.llm.providers.credentials import (
        default_chat_completions_url,
        resolve_default_chat_model,
        resolve_default_openai_provider,
        resolve_openai_env_credentials,
        resolve_xcauto_credentials,
    )

    creds = resolve_xcauto_credentials()
    assert creds is not None
    assert creds.api_key == "pat-test"
    assert creds.api_url == "https://xiu-ci.com/v1/chat/completions"
    assert creds.model == "xcauto-account"
    assert default_chat_completions_url() == creds.api_url
    assert resolve_default_chat_model() == "xcauto-account"
    assert resolve_default_openai_provider() == "xcauto"
    assert resolve_openai_env_credentials() == ("pat-test", "https://xiu-ci.com/v1")


def test_xcauto_openai_sdk_style_env_resolves_account_model(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "pat-openai-style")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://xiu-ci.com/v1")

    from app.infrastructure.llm.providers.credentials import (
        resolve_default_chat_model,
        resolve_default_openai_provider,
        resolve_openai_env_credentials,
        resolve_xcauto_credentials,
    )

    creds = resolve_xcauto_credentials()
    assert creds is not None
    assert creds.api_key == "pat-openai-style"
    assert creds.model == "xcauto-account"
    assert resolve_default_chat_model() == "xcauto-account"
    assert resolve_default_openai_provider() == "xcauto"
    assert resolve_openai_env_credentials() == ("pat-openai-style", "https://xiu-ci.com/v1")


def test_explicit_xcauto_env_wins_over_generic_openai_env(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("XCAUTO_API_KEY", "pat-xcauto")
    monkeypatch.setenv("OPENAI_API_KEY", "pat-openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    from app.infrastructure.llm.providers.credentials import (
        resolve_default_openai_provider,
        resolve_openai_env_credentials,
    )

    assert resolve_openai_env_credentials() == ("pat-xcauto", "https://xiu-ci.com/v1")
    assert resolve_default_openai_provider() == "xcauto"


def test_llm_provider_xcauto_alias_routes_to_openai_compatible(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "xcauto")
    monkeypatch.setenv("XCAUTO_API_KEY", "pat-router")

    import app.infrastructure.llm.providers.registry as registry

    registry._registry = None
    provider = registry.get_active_provider()

    assert provider is not None
    assert provider.provider_id == "openai_compatible"
    assert provider.is_configured is True


def test_llm_routing_order_xcauto_alias_routes_to_openai_compatible(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_ROUTING_ORDER", "xcauto")
    monkeypatch.setenv("XCAUTO_API_KEY", "pat-router")

    import app.infrastructure.llm.providers.registry as registry

    registry._registry = None
    provider = registry.get_active_provider()

    assert provider is not None
    assert provider.provider_id == "openai_compatible"
    assert provider.is_configured is True


def test_employee_agent_defaults_to_xcauto_credentials(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("XCAUTO_API_KEY", "pat-employee")

    from app.application.employee_runtime.agent_runner import _resolve_employee_llm_config

    cfg = _resolve_employee_llm_config()

    assert cfg["provider"] == "xcauto"
    assert cfg["model"] == "xcauto-account"
    assert cfg["api_key"] == "pat-employee"
    assert cfg["base_url"] == "https://xiu-ci.com/v1"


def test_mod_employee_llm_defaults_to_xcauto_direct(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("XCAUTO_API_KEY", "pat-mod")

    from app.mod_sdk.mod_employee_llm import _chat_url_from_base_url, _resolve_provider_override

    override = _resolve_provider_override()

    assert _chat_url_from_base_url("https://xiu-ci.com/v1") == (
        "https://xiu-ci.com/v1/chat/completions"
    )
    assert override["use_direct"] is True
    assert override["provider"] == "xcauto"
    assert override["api_key"] == "pat-mod"
    assert override["model"] == "xcauto-account"
    assert override["chat_url"] == "https://xiu-ci.com/v1/chat/completions"


def test_llm_cost_units_are_estimated_from_tokens(monkeypatch):
    monkeypatch.delenv("FHD_LLM_TOKENS_PER_COST_UNIT", raising=False)

    from app.infrastructure.billing.model_usage import estimate_llm_cost_units

    assert estimate_llm_cost_units(prompt_tokens=2, completion_tokens=3) == 1
    assert estimate_llm_cost_units(total_tokens=1000) == 1
    assert estimate_llm_cost_units(total_tokens=1001) == 2


def test_model_usage_ledger_records_idempotent_entries(tmp_path, monkeypatch):
    ledger_path = tmp_path / "model_usage_ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger_path))

    from app.infrastructure.billing.model_usage import (
        list_model_usage_entries,
        record_model_usage,
    )

    first = record_model_usage(
        run_id="run-1",
        user_id="user-1",
        provider_id="openai_compatible",
        provider="xcauto",
        model="xcauto-account",
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
        cost_units=1,
        billing_status="metered",
        billing_source="estimated_token_units",
        source="test",
        usage_key="run-1:llm-1",
    )
    second = record_model_usage(
        run_id="run-1",
        user_id="user-1",
        provider_id="openai_compatible",
        provider="xcauto",
        model="xcauto-account",
        total_tokens=5,
        cost_units=1,
        source="test",
        usage_key="run-1:llm-1",
    )

    assert second["usage_id"] == first["usage_id"]
    entries = list_model_usage_entries(run_id="run-1")
    assert len(entries) == 1
    assert entries[0]["provider"] == "xcauto"
    assert entries[0]["model"] == "xcauto-account"
    assert entries[0]["cost_units"] == 1


def test_model_usage_ledger_debits_wallet_once(tmp_path, monkeypatch):
    ledger_path = tmp_path / "model_usage_ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger_path))

    from app.infrastructure.billing.model_usage import (
        get_model_wallet,
        record_model_usage,
        set_model_wallet_balance,
    )

    set_model_wallet_balance("user-1", 3, reason="test")
    first = record_model_usage(
        run_id="run-1",
        user_id="user-1",
        provider="xcauto",
        model="xcauto-account",
        total_tokens=5,
        cost_units=2,
        usage_key="run-1:llm-1",
    )
    duplicate = record_model_usage(
        run_id="run-1",
        user_id="user-1",
        provider="xcauto",
        model="xcauto-account",
        total_tokens=5,
        cost_units=2,
        usage_key="run-1:llm-1",
    )

    assert first["billing_status"] == "debited"
    assert first["wallet_debit"]["balance_before_units"] == 3
    assert first["wallet_debit"]["balance_after_units"] == 1
    assert duplicate["usage_id"] == first["usage_id"]
    assert get_model_wallet("user-1")["balance_units"] == 1


def test_model_usage_ledger_records_insufficient_balance(tmp_path, monkeypatch):
    ledger_path = tmp_path / "model_usage_ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger_path))
    monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")

    from app.infrastructure.billing.model_usage import record_model_usage

    entry = record_model_usage(
        run_id="run-1",
        user_id="user-1",
        provider="xcauto",
        model="xcauto-account",
        total_tokens=5,
        cost_units=2,
        usage_key="run-1:llm-1",
    )

    assert entry["billing_status"] == "insufficient_balance"
    assert entry["billing_source"] == "local_model_wallet"
    assert entry["wallet_debit"]["shortfall_units"] == 2


class _MarketWalletResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _MarketWalletClient:
    def __init__(self, responses: list[_MarketWalletResponse], calls: list[dict]):
        self._responses = list(responses)
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, headers=None, json=None):
        self._calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        return self._responses.pop(0)


def test_model_usage_ledger_debits_market_wallet(tmp_path, monkeypatch):
    ledger_path = tmp_path / "model_usage_ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger_path))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    monkeypatch.setenv("MODEL_USAGE_MARKET_BASE_URL", "http://market.test")
    monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "market-token")
    monkeypatch.setenv("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT", "0.02")

    from app.infrastructure.billing import model_usage

    calls: list[dict] = []
    responses = [
        _MarketWalletResponse(
            200,
            {
                "ok": True,
                "hold": {"hold_no": "AIH123", "amount": "0.04", "status": "held"},
                "balance": "0.96",
            },
        ),
        _MarketWalletResponse(
            200,
            {
                "ok": True,
                "hold": {
                    "hold_no": "AIH123",
                    "amount": "0.04",
                    "settled_amount": "0.04",
                    "status": "settled",
                },
                "balance": "0.96",
            },
        ),
    ]
    monkeypatch.setattr(
        model_usage.httpx,
        "Client",
        lambda *args, **kwargs: _MarketWalletClient(responses, calls),
    )

    entry = model_usage.record_model_usage(
        run_id="run-market",
        user_id="u1",
        provider="xcauto",
        model="xcauto-account",
        total_tokens=5,
        cost_units=2,
        usage_key="run-market:llm-1",
    )
    duplicate = model_usage.record_model_usage(
        run_id="run-market",
        user_id="u1",
        provider="xcauto",
        model="xcauto-account",
        total_tokens=5,
        cost_units=2,
        usage_key="run-market:llm-1",
    )

    assert entry["billing_status"] == "debited"
    assert entry["billing_source"] == "market_wallet"
    assert entry["wallet_debit"]["status"] == "debited"
    assert entry["wallet_debit"]["amount_yuan"] == "0.04"
    assert entry["wallet_debit"]["hold_no"] == "AIH123"
    assert entry["wallet_debit"]["balance_after_yuan"] == "0.96"
    assert calls[0]["url"] == "http://market.test/api/wallet/ai/preauthorize"
    assert calls[0]["headers"]["Authorization"] == "Bearer market-token"
    assert calls[0]["json"]["amount"] == "0.04"
    assert calls[1]["url"] == "http://market.test/api/wallet/ai/settle"
    assert duplicate["usage_id"] == entry["usage_id"]
    assert len(calls) == 2


def test_model_usage_ledger_records_market_wallet_insufficient_balance(tmp_path, monkeypatch):
    ledger_path = tmp_path / "model_usage_ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger_path))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    monkeypatch.setenv("MODEL_USAGE_MARKET_BASE_URL", "http://market.test")
    monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "market-token")

    from app.infrastructure.billing import model_usage

    calls: list[dict] = []
    responses = [_MarketWalletResponse(402, {"detail": "余额不足，需要 ¥0.01，当前 ¥0.00"})]
    monkeypatch.setattr(
        model_usage.httpx,
        "Client",
        lambda *args, **kwargs: _MarketWalletClient(responses, calls),
    )

    entry = model_usage.record_model_usage(
        run_id="run-market-low",
        user_id="u1",
        provider="xcauto",
        model="xcauto-account",
        total_tokens=5,
        cost_units=1,
        usage_key="run-market-low:llm-1",
    )

    assert entry["billing_status"] == "insufficient_balance"
    assert entry["billing_source"] == "market_wallet"
    assert entry["wallet_debit"]["status"] == "insufficient_balance"
    assert "余额不足" in entry["wallet_debit"]["message"]
    assert len(calls) == 1
