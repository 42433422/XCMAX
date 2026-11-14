"""AIOPEN AaaS 控制面：Key 策略、限流配额、持久化与调用计量。"""

from __future__ import annotations

from itertools import count

from app.application.aiopen.runtime import ApiKeyRegistry, RuntimeState
from app.application.aiopen.usage import UsageLedger


def _registry(tmp_path, *, env: str = ""):
    issued = count(1)
    return ApiKeyRegistry(
        RuntimeState({}),
        lambda: env,
        lambda _count: f"token{next(issued)}",
        lambda: 1000.0,
        storage=lambda: tmp_path / "keys.json",
    )


def test_scope_and_expiry_are_enforced(tmp_path):
    registry = _registry(tmp_path)
    key = registry.generate("scoped", scopes=["chat"], expires_at=2000.0)["key"]
    assert registry.authorize(key, "chat")["ok"] is True
    assert registry.authorize(key, "ui_click")["code"] == "AIOPEN_SCOPE_DENIED"
    expired = registry.generate("expired", expires_at=500.0)["key"]
    assert registry.authorize(expired, "chat")["code"] == "AIOPEN_KEY_EXPIRED"


def test_rate_limit_and_daily_quota(tmp_path):
    registry = _registry(tmp_path)
    limited = registry.generate("limited", rate_limit_per_min=2)["key"]
    assert registry.authorize(limited, "chat")["ok"] is True
    assert registry.authorize(limited, "chat")["ok"] is True
    assert registry.authorize(limited, "chat")["code"] == "AIOPEN_RATE_LIMITED"

    quota = registry.generate("quota", daily_quota=1)["key"]
    assert registry.authorize(quota, "chat")["ok"] is True
    registry.record_use(quota, "chat")
    assert registry.authorize(quota, "chat")["code"] == "AIOPEN_QUOTA_EXCEEDED"


def test_keys_survive_registry_reload(tmp_path):
    first = _registry(tmp_path)
    key = first.generate("persisted")["key"]
    first.record_use(key, "chat")

    second = _registry(tmp_path)
    assert second.verify(key) is True
    listed = second.list_keys()
    assert listed[0]["today_calls"] == 1
    assert listed[0]["total_calls"] == 1


def test_usage_ledger_aggregates_and_persists(tmp_path):
    path = tmp_path / "usage.jsonl"
    ledger = UsageLedger(lambda: path, lambda: 1000.0)
    ledger.record(key_preview="k1", label="a", tool="chat", channel="rest", ok=True, duration_ms=10)
    ledger.record(key_preview="k1", label="a", tool="api_call", channel="mcp", ok=False, duration_ms=30)

    summary = ledger.summary(days=7)
    assert summary["calls"] == 2
    assert summary["errors"] == 1
    assert summary["avg_duration_ms"] == 20.0
    assert summary["by_tool"]["chat"] == 1

    reloaded = UsageLedger(lambda: path, lambda: 1000.0)
    assert reloaded.summary(days=7)["calls"] == 2
    assert reloaded.recent(1)[0]["tool"] == "api_call"


def test_environment_key_bypasses_runtime_policy(tmp_path):
    registry = _registry(tmp_path, env="env-secret")
    decision = registry.authorize("env-secret", "any_tool")
    assert decision["ok"] is True
    assert decision["env"] is True
