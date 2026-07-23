from __future__ import annotations

import sys
from types import SimpleNamespace

from modstore_server.eventing.events import new_event
from modstore_server.eventing.rabbitmq_bus import RabbitMqNeuroBus


def test_connected_rabbitmq_bus_publishes_with_runtime_pika_import(monkeypatch) -> None:
    published: dict = {}

    class Channel:
        def basic_publish(self, **kwargs) -> None:
            published.update(kwargs)

    monkeypatch.setattr(RabbitMqNeuroBus, "_connect_and_setup", lambda self: None)
    monkeypatch.setitem(
        sys.modules,
        "pika",
        SimpleNamespace(BasicProperties=lambda **kwargs: {"properties": kwargs}),
    )
    bus = RabbitMqNeuroBus()
    bus._channel = Channel()
    bus._connected = True
    event = new_event(
        "autonomy.proof.recorded",
        producer="test-suite",
        subject_id="receipt-1",
    )

    assert bus.publish(event) is True
    assert published["exchange"] == "modstore.events"
    assert published["routing_key"] == event.event_name
    assert published["properties"]["properties"]["delivery_mode"] == 2
    assert published["properties"]["properties"]["message_id"] == event.event_id
