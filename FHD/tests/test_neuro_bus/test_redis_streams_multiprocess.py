"""审计 R12（2026-09-05 报告）：事件总线多进程投递、持久化及恢复验收。

现有 Redis Streams 测试全部 mock redis 客户端；本文件用真实 Redis
（subprocess 起独立 redis-server，端口固定 5490 不可用时跳过）验证：

1. 多进程投递：两个独立子进程各自持有 bridge 实例，一个 XADD、
   另一个消费组内的 worker 读取，事件跨进程送达且负载字节一致；
2. 持久化：publish 后进程退出，消息仍在 stream 中（重启后读取成功）；
3. 恢复：消费失败未 ACK 的 pending 消息可被同组另一 worker 用
   XAUTOCLAIM/PEL 读取路径恢复（此处以 xreadgroup 未 ack → 新实例
   从 '0' 读取 pending 验证）；
4. DLQ：失败消息转 DLQ 并 ACK 原消息，DLQ 可独立读取。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid

import pytest

redis_cli = shutil.which("redis-cli")
redis_server = shutil.which("redis-server")

import redis as redis_lib

from app.neuro_bus.transports.redis_streams import (
    CONSUMER_GROUP,
    DLQ_KEY,
    STREAM_KEY,
    RedisStreamsBridge,
)

_PORT = 5490


@pytest.fixture(scope="module")
def redis_url():
    url = f"redis://127.0.0.1:{_PORT}/0"
    # 优先复用已运行的 Redis（如 docker 容器）；否则尝试本机 redis-server。
    try:
        probe = redis_lib.Redis.from_url(url, socket_connect_timeout=1)
        probe.ping()
        probe.close()
        yield url
        return
    except redis_lib.RedisError:
        pass

    server = None
    if redis_server:
        server = subprocess.Popen(
            [redis_server, "--port", str(_PORT), "--save", "", "--appendonly", "no"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            try:
                if (
                    redis_cli
                    and subprocess.run(
                        [redis_cli, "-p", str(_PORT), "ping"],
                        capture_output=True,
                        timeout=2,
                    ).returncode
                    == 0
                ):
                    break
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(0.1)
        else:
            server.terminate()
            pytest.skip("redis-server 无法在本机启动")
    else:
        pytest.skip("无可用 Redis（端口 5490 未监听且 redis-server 未安装）")
    try:
        yield url
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=5)


def _client(url):
    return redis_lib.Redis.from_url(url, decode_responses=False)


def _fresh_stream(client):
    client.delete(STREAM_KEY, DLQ_KEY)


class _FakeBus:
    def publish(self, *a, **k):  # pragma: no cover - bridge 不回调 bus
        raise AssertionError("bridge must not loop back into bus")


def test_cross_process_publish_and_consume(redis_url) -> None:
    """投递进程与消费进程分离：子进程 publish，主进程组内消费。"""
    client = _client(redis_url)
    _fresh_stream(client)
    event = {"event_id": str(uuid.uuid4()), "type": "order.created", "payload": {"order": 42}}

    code = (
        "import redis, json, sys\n"
        "from app.neuro_bus.transports.redis_streams import RedisStreamsBridge\n"
        f"c = redis.Redis.from_url({redis_url!r})\n"
        "b = RedisStreamsBridge(bus=None, redis_client=c, consumer_id='publisher-proc')\n"
        f"b.publish(json.loads(sys.argv[1]))\n"
    )
    import os
    import sys
    from pathlib import Path

    proc = subprocess.run(
        [sys.executable, "-c", code, json.dumps(event)],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": "."},
    )
    assert proc.returncode == 0, proc.stderr
    assert client.xlen(STREAM_KEY) == 1

    bridge = RedisStreamsBridge(bus=_FakeBus(), redis_client=client, consumer_id="worker-main")
    messages = bridge.consume(count=10, block_ms=1000)
    assert len(messages) == 1
    assert messages[0]["event_id"] == event["event_id"]
    assert messages[0]["payload"] == {"order": 42}
    bridge.ack(messages[0]["_msg_id"])
    client.close()


def test_persistence_survives_process_restart(redis_url) -> None:
    """publish 后「进程退出」，消息持久在 stream 中可被新实例消费。"""
    client = _client(redis_url)
    _fresh_stream(client)
    event = {"event_id": str(uuid.uuid4()), "type": "persist.probe", "payload": {"n": 1}}
    publisher = RedisStreamsBridge(bus=None, redis_client=client, consumer_id="proc-a")
    publisher.publish(event)
    publisher._redis = None  # 模拟发布进程销毁

    # 新连接（等价进程重启后重建客户端）
    restarted = _client(redis_url)
    bridge = RedisStreamsBridge(bus=_FakeBus(), redis_client=restarted, consumer_id="proc-b")
    messages = bridge.consume(count=10, block_ms=1000)
    assert [m["event_id"] for m in messages] == [event["event_id"]]
    bridge.ack(messages[0]["_msg_id"])
    client.close()
    restarted.close()


def test_unacked_pending_message_recovered_by_new_consumer(redis_url) -> None:
    """消费失败未 ACK 的消息留在 PEL，新实例从 '0' 恢复读取（崩溃恢复路径）。"""
    client = _client(redis_url)
    _fresh_stream(client)
    event = {"event_id": str(uuid.uuid4()), "type": "crash.recover", "payload": {"k": "v"}}
    publisher = RedisStreamsBridge(bus=None, redis_client=client, consumer_id="pub")
    publisher.publish(event)

    crashed = RedisStreamsBridge(bus=None, redis_client=client, consumer_id="worker-crashed")
    pending = crashed.consume(count=10, block_ms=1000)
    assert len(pending) == 1
    # 模拟 worker 崩溃：不 ack

    # 恢复：同组新 worker 直接读 PEL（xreadgroup '0'）
    entries = client.xreadgroup(CONSUMER_GROUP, "worker-crashed", {STREAM_KEY: "0"}, count=10)
    recovered_ids = [mid.decode() for _s, msgs in entries for mid, _f in msgs]
    assert recovered_ids == [pending[0]["_msg_id"]]
    client.xack(STREAM_KEY, CONSUMER_GROUP, *recovered_ids)
    client.close()


def test_failed_message_routed_to_dlq(redis_url) -> None:
    """失败消息转 DLQ 并 ACK 原消息，DLQ 独立可读。"""
    client = _client(redis_url)
    _fresh_stream(client)
    event = {"event_id": str(uuid.uuid4()), "type": "bad.payload", "payload": {}}
    bridge = RedisStreamsBridge(bus=None, redis_client=client, consumer_id="worker-dlq")
    msg_id = bridge.publish(event)
    assert msg_id is not None
    bridge.send_to_dlq(event, msg_id)

    assert client.xlen(DLQ_KEY) == 1
    dlq_entries = client.xrange(DLQ_KEY)
    payload = json.loads(dlq_entries[0][1][b"payload"].decode())
    assert payload["event_id"] == event["event_id"]
    assert dlq_entries[0][1][b"original_id"].decode() == msg_id
    # 原消息已 ACK：PEL 中不再存在
    pending = client.xpending(STREAM_KEY, CONSUMER_GROUP)
    assert pending["pending"] == 0
    client.close()


def test_safe_trim_preserves_slowest_group_and_pending_payload(redis_url, monkeypatch):
    from app.neuro_bus.transports import redis_streams as streams

    monkeypatch.setattr(streams, "MAXLEN", 3)
    client = _client(redis_url)
    try:
        _fresh_stream(client)
        bridge = RedisStreamsBridge(bus=None, redis_client=client, consumer_id="fast")
        client.xgroup_create(STREAM_KEY, "slow", id="0-0")
        ids = [bridge.publish({"n": i}) for i in range(12)]
        assert client.xlen(STREAM_KEY) == 12

        received = bridge.consume(count=12, block_ms=1000)
        assert [m["_msg_id"] for m in received] == ids
        for msg_id in ids[1:]:
            bridge.ack(msg_id)
        # Unread group plus oldest unacknowledged fast worker block trimming.
        assert client.xlen(STREAM_KEY) == 12

        client.xreadgroup("slow", "crashed", {STREAM_KEY: ">"}, count=5)
        client.xack(STREAM_KEY, "slow", *ids[:4])
        assert bridge.trim_acknowledged() == 0
        bridge.ack(ids[0])
        assert [mid.decode() for mid, _ in client.xrange(STREAM_KEY)] == ids[4:]

        # Recover the pending message, including its original payload.
        _, claimed, *_ = client.xautoclaim(
            STREAM_KEY, "slow", "restarted", min_idle_time=0, start_id="0-0", count=10
        )
        assert len(claimed) == 1
        assert claimed[0][0].decode() == ids[4]
        assert json.loads(claimed[0][1][b"payload"]) == {"n": 4}
        client.xack(STREAM_KEY, "slow", ids[4])
        client.xreadgroup("slow", "restarted", {STREAM_KEY: ">"}, count=12)
        client.xack(STREAM_KEY, "slow", *ids[5:])
        assert bridge.trim_acknowledged() == 5
        assert [mid.decode() for mid, _ in client.xrange(STREAM_KEY)] == ids[-3:]
    finally:
        _fresh_stream(client)
        client.close()


def test_safe_trim_retains_without_group_and_bounds_each_batch(redis_url, monkeypatch):
    from app.neuro_bus.transports import redis_streams as streams

    monkeypatch.setattr(streams, "MAXLEN", 1)
    monkeypatch.setattr(streams, "TRIM_BATCH", 2)
    client = _client(redis_url)
    try:
        _fresh_stream(client)
        bridge = RedisStreamsBridge(bus=None, redis_client=client, consumer_id="worker")
        ids = [bridge.publish({"n": i}) for i in range(7)]
        client.xgroup_destroy(STREAM_KEY, CONSUMER_GROUP)
        assert bridge.trim_acknowledged() == 0
        assert client.xlen(STREAM_KEY) == 7

        client.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0-0")
        assert bridge.trim_acknowledged() == 0
        bridge.consume(count=7, block_ms=1000)
        client.xack(STREAM_KEY, CONSUMER_GROUP, *ids)
        for remaining in (5, 3, 1):
            assert bridge.trim_acknowledged() == 2
            assert client.xlen(STREAM_KEY) == remaining
        assert bridge.trim_acknowledged() == 0
        assert client.xrange(STREAM_KEY)[0][0].decode() == ids[-1]
    finally:
        _fresh_stream(client)
        client.close()


def test_safe_trim_compares_full_uint64_stream_ids(redis_url, monkeypatch):
    from app.neuro_bus.transports import redis_streams as streams

    monkeypatch.setattr(streams, "MAXLEN", 1)
    client = _client(redis_url)
    try:
        _fresh_stream(client)
        bridge = RedisStreamsBridge(bus=None, redis_client=client, consumer_id="worker")
        ids = ["100-9007199254740992", "100-9007199254740993", "101-0"]
        for msg_id in ids:
            client.xadd(STREAM_KEY, {"payload": "{}"}, id=msg_id)
        bridge.consume(count=3, block_ms=1000)
        bridge.ack(ids[-1])
        assert client.xlen(STREAM_KEY) == 3
        bridge.ack(ids[0])
        assert [mid.decode() for mid, _ in client.xrange(STREAM_KEY)] == ids[1:]
        bridge.ack(ids[1])
        assert [mid.decode() for mid, _ in client.xrange(STREAM_KEY)] == ids[-1:]
    finally:
        _fresh_stream(client)
        client.close()


def test_dlq_soft_limit_never_drops_unconsumed_failures(redis_url, monkeypatch):
    from app.neuro_bus.transports import redis_streams as streams

    monkeypatch.setattr(streams, "MAXLEN", 2)
    client = _client(redis_url)
    try:
        _fresh_stream(client)
        bridge = RedisStreamsBridge(bus=None, redis_client=client, consumer_id="worker")
        ids = [bridge.publish({"n": i}) for i in range(8)]
        bridge.consume(count=8, block_ms=1000)
        for i, msg_id in enumerate(ids):
            bridge.send_to_dlq({"n": i}, msg_id)
        assert [fields[b"original_id"].decode() for _, fields in client.xrange(DLQ_KEY)] == ids
        assert client.xpending(STREAM_KEY, CONSUMER_GROUP)["pending"] == 0
    finally:
        _fresh_stream(client)
        client.close()


def test_new_group_reads_preexisting_backlog_instead_of_skipping(redis_url, monkeypatch):
    from app.neuro_bus.transports import redis_streams as streams

    monkeypatch.setattr(streams, "MAXLEN", 1)
    client = _client(redis_url)
    try:
        _fresh_stream(client)
        ids = [
            client.xadd(STREAM_KEY, {"payload": json.dumps({"n": i})}).decode()
            for i in range(5)
        ]
        bridge = RedisStreamsBridge(bus=None, redis_client=client, consumer_id="new")
        assert bridge.trim_acknowledged() == 0
        messages = bridge.consume(count=5, block_ms=1000)
        assert [message["_msg_id"] for message in messages] == ids
        for msg_id in ids:
            bridge.ack(msg_id)
        assert client.xlen(STREAM_KEY) == 1
    finally:
        _fresh_stream(client)
        client.close()
