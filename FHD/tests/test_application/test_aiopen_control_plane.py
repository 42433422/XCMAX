"""AIOPEN AaaS 控制面：Key 策略、限流配额、持久化与调用计量。"""

from __future__ import annotations

from itertools import count

import pytest

from app.application.aiopen.runtime import ApiKeyRegistry, RuntimeState
from app.application.aiopen.usage import UsageLedger


def _authorization_worker(path, key, ready, proceed):
    registry = ApiKeyRegistry(
        RuntimeState({}), lambda: "", lambda _: "unused", lambda: 1000.0, storage=lambda: path
    )
    ready.put(registry.authorize(key, "ui_click")["ok"])
    proceed.get(timeout=10)
    ready.put(registry.authorize(key, "ui_click")["ok"])


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


def test_failed_revocation_persistence_is_reported_and_keeps_original_key(tmp_path, monkeypatch):
    registry, other_worker = _registry(tmp_path), _registry(tmp_path)
    key = registry.generate("original")["key"]
    with monkeypatch.context() as failure:
        failure.setattr(registry, "_persist", lambda: False)
        with pytest.raises(OSError, match="revocation"):
            registry.revoke(key)
        assert registry.verify(key) is True
        assert other_worker.authorize(key, "chat")["ok"] is True
    assert registry.revoke(key) is True
    assert other_worker.authorize(key, "chat")["ok"] is False


def test_client_revocation_is_visible_to_other_workers_and_not_resurrected(tmp_path):
    from app.domain.aiopen.principal import ScreenPrincipal

    first, second = _registry(tmp_path), _registry(tmp_path)
    alice = ScreenPrincipal("alice", "tenant-a")
    key = first.generate(
        "screen", principal=alice, scopes=["ui_click"], expires_at=2000.0, client_key=True
    )["key"]
    assert second.authorize(key, "ui_click")["ok"] is True
    assert first.revoke_client_key(alice) is True
    assert second.authorize(key, "ui_click")["ok"] is False
    second.record_use(key, "ui_click")
    assert first.authorize(key, "ui_click")["ok"] is False
    assert second.resolve_principal(key) is None


def test_revocation_is_visible_in_a_running_separate_process(tmp_path):
    from multiprocessing import get_context

    from app.domain.aiopen.principal import ScreenPrincipal

    registry = _registry(tmp_path)
    owner = ScreenPrincipal("alice", "tenant-a")
    key = registry.generate(
        principal=owner, scopes=["ui_click"], expires_at=2000.0, client_key=True
    )["key"]
    context = get_context("spawn")
    ready, proceed = context.Queue(), context.Queue()
    worker = context.Process(
        target=_authorization_worker, args=(tmp_path / "keys.json", key, ready, proceed)
    )
    worker.start()
    try:
        assert ready.get(timeout=10) is True
        assert registry.revoke_client_key(owner) is True
        proceed.put(True)
        assert ready.get(timeout=10) is False
        worker.join(timeout=10)
        assert worker.exitcode == 0
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=5)
        ready.close()
        proceed.close()


def test_workers_do_not_overwrite_each_others_keys(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4

    from app.domain.aiopen.principal import ScreenPrincipal

    def issue(index):
        registry = ApiKeyRegistry(
            RuntimeState({}),
            lambda: "",
            lambda _: uuid4().hex,
            lambda: 1000.0,
            storage=lambda: tmp_path / "keys.json",
        )
        principal = ScreenPrincipal(f"owner-{index}", "tenant-a")
        return registry.generate(
            principal=principal, scopes=["ui_click"], expires_at=2000.0, client_key=True
        )["key"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(issue, range(16)))
    reader = _registry(tmp_path)
    assert all(reader.authorize(key, "ui_click")["ok"] for key in keys)


def test_usage_ledger_aggregates_and_persists(tmp_path):
    path = tmp_path / "usage.jsonl"
    ledger = UsageLedger(lambda: path, lambda: 1000.0)
    ledger.record(key_preview="k1", label="a", tool="chat", channel="rest", ok=True, duration_ms=10)
    ledger.record(
        key_preview="k1", label="a", tool="api_call", channel="mcp", ok=False, duration_ms=30
    )

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
