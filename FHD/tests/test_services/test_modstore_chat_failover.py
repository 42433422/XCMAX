from app.infrastructure.llm.modstore_chat_failover import (
    build_chat_failover_candidates,
    is_market_chat_failoverable,
)


def test_failoverable_status_and_markers():
    assert is_market_chat_failoverable(429, "insufficient_quota")
    assert not is_market_chat_failoverable(None, "平台错误(402): 余额不足")
    assert not is_market_chat_failoverable(403, "配额不足")
    assert is_market_chat_failoverable(404, "当前模型或模型服务入口不可用")
    assert not is_market_chat_failoverable(401, "凭证无效")


def test_unconfirmed_gateway_and_transport_results_do_not_authorize_failover():
    assert not is_market_chat_failoverable(500, "Internal Server Error")
    assert not is_market_chat_failoverable(503, "Service Unavailable")
    assert not is_market_chat_failoverable(None, "ReadTimeout: timed out")
    assert not is_market_chat_failoverable(None, "ConnectError: connection refused")


def test_wallet_dependency_failure_is_not_failoverable():
    assert not is_market_chat_failoverable(
        502, "Java 支付服务不可用: cannot connect (JAVA_PAYMENT_SERVICE_URL=...)"
    )


def test_build_candidates_orders_primary_then_status():
    status = {
        "fernet_configured": True,
        "providers": [
            {"provider": "openai", "has_platform_key": True},
            {"provider": "deepseek", "has_platform_key": True},
            {"provider": "xiaomi", "has_user_override": True},
        ],
    }
    catalog = {
        "providers": [
            {"provider": "openai", "models": ["gpt-4o-mini"]},
            {"provider": "deepseek", "models": ["deepseek-chat"]},
            {"provider": "xiaomi", "runtime_models": ["mimo-v2"]},
        ]
    }
    out = build_chat_failover_candidates(
        primary_provider="openai",
        primary_model="gpt-4o-mini",
        status_payload=status,
        catalog_payload=catalog,
        resolved_default={"ok": True, "provider": "deepseek", "model": "deepseek-chat"},
        max_attempts=3,
    )
    assert out[0] == ("openai", "gpt-4o-mini")
    assert ("deepseek", "deepseek-chat") in out
    assert len(out) <= 3


def test_same_gateway_aliases_are_deduplicated_and_bounded():
    candidates = build_chat_failover_candidates(
        primary_provider="litellm",
        primary_model="kimi",
        resolved_default={"provider": "litellm", "model": "kimi"},
        status_payload={"providers": [{"provider": "litellm", "has_platform_key": True}]},
        catalog_payload={
            "providers": [
                {"provider": "litellm", "runtime_models": ["kimi", "kimi", "mimo", "other"]}
            ]
        },
        max_attempts=2,
    )
    assert candidates == [("litellm", "kimi"), ("litellm", "mimo")]
