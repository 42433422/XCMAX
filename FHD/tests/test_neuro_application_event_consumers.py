"""核心 app service NeuroBus「真实落地」验证。

证明三个先前「只发布、无消费」的服务事件，现在被消费者消费并产生**持久副作用**
（``neuro_event_log`` 落库）—— 即 produce → consume → durable side-effect 在默认路径成立。

DB 后端无关：测试将 ``app.db.SessionLocal`` 指向临时 SQLite（消费者在调用时才 import 该名字），
聚焦于「事件被消费并写下一条可查询的持久记录」这一行为本身。
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.neuro_bus.bus import NeuroBus, get_neuro_bus
from app.neuro_bus.domains.application_event_consumers import (
    register_application_event_consumers,
)
from app.neuro_bus.events.base import EventMetadata, NeuroEvent


@pytest.fixture
def sqlite_sessionlocal(monkeypatch, tmp_path):
    """将 app.db.SessionLocal 指向独立临时 SQLite，并建好 neuro_event_log 表。"""
    from app.db.models.neuro_event_log import NeuroEventLog

    engine = create_engine(f"sqlite:///{tmp_path / 'neuro_test.db'}")
    NeuroEventLog.__table__.create(bind=engine, checkfirst=True)
    test_session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.SessionLocal", test_session, raising=False)
    return test_session


def _publish_event(bus: NeuroBus, event_type: str, payload: dict, domain: str) -> None:
    meta = EventMetadata(domain=domain, source="test")
    bus.publish(NeuroEvent(event_type=event_type, payload=payload, metadata=meta))


def _rows_with_nonce(session_factory, nonce: str):
    from app.db.models.neuro_event_log import NeuroEventLog

    with session_factory() as db:
        return (
            db.query(NeuroEventLog)
            .filter(NeuroEventLog.payload.like(f"%{nonce}%"))
            .all()
        )


@pytest.mark.asyncio
async def test_three_consumers_write_durable_event_log(sqlite_sessionlocal):
    """三个核心 app service 事件各自被消费并落一条持久 neuro_event_log。"""
    bus = NeuroBus(enable_metrics=False)
    register_application_event_consumers(bus)
    await bus.start()
    try:
        nonce = uuid4().hex
        _publish_event(
            bus,
            "application.products.imported",
            {"count": 3, "customer_id": nonce, "source": "test"},
            "product",
        )
        _publish_event(
            bus,
            "application.conversation.message_saved",
            {"session_id": nonce, "user_id": "u1", "role": "user", "intent": "x"},
            "ai_service",
        )
        _publish_event(
            bus,
            "application.customer.changed",
            {"action": "created", "customer_id": nonce, "customer_name": "n", "tenant_id": "t"},
            "customer",
        )
        await asyncio.sleep(0.4)
    finally:
        await bus.stop()

    rows = _rows_with_nonce(sqlite_sessionlocal, nonce)
    got_types = {r.event_type for r in rows}
    assert got_types == {
        "application.products.imported",
        "application.conversation.message_saved",
        "application.customer.changed",
    }, f"missing durable rows, got: {got_types}"
    for r in rows:
        assert r.created_at is not None
        assert r.domain in {"product", "ai_service", "customer"}
        assert nonce in r.payload


@pytest.mark.asyncio
async def test_real_startup_registration_wires_consumer(sqlite_sessionlocal):
    """走真实启动注册编排（register_domain_handlers_for_runtime，本环境为 handlers-via-mod 目录驱动），
    证明消费者经生产注册路径挂载到总线并产生持久副作用——而非仅靠测试内手工 subscribe。"""
    from app.mod_sdk.neuro_bus_handler_registry import (
        is_neuro_bus_handlers_via_mod_enabled,
        register_domain_handlers_for_runtime,
    )

    bus = NeuroBus(enable_metrics=False)
    await bus.start()
    try:
        result = await register_domain_handlers_for_runtime(bus)
        # 经生产注册编排后，application.products.imported 必须有消费者订阅
        assert "application.products.imported" in getattr(bus, "_handlers", {}), (
            f"consumer not wired via real registration path "
            f"(handlers_via_mod={is_neuro_bus_handlers_via_mod_enabled()}, result={result})"
        )

        nonce = uuid4().hex
        _publish_event(
            bus,
            "application.products.imported",
            {"count": 1, "customer_id": nonce, "source": "startup-path"},
            "product",
        )
        await asyncio.sleep(0.4)
    finally:
        await bus.stop()

    rows = _rows_with_nonce(sqlite_sessionlocal, nonce)
    assert any(
        r.event_type == "application.products.imported" for r in rows
    ), "real startup registration path did not deliver event to durable consumer"
