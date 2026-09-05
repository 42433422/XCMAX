"""Catalog fan-out must not exhaust the pool or block unrelated requests."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from modstore_server import llm_api, llm_catalog, llm_key_resolver, models
from modstore_server.db.llm_chat import UserLlmCredential


@pytest.fixture
def small_pool(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'catalog.sqlite'}",
        connect_args={"check_same_thread": False},
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    UserLlmCredential.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(models, "get_session_factory", lambda: factory)
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: None)
    monkeypatch.setattr(llm_catalog, "_cache", {})
    monkeypatch.setattr(llm_api, "_CATALOG_PROVIDER_TIMEOUT_SEC", 3)
    yield engine
    assert engine.pool.checkedout() == 0
    engine.dispose()


@pytest.mark.asyncio
async def test_unconfigured_catalog_fanout_releases_each_real_connection(small_pool):
    providers = llm_key_resolver.KNOWN_PROVIDERS[:8]
    blocks = await asyncio.wait_for(
        asyncio.gather(
            *[
                llm_api._fetch_catalog_provider_block(41, provider, force_refresh=False)
                for provider in providers
            ]
        ),
        timeout=2,
    )
    assert [block["provider"] for block in blocks] == list(providers)
    assert all(block["error"] == "no_api_key" for block in blocks)
    assert all(block["fetch_source"] == "fallback_only" for block in blocks)


@pytest.mark.asyncio
async def test_remote_catalog_waits_leave_pool_available_for_wallet(small_pool, monkeypatch):
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: "local-test-key")
    started, release = asyncio.Event(), asyncio.Event()
    arrivals = []

    async def remote(_base, _key, **_kwargs):
        arrivals.append(1)
        if len(arrivals) == 6:
            started.set()
        await release.wait()
        return [], None

    monkeypatch.setattr(llm_catalog, "_fetch_openai_compatible_records", remote)
    tasks = [
        asyncio.create_task(
            llm_api._fetch_catalog_provider_block(41, "openai", force_refresh=False)
        )
        for _ in range(6)
    ]
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert small_pool.pool.checkedout() == 0
        with small_pool.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert len(arrivals) == 6
    assert all(isinstance(result, dict) and result["provider"] == "openai" for result in results)


@pytest.mark.asyncio
async def test_cancelled_catalog_does_not_retain_credential_connection(small_pool, monkeypatch):
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: "local-test-key")
    started = asyncio.Event()

    async def remote(_base, _key, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(llm_catalog, "_fetch_openai_compatible_records", remote)
    task = asyncio.create_task(
        llm_api._fetch_catalog_provider_block(41, "openai", force_refresh=False)
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert small_pool.pool.checkedout() == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    with small_pool.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
