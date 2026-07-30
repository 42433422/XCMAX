"""订单域「1 条样板闭环」单测：AppService 成功 → emit → handler 副作用可断言。

不宣称订单域全域已落地；仅覆盖 create_order / order.created 样板路径。
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.application import order_app_service as oas
from app.neuro_bus import event_store as event_store_mod
from app.neuro_bus.domains import order_domain as od
from app.neuro_bus.domains import order_domain_handlers as odh
from app.neuro_bus.event_store import EventStore
from app.neuro_bus.events.base import NeuroEvent


@pytest.fixture(autouse=True)
def _isolate_sample_state(monkeypatch: pytest.MonkeyPatch):
    oas.clear_sample_orders()
    odh.clear_order_created_side_effects()
    monkeypatch.setattr(event_store_mod, "_event_store_instance", EventStore())
    monkeypatch.setattr(od, "_order_domain", None)
    yield
    oas.clear_sample_orders()
    odh.clear_order_created_side_effects()


def test_create_order_emits_and_handler_side_effect_is_queryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """服务成功 → emit 被调 → handler 副作用（EventStore + 投影）可断言。"""
    emit_calls: list[dict] = []

    domain = MagicMock()

    def _fake_emit_order_created(
        order_id: str,
        customer_id: str,
        items: list,
        total_amount: Decimal,
    ) -> bool:
        emit_calls.append(
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "items": items,
                "total_amount": total_amount,
            }
        )
        event = NeuroEvent(
            event_type="order.created",
            payload={
                "order_id": order_id,
                "customer_id": customer_id,
                "items": items,
                "total_amount": str(total_amount),
                "item_count": len(items),
            },
            source="order",
        )
        event.with_domain("order")
        # 模拟 bus 投递到样板 handler 的副作用路径
        odh.apply_order_created_side_effect(event)
        return True

    domain.emit_order_created.side_effect = _fake_emit_order_created
    monkeypatch.setattr(
        "app.neuro_bus.domains.order_domain.get_order_domain",
        lambda: domain,
    )

    svc = oas.OrderAppService()
    result = svc.create_order(
        customer_id="cust-sample-1",
        items=[{"product_id": "p1", "quantity": 2, "unit_price": "10.5"}],
    )

    assert result["success"] is True
    order_id = result["order_id"]
    assert order_id
    assert oas.get_sample_order(order_id) is not None

    assert len(emit_calls) == 1
    assert emit_calls[0]["order_id"] == order_id
    assert emit_calls[0]["customer_id"] == "cust-sample-1"
    assert emit_calls[0]["total_amount"] == Decimal("21.0")
    domain.emit_order_created.assert_called_once()

    projection = odh.get_order_created_projection(order_id)
    assert projection is not None
    assert projection["status"] == "projected"
    assert projection["stream_id"] == f"order:{order_id}"
    assert projection["store_id"]

    log = odh.get_order_created_event_log()
    assert len(log) == 1
    assert log[0]["order_id"] == order_id

    stored = event_store_mod.get_event_store().get_stream_events(f"order:{order_id}")
    assert len(stored) == 1
    assert stored[0].event.event_type == "order.created"
    assert stored[0].event.payload["order_id"] == order_id


@pytest.mark.asyncio
async def test_registered_order_created_handler_applies_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注册到 domain 的 order.created handler 会跑真实副作用。"""
    bus = MagicMock()
    domain = od.OrderNeuroDomain(bus=bus)
    # handlers 已在 __init__ 注册到 domain._handlers
    created_handlers = [h for h in domain._handlers if h.event_type == "order.created"]
    assert created_handlers

    event = NeuroEvent(
        event_type="order.created",
        payload={
            "order_id": "ord-handler-1",
            "customer_id": "c-2",
            "items": [],
            "total_amount": "0",
            "item_count": 0,
        },
        source="order",
    )
    await created_handlers[0].handler(event)

    assert odh.get_order_created_projection("ord-handler-1") is not None
    stored = event_store_mod.get_event_store().get_stream_events("order:ord-handler-1")
    assert len(stored) == 1


def test_create_order_rejects_empty_customer() -> None:
    result = oas.OrderAppService().create_order(customer_id="  ")
    assert result["success"] is False
    assert not odh.get_order_created_event_log()
