"""COVERAGE_RAMP P1：基础设施与工具路径冒烟。"""

from __future__ import annotations

import tempfile

import pytest

from app.utils import rate_limiter as rate_limiter_mod


@pytest.fixture(autouse=True)
def _reset_rate_limiter_redis_state(monkeypatch: pytest.MonkeyPatch):
    """避免前序用例初始化 Redis 后端导致本用例连 localhost:6379。"""
    monkeypatch.delenv("CACHE_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("XCAGI_REDIS_URL", raising=False)
    rate_limiter_mod._redis_client = None
    rate_limiter_mod._redis_init_attempted = False
    rate_limiter_mod._rate_limiters.clear()
    rate_limiter_mod._circuit_breakers.clear()
    yield
    rate_limiter_mod._redis_client = None
    rate_limiter_mod._redis_init_attempted = False
    rate_limiter_mod._rate_limiters.clear()
    rate_limiter_mod._circuit_breakers.clear()


def test_filesystem_template_store_legacy_list():
    from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore

    with tempfile.TemporaryDirectory() as tmp:
        store = FileSystemTemplateStore(tmp)
        legacy = store._legacy_templates()
        assert isinstance(legacy, list)
        assert len(legacy) >= 2
        assert legacy[0]["id"] == "shipment"


def test_password_hash_roundtrip():
    from app.utils.password_hash import check_password_hash, generate_password_hash

    hashed = generate_password_hash("secret-pass")
    assert check_password_hash(hashed, "secret-pass")
    assert not check_password_hash(hashed, "wrong")


def test_rate_limiter_memory_backend():
    from app.utils.rate_limiter import check_rate_limit

    r1 = check_rate_limit("u1", "ep-test-mem", max_requests=2, window_seconds=60)
    assert r1["allowed"] is True
    r2 = check_rate_limit("u1", "ep-test-mem", max_requests=2, window_seconds=60)
    assert r2["allowed"] is True
    r3 = check_rate_limit("u1", "ep-test-mem", max_requests=2, window_seconds=60)
    assert r3["allowed"] is False
