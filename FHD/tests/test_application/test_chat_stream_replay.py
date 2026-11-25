"""回放缓冲的归属隔离、生产权租约与游标连续性。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from redis.exceptions import LockError
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
    """替代 redis-py Script：实现租约与回放的固定脚本语义；Lua 后端测试验证实际脚本。"""

    def __init__(self, client: _FakeRedis, script: str) -> None:
        self._client = client
        self._script = script

    def __call__(self, keys=None, args=None, client=None):
        if len(keys or []) == 3:
            stream, status, lease = keys
            token = args[0]
            if "'NX'" in self._script:
                if not self._client.set(lease, token, nx=True, px=args[1]):
                    return 0
                self._client.delete(stream, status)
                return 1
            if self._client.values.get(lease) != token:
                return None
            _, action, value, ttl, maxlen = args
            if action == "append":
                return self._client.xadd(stream, {"payload": value}, maxlen=maxlen)
            if action == "finish":
                self._client.set(status, value, ex=ttl)
            elif action == "clear":
                self._client.delete(stream, status)
            return 1
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
    for scoped in list(replay._leases):
        lease = replay._leases.pop(scoped)
        try:
            lease.release()
        except (ConnectionError, LockError):
            pass


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


@pytest.mark.parametrize("backend", ["local", "redis"])
def test_expired_cursor_must_not_replay_an_incomplete_suffix(monkeypatch, backend):
    monkeypatch.setattr(replay, "REPLAY_MAX_EVENTS", 2)
    if backend == "redis":
        _use_redis(_FakeRedis())
    assert replay.claim_runner("gap", owner="7", tenant="2")
    first = replay.append("gap", {"type": "token", "text": "a"}, owner="7", tenant="2")
    second = replay.append("gap", {"type": "token", "text": "b"}, owner="7", tenant="2")
    replay.append("gap", {"type": "token", "text": "c"}, owner="7", tenant="2")
    with pytest.raises(replay.ReplayBackendUnavailable):
        replay.events_after("gap", first, owner="7", tenant="2")
    assert [row["payload"]["text"] for row in replay.events_after("gap", second, owner="7", tenant="2")] == ["c"]


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

    assert replay.claim_runner("turn-5", owner="7", tenant="2")
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

    assert replay.claim_runner("turn-7", owner="7", tenant="2")
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
                (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
            ],
        }
    )


async def test_resume_endpoint_rejects_anonymous_callers():
    with pytest.raises(HTTPException) as exc_info:
        await compat_routes.ai_chat_stream_resume(_http_request(), turn_id="turn-1", after="0")

    assert exc_info.value.status_code == 401


async def test_resume_endpoint_hides_another_owners_turn(monkeypatch):
    replay.append("turn-10", {"type": "token", "text": "secret"}, owner="7", tenant="2")
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_principal.require_agent_principal",
        lambda request, x_user_id=None: AgentPrincipal(user_id="8", tenant_id="2"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await compat_routes.ai_chat_stream_resume(_http_request(), turn_id="turn-10", after="0")

    assert exc_info.value.status_code == 404


@pytest.mark.parametrize("backend", ["fake", "lua"])
@pytest.mark.parametrize("operation", ["append", "clear", "finish"])
def test_expired_producer_cannot_mutate_replacement_replay(operation, backend):
    fake = (
        _FakeRedis()
        if backend == "fake"
        else pytest.importorskip("fakeredis").FakeRedis(decode_responses=True)
    )
    _use_redis(fake)
    turn, owner, tenant = "turn-fenced", "7", "2"
    assert replay.claim_runner(turn, owner=owner, tenant=tenant)
    old = replay.runner_for(turn, owner=owner, tenant=tenant)
    fake.delete(old.name)  # Redis expiry while the original worker remains alive.
    assert replay.claim_runner(turn, owner=owner, tenant=tenant)
    new = replay.runner_for(turn, owner=owner, tenant=tenant)
    replay.clear(turn, owner=owner, tenant=tenant, runner=new)
    replay.append(turn, {"text": "new"}, owner=owner, tenant=tenant, runner=new)
    with pytest.raises(replay.ReplayBackendUnavailable):
        if operation == "append":
            replay.append(turn, {"text": "stale"}, owner=owner, tenant=tenant, runner=old)
        elif operation == "clear":
            replay.clear(turn, owner=owner, tenant=tenant, runner=old)
        else:
            replay.mark_finished(turn, owner=owner, tenant=tenant, runner=old)
    assert replay.runner_for(turn, owner=owner, tenant=tenant) is new
    assert replay.lease_alive(turn, owner=owner, tenant=tenant)
    assert replay.finish_status(turn, owner=owner, tenant=tenant) is None
    assert [row["payload"] for row in replay.events_after(turn, owner=owner, tenant=tenant)] == [
        {"text": "new"}
    ]


def test_redis_retry_does_not_use_stale_local_terminal_state():
    fake = _FakeRedis()
    _use_redis(fake)
    replay._status[replay.scope_key("retry", "7", "2")] = "done"
    assert replay.claim_runner("retry", owner="7", tenant="2")
    assert replay.finish_status("retry", owner="7", tenant="2") is None
    fake.available = False
    with pytest.raises(replay.ReplayBackendUnavailable):
        replay.finish_status("retry", owner="7", tenant="2")


async def test_producer_cancels_and_joins_heartbeat_after_losing_lease(monkeypatch):
    fake = _FakeRedis()
    _use_redis(fake)
    assert replay.claim_runner("cancel", owner="7", tenant="2")
    runner = replay.runner_for("cancel", owner="7", tenant="2")
    started, closed = asyncio.Event(), asyncio.Event()
    released = []

    async def upstream(*args, **kwargs):
        try:
            started.set()
            await asyncio.Event().wait()
            yield ""
        finally:
            closed.set()

    monkeypatch.setattr(compat_routes, "compat_chat_stream_async", upstream)
    monkeypatch.setattr(
        "app.middleware.chat_stream_limit.release_chat_stream_slot", lambda: released.append(True)
    )
    monkeypatch.setattr(replay, "LEASE_TTL_SECONDS", 1)
    task = asyncio.create_task(
        compat_routes._produce_replay(
            _http_request(),
            compat_routes.XcagiCompatChatBody(message="hello"),
            ai_tier="p1",
            turn_id="cancel",
            owner="7",
            tenant="2",
            runner=runner,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    fake.delete(runner.name)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3)
    assert closed.is_set()
    assert released == [True]
    assert replay.finish_status("cancel", owner="7", tenant="2") is None
    assert not any(t.get_coro().__name__ == "_renew_replay_lease" for t in asyncio.all_tasks())


@pytest.mark.parametrize("cancel", [False, True])
async def test_producer_completion_joins_heartbeat_and_releases_lease(monkeypatch, cancel):
    fake = pytest.importorskip("fakeredis").FakeRedis(decode_responses=True)
    _use_redis(fake)
    assert replay.claim_runner("exit", owner="7", tenant="2")
    runner = replay.runner_for("exit", owner="7", tenant="2")
    started, closed = asyncio.Event(), asyncio.Event()
    slots = []

    async def upstream(*args, **kwargs):
        try:
            started.set()
            if cancel:
                await asyncio.Event().wait()
            yield 'data: {"type": "token", "text": "kept"}\n\n'
        finally:
            closed.set()

    monkeypatch.setattr(compat_routes, "compat_chat_stream_async", upstream)
    monkeypatch.setattr(
        "app.middleware.chat_stream_limit.release_chat_stream_slot", lambda: slots.append(True)
    )
    task = asyncio.create_task(
        compat_routes._produce_replay(
            _http_request(),
            compat_routes.XcagiCompatChatBody(message="hello"),
            ai_tier="p1",
            turn_id="exit",
            owner="7",
            tenant="2",
            runner=runner,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
    assert closed.is_set() and slots == [True]
    assert replay.runner_for("exit", owner="7", tenant="2") is None
    assert not replay.lease_alive("exit", owner="7", tenant="2")
    assert replay.finish_status("exit", owner="7", tenant="2") == ("aborted" if cancel else "done")
    assert not any(t.get_coro().__name__ == "_renew_replay_lease" for t in asyncio.all_tasks())


@pytest.mark.parametrize("backend", ["local", "lua"])
def test_claim_clears_old_replay_before_publishing_lease(backend):
    if backend == "lua":
        _use_redis(pytest.importorskip("fakeredis").FakeRedis(decode_responses=True))
    turn, owner, tenant = "atomic-retry", "7", "2"
    assert replay.claim_runner(turn, owner=owner, tenant=tenant)
    replay.append(turn, {"text": "old"}, owner=owner, tenant=tenant)
    replay.mark_finished(turn, owner=owner, tenant=tenant)
    assert replay.finish_status(turn, owner=owner, tenant=tenant) == "done"
    assert replay.claim_runner(turn, owner=owner, tenant=tenant)
    # A competing follower observes the lease but never the previous terminal/data.
    assert not replay.claim_runner(turn, owner=owner, tenant=tenant)
    assert replay.lease_alive(turn, owner=owner, tenant=tenant)
    assert replay.finish_status(turn, owner=owner, tenant=tenant) is None
    assert replay.events_after(turn, owner=owner, tenant=tenant) == []
    replay.append(turn, {"text": "new"}, owner=owner, tenant=tenant)
    assert not replay.claim_runner(turn, owner=owner, tenant=tenant)
    assert [row["payload"] for row in replay.events_after(turn, owner=owner, tenant=tenant)] == [
        {"text": "new"}
    ]


@pytest.mark.parametrize("decode_responses", [False, True])
def test_atomic_claim_uses_real_redis_lock_token_protocol(decode_responses):
    fake = pytest.importorskip("fakeredis").FakeRedis(decode_responses=decode_responses)
    _use_redis(fake)
    assert replay.claim_runner("protocol", owner="7")
    runner = replay.runner_for("protocol", owner="7")
    assert isinstance(runner.local.token, bytes)
    assert runner.owned()
    assert 0 < fake.pttl(runner.name) <= replay.LEASE_TTL_SECONDS * 1000
    assert runner.reacquire()
    replay.release_runner("protocol", owner="7", runner=runner)
    assert runner.local.token is None
    assert not fake.exists(runner.name)


@pytest.mark.parametrize("already_done", [False, True])
async def test_heartbeat_does_not_renew_completed_producer(monkeypatch, mocker, already_done):
    release = asyncio.Event()
    producer = asyncio.create_task(release.wait())
    runner = mocker.Mock()

    async def finish_during_sleep(delay):
        release.set()
        await producer

    monkeypatch.setattr(compat_routes.asyncio, "sleep", finish_during_sleep)
    if already_done:
        release.set()
        await producer
    await asyncio.wait_for(compat_routes._renew_replay_lease(runner, producer), timeout=2)
    runner.reacquire.assert_not_called()
    assert producer.done() and not producer.cancelled()


@pytest.mark.parametrize("mode", ["progress", "idle", "interrupted"])
async def test_replay_idle_timeout_measures_time_since_last_event(monkeypatch, mocker, mode):
    turn, owner, tenant = "long-running", "7", "2"
    clock = 0.0
    scope = {"owner": owner, "tenant": tenant}
    mocker.patch.object(compat_routes, "time").monotonic.side_effect = lambda: clock
    if mode != "interrupted":
        assert replay.claim_runner(turn, **scope)

    async def advance_clock(_delay):
        nonlocal clock
        clock += 250
        assert clock <= 1000
        if mode == "progress":
            replay.append(turn, {"type": "token", "text": str(int(clock))}, **scope)
            if clock == 1000:
                replay.mark_finished(turn, **scope)

    monkeypatch.setattr(compat_routes.asyncio, "sleep", advance_clock)
    chunks = [chunk async for chunk in compat_routes._follow_replay(turn, **scope)]

    if mode == "progress":
        rows = replay.events_after(turn, **scope)
        assert clock == 1000 and len(rows) == 4
        assert chunks == [compat_routes._replay_line(row) for row in rows]
    elif mode == "idle":
        assert clock == 750
        assert chunks == [b": replay idle timeout\n\n"]
    else:
        assert clock == 250
        assert len(chunks) == 1 and b"STREAM_INTERRUPTED" in chunks[0]


@pytest.mark.parametrize("decode_responses", [False, True])
async def test_redis_response_modes_preserve_replay_payload_cursor_and_done(decode_responses):
    fake = pytest.importorskip("fakeredis").FakeRedis(decode_responses=decode_responses)
    _use_redis(fake)
    turn, owner, tenant = "response-mode", "7", "2"
    assert replay.claim_runner(turn, owner=owner, tenant=tenant)
    payloads = [
        {"type": "token", "text": "首条"},
        {"type": "token", "text": "续传"},
        {"type": "done"},
    ]
    cursors = [replay.append(turn, payload, owner=owner, tenant=tenant) for payload in payloads]
    replay.mark_finished(turn, owner=owner, tenant=tenant)
    expected = [{"seq": cursor, "payload": payload} for cursor, payload in zip(cursors, payloads)]
    assert replay.events_after(turn, owner=owner, tenant=tenant) == expected
    assert replay.events_after(turn, cursors[0], owner=owner, tenant=tenant) == expected[1:]
    assert replay.events_after(turn, cursors[-1], owner=owner, tenant=tenant) == []
    assert replay.finish_status(turn, owner=owner, tenant=tenant) == "done"

    async def follow():
        return [
            chunk
            async for chunk in compat_routes._follow_replay(
                turn, cursors[0], owner=owner, tenant=tenant
            )
        ]

    chunks = await asyncio.wait_for(follow(), timeout=2)
    assert chunks == [compat_routes._replay_line(row) for row in expected[1:]]
