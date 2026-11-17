"""回放缓冲的归属隔离、生产权租约与游标连续性。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.application import chat_stream_replay as replay
from app.infrastructure.auth.agent_principal import AgentPrincipal
from app.legacy.routes.conversation import compat_routes
from app.utils.performance import redis_cache as rc_mod
from app.utils.performance.redis_cache import RedisCache


class _FakeRedis:
    """覆盖回放路径用到的最小 Redis 子集（含 redis-py Lock 依赖的命令）。"""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.available = True
        self._seq = 0

    def ping(self) -> bool:
        if not self.available:
            raise ConnectionError("redis down")
        return True

    def set(self, key, value, ex=None, px=None, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def pexpire(self, key, ms: int) -> bool:
        return key in self.values or key in self.streams

    def expire(self, key, seconds: int) -> bool:
        return self.pexpire(key, seconds * 1000)

    def exists(self, *keys: str) -> int:
        return sum(1 for key in keys if key in self.values or key in self.streams)

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(self.values.pop(key, None) is not None)
            removed += int(self.streams.pop(key, None) is not None)
        return removed

    def get_encoder(self):
        class _Encoder:
            @staticmethod
            def encode(value):
                return value.encode() if isinstance(value, str) else value

        return _Encoder()

    def register_script(self, script):
        return _FakeScript(self, script)

    def xadd(self, key, fields, maxlen=None, approximate=False):
        self._seq += 1
        entry_id = f"{1_700_000_000_000 + self._seq}-0"
        self.streams.setdefault(key, []).append((entry_id, dict(fields)))
        if maxlen:
            self.streams[key] = self.streams[key][-maxlen:]
        return entry_id

    def xrange(self, key, min="-", max="+"):
        rows = self.streams.get(key) or []
        if min in ("-", None):
            return list(rows)
        for index, (entry_id, _fields) in enumerate(rows):
            if entry_id == min:
                return list(rows[index:])
        return []


class _FakeScript:
    """替代 redis-py Script：只实现 Lock 用到的 release/reacquire 语义。"""

    def __init__(self, client: _FakeRedis, script: str) -> None:
        self._client = client
        self._script = script

    def __call__(self, keys=None, args=None, client=None):
        key = (keys or [None])[0]
        token = (args or [None])[0]
        if "del" in self._script:
            if self._client.values.get(key) == token:
                del self._client.values[key]
                return 1
            return 0
        return 1 if self._client.values.get(key) == token else 0


@pytest.fixture(autouse=True)
def _isolated_backend(monkeypatch):
    from redis.lock import Lock

    previous = rc_mod._redis_cache_instance
    previous_scripts = (Lock.lua_release, Lock.lua_extend, Lock.lua_reacquire)
    Lock.lua_release = Lock.lua_extend = Lock.lua_reacquire = None
    rc_mod._redis_cache_instance = None
    for name in ("CACHE_REDIS_URL", "REDIS_URL", "XCAGI_REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    _reset_local()
    yield
    _reset_local()
    Lock.lua_release, Lock.lua_extend, Lock.lua_reacquire = previous_scripts
    rc_mod._redis_cache_instance = previous


def _reset_local() -> None:
    replay._events.clear()
    replay._status.clear()
    replay._running.clear()
    replay._touched.clear()
    replay._leases.clear()


def _use_redis(fake: _FakeRedis) -> None:
    rc_mod._redis_cache_instance = RedisCache(fake)


def test_local_replay_is_scoped_by_owner_and_tenant():
    replay.append("turn-1", {"type": "token", "text": "a"}, owner="7", tenant="2")

    assert replay.events_after("turn-1", 0, owner="7", tenant="2")
    assert replay.events_after("turn-1", 0, owner="8", tenant="2") == []
    assert replay.events_after("turn-1", 0, owner="7", tenant="3") == []
    assert replay.has_replay("turn-1", owner="8", tenant="2") is False


def test_local_claim_allows_only_one_producer():
    assert replay.claim_runner("turn-2", owner="7", tenant="2") is True
    assert replay.claim_runner("turn-2", owner="7", tenant="2") is False
    # 其它主体在各自命名空间内不共享生产权。
    assert replay.claim_runner("turn-2", owner="8", tenant="2") is True

    replay.release_runner("turn-2", owner="7", tenant="2")
    assert replay.claim_runner("turn-2", owner="7", tenant="2") is True


def test_local_cursor_only_returns_newer_events():
    first = replay.append("turn-3", {"type": "token", "text": "a"}, owner="7")
    replay.append("turn-3", {"type": "token", "text": "b"}, owner="7")

    rows = replay.events_after("turn-3", first, owner="7")
    assert [row["payload"]["text"] for row in rows] == ["b"]


def test_local_finish_status_and_lease_liveness():
    replay.claim_runner("turn-4", owner="7")
    assert replay.lease_alive("turn-4", owner="7") is True
    assert replay.finish_status("turn-4", owner="7") is None

    replay.mark_finished("turn-4", "done", owner="7")
    assert replay.finish_status("turn-4", owner="7") == "done"
    assert replay.lease_alive("turn-4", owner="7") is False


def test_redis_stream_uses_entry_id_as_monotonic_cursor():
    fake = _FakeRedis()
    _use_redis(fake)

    first = replay.append("turn-5", {"type": "token", "text": "a"}, owner="7", tenant="2")
    replay.append("turn-5", {"type": "token", "text": "b"}, owner="7", tenant="2")

    rows = replay.events_after("turn-5", first, owner="7", tenant="2")
    assert [row["payload"]["text"] for row in rows] == ["b"]
    assert rows[0]["seq"] > first


def test_redis_claim_is_a_cross_process_lease():
    fake = _FakeRedis()
    _use_redis(fake)

    assert replay.claim_runner("turn-6", owner="7", tenant="2") is True
    # 另一个 worker 看到的是同一把 Redis 锁，不能重复生产。
    assert replay.claim_runner("turn-6", owner="7", tenant="2") is False

    replay.mark_finished("turn-6", "done", owner="7", tenant="2")
    assert replay.finish_status("turn-6", owner="7", tenant="2") == "done"
    assert replay.lease_alive("turn-6", owner="7", tenant="2") is False
    # 上一轮结束后才允许重试抢占。
    assert replay.claim_runner("turn-6", owner="7", tenant="2") is True


def test_redis_replay_does_not_leak_across_owners():
    fake = _FakeRedis()
    _use_redis(fake)

    replay.append("turn-7", {"type": "token", "text": "secret"}, owner="7", tenant="2")

    assert replay.events_after("turn-7", 0, owner="8", tenant="2") == []
    assert replay.has_replay("turn-7", owner="8", tenant="2") is False


def test_redis_outage_fails_loudly_instead_of_falling_back_to_process_memory():
    fake = _FakeRedis()
    fake.available = False
    _use_redis(fake)

    with pytest.raises(replay.ReplayBackendUnavailable):
        replay.append("turn-8", {"type": "token"}, owner="7")
    with pytest.raises(replay.ReplayBackendUnavailable):
        replay.events_after("turn-8", 0, owner="7")
    with pytest.raises(replay.ReplayBackendUnavailable):
        replay.claim_runner("turn-8", owner="7")


def test_follower_can_detect_a_dead_producer_after_lease_loss():
    fake = _FakeRedis()
    _use_redis(fake)

    replay.claim_runner("turn-9", owner="7", tenant="2")
    # 模拟生产进程被强杀：租约到期后从 Redis 消失，且没有终态。
    fake.values.clear()

    assert replay.finish_status("turn-9", owner="7", tenant="2") is None
    assert replay.lease_alive("turn-9", owner="7", tenant="2") is False


def _http_request(headers: dict[str, str] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/ai/chat/stream/resume",
            "headers": [
                (name.lower().encode(), value.encode())
                for name, value in (headers or {}).items()
            ],
        }
    )


async def test_resume_endpoint_rejects_anonymous_callers():
    with pytest.raises(HTTPException) as exc_info:
        await compat_routes.ai_chat_stream_resume(
            _http_request(), turn_id="turn-1", after="0"
        )

    assert exc_info.value.status_code == 401


async def test_resume_endpoint_hides_another_owners_turn(monkeypatch):
    replay.append("turn-10", {"type": "token", "text": "secret"}, owner="7", tenant="2")
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_principal.require_agent_principal",
        lambda request, x_user_id=None: AgentPrincipal(user_id="8", tenant_id="2"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await compat_routes.ai_chat_stream_resume(
            _http_request(), turn_id="turn-10", after="0"
        )

    assert exc_info.value.status_code == 404

