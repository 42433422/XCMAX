"""Redis Streams bridge regression including owner-fenced ACK and safe trim."""

from unittest.mock import MagicMock

from redis.exceptions import ResponseError

from app.neuro_bus.transports.redis_streams import (
    CONSUMER_GROUP,
    DLQ_KEY,
    MAXLEN,
    STREAM_KEY,
    TRIM_BATCH,
    RedisStreamsBridge,
    _ACK,
    _DEAD_LETTER,
    _SAFE_TRIM,
)


def test_publish_xadd_never_blindly_trims_pending_work():
    client = MagicMock()
    client.xadd.return_value = b"1234567890-0"
    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=client)
    assert bridge.publish({"event_type": "test", "payload": {}}) == "1234567890-0"
    args, kwargs = client.xadd.call_args
    assert args[0] == STREAM_KEY
    assert "payload" in kwargs["fields"]
    assert "maxlen" not in kwargs
    assert "approximate" not in kwargs


def test_consume_reads_group_but_never_auto_acks():
    client = MagicMock()
    client.xreadgroup.return_value = [
        (STREAM_KEY.encode(), [(b"1234567890-0", {b"payload": b'{"event_type":"test"}'})])
    ]
    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=client)
    messages = bridge.consume(count=10, block_ms=1000)
    assert len(messages) == 1
    assert messages[0]["_msg_id"] == "1234567890-0"
    client.xreadgroup.assert_called_once()
    client.xack.assert_not_called()
    client.eval.assert_not_called()


def test_stale_owner_cannot_ack_or_trigger_trimming():
    client = MagicMock()
    client.eval.return_value = 0
    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=client, consumer_id="old")
    assert not bridge.ack("1-0")
    client.eval.assert_called_once_with(_ACK, 1, STREAM_KEY, CONSUMER_GROUP, "1-0", "old")
    client.xack.assert_not_called()
    client.xtrim.assert_not_called()


def test_successful_fenced_ack_trims_fail_closed():
    client = MagicMock()
    client.eval.side_effect = [1, ResponseError("NOPERM")]
    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=client, consumer_id="owner")
    assert bridge.ack("1-0")
    assert client.eval.call_count == 2
    client.eval.assert_any_call(_ACK, 1, STREAM_KEY, CONSUMER_GROUP, "1-0", "owner")
    client.eval.assert_any_call(_SAFE_TRIM, 1, STREAM_KEY, MAXLEN, TRIM_BATCH)
    client.xack.assert_not_called()
    client.xtrim.assert_not_called()
    client.xdel.assert_not_called()


def test_dead_letter_and_ack_remain_atomically_owner_fenced():
    client = MagicMock()
    client.eval.side_effect = [1, 0]
    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=client, consumer_id="owner")
    assert bridge.send_to_dlq({"reason": "invalid"}, "1-0")
    args, _ = client.eval.call_args_list[0]
    assert args[:6] == (_DEAD_LETTER, 2, STREAM_KEY, DLQ_KEY, CONSUMER_GROUP, "1-0")
    assert args[6] == "owner"
    client.eval.assert_any_call(_SAFE_TRIM, 1, STREAM_KEY, MAXLEN, TRIM_BATCH)
    client.xadd.assert_not_called()
    client.xack.assert_not_called()


def test_failed_dead_letter_does_not_trigger_trim_or_ack():
    client = MagicMock()
    client.eval.return_value = 0
    bridge = RedisStreamsBridge(bus=MagicMock(), redis_client=client, consumer_id="stale")
    assert not bridge.send_to_dlq({"reason": "poison"}, "1-0")
    assert client.eval.call_count == 1
    client.xack.assert_not_called()
