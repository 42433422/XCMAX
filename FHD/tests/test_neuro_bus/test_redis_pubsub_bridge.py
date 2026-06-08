"""NeuroBus Redis Pub/Sub 桥单元测试（无真实 Redis）。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.transports.redis_pubsub import CHANNEL, RedisPubSubBridge


@pytest.fixture
def bus_mock():
    bus = MagicMock()
    bus.ingest_remote_event = MagicMock(return_value=True)
    return bus


def test_publish_remote_skips_local_only(bus_mock):
    bridge = RedisPubSubBridge(bus_mock)
    bridge._redis = MagicMock()
    bridge._instance_id = "inst-a"

    event = NeuroEvent("test.event", {"local_only": True, "x": 1})
    bridge.publish_remote(event)
    bridge._redis.publish.assert_not_called()


def test_publish_remote_broadcasts(bus_mock):
    bridge = RedisPubSubBridge(bus_mock)
    bridge._redis = MagicMock()
    bridge._instance_id = "inst-a"

    event = NeuroEvent("test.event", {"x": 1})
    bridge.publish_remote(event)

    bridge._redis.publish.assert_called_once()
    channel, payload = bridge._redis.publish.call_args[0]
    assert channel == CHANNEL
    envelope = json.loads(payload)
    assert envelope["origin"] == "inst-a"
    assert envelope["event"]["event_type"] == "test.event"


def test_handle_message_ignores_self_origin(bus_mock):
    bridge = RedisPubSubBridge(bus_mock)
    bridge._instance_id = "inst-a"
    envelope = {"origin": "inst-a", "event": NeuroEvent("e", {}).to_dict()}
    bridge._handle_message(json.dumps(envelope))
    bus_mock.ingest_remote_event.assert_not_called()


def test_handle_message_ingests_foreign(bus_mock):
    bridge = RedisPubSubBridge(bus_mock)
    bridge._instance_id = "inst-a"
    event = NeuroEvent("remote.event", {"k": "v"})
    envelope = {"origin": "inst-b", "event": event.to_dict()}
    bridge._handle_message(json.dumps(envelope))
    bus_mock.ingest_remote_event.assert_called_once()
    ingested = bus_mock.ingest_remote_event.call_args[0][0]
    assert ingested.event_type == "remote.event"
    assert ingested.payload.get("_neuro_remote_ingest") is True


def test_redis_pubsub_enabled_env():
    with patch.dict("os.environ", {"XCAGI_NEURO_BUS_REDIS_PUBSUB": "1"}):
        from app.neuro_bus.transports.redis_pubsub import redis_pubsub_enabled

        assert redis_pubsub_enabled() is True
