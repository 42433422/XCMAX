"""按 turn 回放的聊天 SSE 事件缓冲。

生产端与 HTTP 连接解耦：生产者把事件写入按 ``tenant:owner:turn`` 绑定的
Redis Stream，连接只按游标跟随，因此跨 worker 的续传不依赖进程内状态。

- 归属：命名空间包含租户与发起者，其它主体的请求读不到同一条流。
- 单生产者：``redis-py`` 的分布式锁（``SET NX PX`` + Lua 释放）充当生产权
  租约，后台心跳续期；锁丢失即视为生产端失联。
- 连续性：事件与序号由 Stream 条目 ID 原子生成，故障切换不会重启序号；
  运行期后端不可用时显式失败，不静默切到进程内缓冲。

无 Redis 的单进程部署（桌面）退回进程内缓冲，语义保持一致。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

REPLAY_TTL_SECONDS = int(os.environ.get("XCAGI_CHAT_STREAM_REPLAY_TTL_SECONDS", "1800"))
REPLAY_MAX_EVENTS = int(os.environ.get("XCAGI_CHAT_STREAM_REPLAY_MAX_EVENTS", "5000"))
LEASE_TTL_SECONDS = int(os.environ.get("XCAGI_CHAT_STREAM_LEASE_TTL_SECONDS", "30"))
_PREFIX = "chat_stream:replay"
_STREAM_ID = re.compile(r"^\d+-\d+$")

_lock = threading.Lock()
_events: dict[str, list[dict[str, Any]]] = {}
_status: dict[str, str] = {}
_running: set[str] = set()
_touched: dict[str, float] = {}
_leases: dict[str, Any] = {}


class ReplayBackendUnavailable(RuntimeError):
    """回放后端不可用；调用方必须显式终止流，不得静默降级。"""


def _backend() -> tuple[Any, str, bool]:
    """返回 ``(client, prefix, configured)``；``client`` 为 None 表示不可用。"""
    try:
        from app.utils.performance.redis_cache import get_redis_cache

        cache = get_redis_cache()
        client = getattr(cache, "_redis", None)
        prefix = str(getattr(cache, "_prefix", "") or "")
        configured = client is not None
        if not configured:
            from app.utils.deployment import redis_url_from_env

            env_url = (os.environ.get("CACHE_REDIS_URL") or "").strip() or redis_url_from_env()
            configured = bool(env_url)
        if not configured:
            return None, prefix, False
        if not cache.is_available:
            return None, prefix, True
        return client, prefix, True
    except RECOVERABLE_ERRORS:
        return None, "", False


def _require_client() -> tuple[Any, str]:
    client, prefix, configured = _backend()
    if client is None and configured:
        raise ReplayBackendUnavailable("回放后端不可用")
    return client, prefix


def scope_key(turn_id: str, owner: str, tenant: str) -> str:
    """按租户 + 发起者隔离回放命名空间；不含 session，重登不丢进行中的流。"""
    return f"{tenant or '-'}:{owner or '-'}:{turn_id}"


def _redis_keys(scoped: str, prefix: str) -> tuple[str, str, str]:
    base = f"{prefix}{_PREFIX}:{scoped}"
    return f"{base}:stream", f"{base}:status", f"{base}:lease"


def _prune_locked() -> None:
    if len(_touched) < 200:
        return
    cutoff = time.time() - REPLAY_TTL_SECONDS
    for scoped, seen in list(_touched.items()):
        if seen >= cutoff or scoped in _running or scoped in _leases:
            continue
        _events.pop(scoped, None)
        _status.pop(scoped, None)
        _touched.pop(scoped, None)


def append(
    turn_id: str, payload: dict[str, Any], *, owner: str = "", tenant: str = "", runner: Any = None
) -> str:
    """追加一条事件并返回游标；无 turn_id 时返回空串（不进缓冲）。"""
    if not turn_id:
        return ""
    scoped = scope_key(turn_id, owner, tenant)
    client, prefix = _require_client()
    if client is not None:
        entry_id = _fenced(
            client, scoped, prefix, runner, "append", json.dumps(payload, ensure_ascii=False)
        )
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
    with _lock:
        _prune_locked()
        bucket = _events.setdefault(scoped, [])
        seq = int(bucket[-1]["seq"]) + 1 if bucket else 1
        bucket.append({"seq": seq, "payload": payload})
        if len(bucket) > REPLAY_MAX_EVENTS:
            del bucket[: len(bucket) - REPLAY_MAX_EVENTS]
        _touched[scoped] = time.time()
        return str(seq)


def events_after(
    turn_id: str, after: str | int = 0, *, owner: str = "", tenant: str = ""
) -> list[dict[str, Any]]:
    """返回游标之后的事件，元素形如 ``{"seq": str, "payload": dict}``。"""
    if not turn_id:
        return []
    scoped = scope_key(turn_id, owner, tenant)
    cursor = str(after or "")
    from_start = cursor in {"", "0", "0-0"}
    client, prefix = _require_client()
    if client is not None:
        stream_key, _, _ = _redis_keys(scoped, prefix)
        try:
            if not from_start and not _STREAM_ID.fullmatch(cursor):
                raise ReplayBackendUnavailable("无效的回放游标")
            raw = client.xrange(stream_key, min="-" if from_start else cursor, max="+")
        except RECOVERABLE_ERRORS:
            raise ReplayBackendUnavailable("回放流读取失败") from None
        if not from_start:
            first = raw[0][0] if raw else None
            if isinstance(first, bytes):
                first = first.decode()
            if first != cursor:
                raise ReplayBackendUnavailable("原事件游标已失效，请核对原任务回执")
        out: list[dict[str, Any]] = []
        for entry_id, fields in raw:
            sid = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            if sid == cursor:
                continue
            try:
                fields = fields or {}
                payload = json.loads(fields.get("payload", fields.get(b"payload")) or "{}")
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict):
                out.append({"seq": sid, "payload": payload})
        return out
    if not from_start and not cursor.isdigit():
        raise ReplayBackendUnavailable("无效的回放游标")
    after_int = 0 if from_start else int(cursor)
    with _lock:
        bucket = _events.get(scoped) or []
        if after_int and not any(int(row["seq"]) == after_int for row in bucket):
            raise ReplayBackendUnavailable("原事件游标已失效，请核对原任务回执")
        if from_start and bucket and int(bucket[0]["seq"]) != 1:
            raise ReplayBackendUnavailable("回放历史不完整，请核对原任务回执")
        _touched[scoped] = time.time()
        return [dict(row) for row in bucket if int(row["seq"]) > after_int]


def has_replay(turn_id: str, *, owner: str = "", tenant: str = "") -> bool:
    if not turn_id:
        return False
    scoped = scope_key(turn_id, owner, tenant)
    client, prefix = _require_client()
    if client is not None:
        stream_key, status_key, lease_key = _redis_keys(scoped, prefix)
        try:
            return bool(client.exists(stream_key, status_key, lease_key))
        except RECOVERABLE_ERRORS:
            raise ReplayBackendUnavailable("回放状态读取失败") from None
    with _lock:
        return bool(_events.get(scoped) or scoped in _status or scoped in _running)


def claim_runner(turn_id: str, *, owner: str = "", tenant: str = "") -> bool:
    """原子抢占生产权并清除旧回放；失败时保留当前生产者的数据。"""
    if not turn_id:
        return True
    scoped = scope_key(turn_id, owner, tenant)
    client, prefix = _require_client()
    if client is not None:
        from redis.lock import Lock

        stream_key, status_key, lease_key = _redis_keys(scoped, prefix)
        lease = Lock(
            client,
            lease_key,
            timeout=LEASE_TTL_SECONDS,
            blocking_timeout=0,
            thread_local=False,
        )
        token = uuid.uuid4().hex.encode()
        try:
            claim = client.register_script(
                """
                if not redis.call('set', KEYS[3], ARGV[1], 'NX', 'PX', ARGV[2]) then
                    return 0
                end
                redis.call('del', KEYS[1], KEYS[2])
                return 1
                """
            )
            if not claim(
                keys=[stream_key, status_key, lease_key],
                args=[token, LEASE_TTL_SECONDS * 1000],
            ):
                return False
            lease.local.token = token
        except RECOVERABLE_ERRORS:
            raise ReplayBackendUnavailable("生产权租约不可用") from None
        with _lock:
            _leases[scoped] = lease
            _touched[scoped] = time.time()
        return True
    with _lock:
        if scoped in _running:
            return False
        _running.add(scoped)
        _events.pop(scoped, None)
        _status.pop(scoped, None)
        _touched[scoped] = time.time()
    return True


def runner_for(turn_id: str, *, owner: str = "", tenant: str = "") -> Any:
    """Capture the lease once: an old producer must never borrow a replacement."""
    with _lock:
        return _leases.get(scope_key(turn_id, owner, tenant))


def release_runner(turn_id: str, *, owner: str = "", tenant: str = "", runner: Any = None) -> None:
    scoped = scope_key(turn_id, owner, tenant)
    with _lock:
        _running.discard(scoped)
        lease = runner if runner is not None else _leases.get(scoped)
        if _leases.get(scoped) is lease:
            _leases.pop(scoped, None)
    if lease is not None:
        try:
            lease.release()
        except RECOVERABLE_ERRORS:
            pass


def _fenced(
    client: Any, scoped: str, prefix: str, runner: Any, action: str, value: str = ""
) -> Any:
    """Compare the captured lease token and mutate replay data in one Redis operation."""
    if runner is None:
        with _lock:
            runner = _leases.get(scoped)
    token = runner.local.token if runner is not None else None
    if token is None:
        raise ReplayBackendUnavailable("生产权租约已失效")
    stream, status, lease = _redis_keys(scoped, prefix)
    try:
        mutate = client.register_script(
            """
            if redis.call('get', KEYS[3]) ~= ARGV[1] then return false end
            if ARGV[2] == 'append' then
                local id = redis.call('xadd', KEYS[1], 'MAXLEN', ARGV[5], '*', 'payload', ARGV[3])
                redis.call('expire', KEYS[1], ARGV[4])
                return id
            elseif ARGV[2] == 'finish' then
                redis.call('set', KEYS[2], ARGV[3], 'EX', ARGV[4])
                redis.call('expire', KEYS[1], ARGV[4])
            elseif ARGV[2] == 'clear' then
                redis.call('del', KEYS[1], KEYS[2])
            end
            return 1
            """,
        )
        result = mutate(
            keys=[stream, status, lease],
            args=[token, action, value, REPLAY_TTL_SECONDS, REPLAY_MAX_EVENTS],
        )
    except RECOVERABLE_ERRORS:
        raise ReplayBackendUnavailable("回放流写入失败") from None
    if not result:
        raise ReplayBackendUnavailable("生产权租约已失效")
    return result


def mark_finished(
    turn_id: str, status: str = "done", *, owner: str = "", tenant: str = "", runner: Any = None
) -> None:
    if not turn_id:
        return
    scoped = scope_key(turn_id, owner, tenant)
    try:
        client, prefix = _require_client()
        if client is not None:
            _fenced(client, scoped, prefix, runner, "finish", status)
        else:
            with _lock:
                _status[scoped] = status
                _touched[scoped] = time.time()
    finally:
        release_runner(turn_id, owner=owner, tenant=tenant, runner=runner)


def finish_status(turn_id: str, *, owner: str = "", tenant: str = "") -> str | None:
    """Redis is authoritative across workers, including retries of a finished turn."""
    if not turn_id:
        return None
    scoped = scope_key(turn_id, owner, tenant)
    client, prefix = _require_client()
    if client is not None:
        _, status_key, _ = _redis_keys(scoped, prefix)
        try:
            value = client.get(status_key)
        except RECOVERABLE_ERRORS:
            raise ReplayBackendUnavailable("回放状态读取失败") from None
        if isinstance(value, bytes):
            value = value.decode()
        return str(value) if value else None
    with _lock:
        return _status.get(scoped)


def lease_alive(turn_id: str, *, owner: str = "", tenant: str = "") -> bool:
    """生产端是否仍持有租约；无法确认时返回 True，避免误报断流。"""
    if not turn_id:
        return False
    scoped = scope_key(turn_id, owner, tenant)
    client, prefix, configured = _backend()
    if client is not None:
        _, _, lease_key = _redis_keys(scoped, prefix)
        try:
            return bool(client.exists(lease_key))
        except RECOVERABLE_ERRORS:
            return True
    if configured:
        return True
    with _lock:
        return scoped in _running


def clear(turn_id: str, *, owner: str = "", tenant: str = "", runner: Any = None) -> None:
    """清空该 turn 的事件与终态；不动租约（调用方已持有生产权）。"""
    if not turn_id:
        return
    scoped = scope_key(turn_id, owner, tenant)
    with _lock:
        _events.pop(scoped, None)
        _status.pop(scoped, None)
        _touched.pop(scoped, None)
    client, prefix = _require_client()
    if client is not None:
        _fenced(client, scoped, prefix, runner, "clear")
