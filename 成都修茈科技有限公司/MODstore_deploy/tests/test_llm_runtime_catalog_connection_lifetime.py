"""Platform catalog network waits must release the shared database pool."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from modstore_server import llm_catalog, llm_key_resolver, llm_runtime_route, models
from modstore_server.db.llm_chat import UserLlmCredential


@pytest.fixture
def platform_small_pool(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'platform_catalog.sqlite'}",
        connect_args={"check_same_thread": False},
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    UserLlmCredential.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(models, "get_session_factory", lambda: factory)
    monkeypatch.setattr(llm_key_resolver, "KNOWN_PROVIDERS", ("openai", "deepseek"))
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: "platform-test-key")
    monkeypatch.setattr(llm_catalog, "_cache", {})
    yield engine
    assert engine.pool.checkedout() == 0
    engine.dispose()


@pytest.mark.asyncio
async def test_platform_catalog_parallel_providers_leave_wallet_connection_free(
    platform_small_pool, monkeypatch
):
    started, release = asyncio.Event(), asyncio.Event()
    arrivals = []

    async def remote(_base, _key, *, provider):
        arrivals.append(provider)
        if len(arrivals) == 2:
            started.set()
        await release.wait()
        return [], None

    monkeypatch.setattr(llm_catalog, "_fetch_openai_compatible_records", remote)
    task = asyncio.create_task(llm_runtime_route.platform_model_catalog())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert platform_small_pool.pool.checkedout() == 0
        with platform_small_pool.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        release.set()
        results = await asyncio.gather(task, return_exceptions=True)
    assert sorted(arrivals) == ["deepseek", "openai"]
    assert isinstance(results[0], dict)
    assert results[0]["configured_count"] == 2
    assert [row["provider"] for row in results[0]["providers"]] == ["openai", "deepseek"]


@pytest.mark.asyncio
async def test_cancelled_platform_catalog_has_no_checked_out_connection(
    platform_small_pool, monkeypatch
):
    started = asyncio.Event()

    async def remote(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(llm_catalog, "_fetch_openai_compatible_records", remote)
    task = asyncio.create_task(llm_runtime_route.platform_model_catalog("openai"))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert platform_small_pool.pool.checkedout() == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    with platform_small_pool.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1


@pytest.mark.asyncio
async def test_platform_catalog_remote_error_propagates_after_releasing_connection(
    platform_small_pool, monkeypatch
):
    async def remote(*_args, **_kwargs):
        assert platform_small_pool.pool.checkedout() == 0
        raise OSError("isolated upstream failure")

    monkeypatch.setattr(llm_catalog, "_fetch_openai_compatible_records", remote)
    with pytest.raises(OSError, match="isolated upstream failure"):
        await llm_runtime_route.platform_model_catalog("openai")
    with platform_small_pool.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
