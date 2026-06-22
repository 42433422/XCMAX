# FHD/tests/test_neuro_bus/test_redis_streams.py
"""Redis Streams Bridge 测试。"""

import json
from unittest.mock import MagicMock, patch

import pytest


def test_streams_bridge_publish_calls_xadd(monkeypatch):
    """publish 调用 XADD。"""
    mock_redis = MagicMock()
    mock_redis.xadd.return_value = b"1234567890-0"

    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=mock_redis)
    event_dict = {"event_type": "test.event", "data": "hello"}
    bridge.publish(event_dict)

    mock_redis.xadd.assert_called_once()
    args, kwargs = mock_redis.xadd.call_args
    assert args[0] == "neurobus:events"
    assert "payload" in kwargs["fields"]
    assert kwargs["maxlen"] == 100000


def test_streams_bridge_consume_calls_xreadgroup(monkeypatch):
    """consume 调用 XREADGROUP。"""
    mock_redis = MagicMock()
    mock_redis.xreadgroup.return_value = [
        (b"neurobus:events", [(b"1234567890-0", {b"payload": b'{"event_type":"test"}'})])
    ]

    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=mock_redis)
    messages = bridge.consume(count=10, block_ms=1000)

    mock_redis.xreadgroup.assert_called_once()
    assert len(messages) == 1
    assert messages[0]["event_type"] == "test"


def test_streams_bridge_ack_calls_xack():
    """ack 调用 XACK。"""
    mock_redis = MagicMock()
    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=mock_redis)
    bridge.ack("1234567890-0")

    mock_redis.xack.assert_called_once_with("neurobus:events", "neurobus-workers", "1234567890-0")


def test_streams_bridge_send_to_dlq():
    """失败消息转入 DLQ stream。"""
    mock_redis = MagicMock()
    from app.neuro_bus.transports.redis_streams import RedisStreamsBridge

    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=mock_redis)
    bridge.send_to_dlq({"event_type": "failed"}, "1234567890-0")

    mock_redis.xadd.assert_called_once()
    args, kwargs = mock_redis.xadd.call_args
    assert args[0] == "neurobus:dlq"
    mock_redis.xack.assert_called_once()
