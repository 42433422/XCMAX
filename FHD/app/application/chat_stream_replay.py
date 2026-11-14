"""按 turn 回放的聊天 SSE 事件缓冲。

断线续传的前提是「事件生产」与「HTTP 连接」解耦：后台任务持续把事件写入
本模块，HTTP 连接只负责按序号跟随读取。客户端重连时带上同一 ``turn_id``
和最后收到的序号，即可从断点继续。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

REPLAY_TTL_SECONDS = int(os.environ.get("XCAGI_CHAT_STREAM_REPLAY_TTL_SECONDS", "1800"))
REPLAY_MAX_EVENTS = int(os.environ.get("XCAGI_CHAT_STREAM_REPLAY_MAX_EVENTS", "5000"))
_PREFIX = "chat_stream:replay"

_lock = threading.Lock()
_events: dict[str, list[dict[str, Any]]] = {}
_status: dict[str, str] = {}
_running: set[str] = set()
_touched: dict[str, float] = {}


def _redis() -> tuple[Any, str]:
    try:
        from app.utils.performance.redis_cache import get_redis_cache

        cache = get_redis_cache()
        if not cache.is_available:
            return None, ""
        return getattr(cache, "_redis", None), str(getattr(cache, "_prefix", "") or "")
    except RECOVERABLE_ERRORS:
        return None, ""


def _events_key(turn_id: str, prefix: str) -> str:
    return f"{prefix}{_PREFIX}:{turn_id}:events"


def _seq_key(turn_id: str, prefix: str) -> str:
    return f"{prefix}{_PREFIX}:{turn_id}:seq"


def _status_key(turn_id: str, prefix: str) -> str:
    return f"{prefix}{_PREFIX}:{turn_id}:status"


def _prune_locked() -> None:
    if len(_touched) < 200:
        return
    cutoff = time.time() - REPLAY_TTL_SECONDS
    for turn_id, seen in list(_touched.items()):
        if seen >= cutoff or turn_id in _running:
            continue
        _events.pop(turn_id, None)
        _status.pop(turn_id, None)
        _touched.pop(turn_id, None)


def append(turn_id: str, payload: dict[str, Any]) -> int:
    """追加一条事件并返回其序号；无 turn_id 时返回 0（不进缓冲）。"""
    if not turn_id:
        return 0
    client, prefix = _redis()
    if client is not None:
        try:
            seq = int(client.incr(_seq_key(turn_id, prefix)))
            client.expire(_seq_key(turn_id, prefix), REPLAY_TTL_SECONDS)
            key = _events_key(turn_id, prefix)
            client.rpush(key, json.dumps({"seq": seq, "payload": payload}, ensure_ascii=False))
            client.expire(key, REPLAY_TTL_SECONDS)
            return seq
        except RECOVERABLE_ERRORS:
            pass
    with _lock:
        _prune_locked()
        bucket = _events.setdefault(turn_id, [])
        seq = int(bucket[-1]["seq"]) + 1 if bucket else 1
        bucket.append({"seq": seq, "payload": payload})
        if len(bucket) > REPLAY_MAX_EVENTS:
            del bucket[: len(bucket) - REPLAY_MAX_EVENTS]
        _touched[turn_id] = time.time()
        return seq


def events_after(turn_id: str, after: int = 0) -> list[dict[str, Any]]:
    """返回序号大于 ``after`` 的事件，元素形如 ``{"seq": int, "payload": dict}``。"""
    if not turn_id:
        return []
    client, prefix = _redis()
    if client is not None:
        try:
            raw = client.lrange(_events_key(turn_id, prefix), 0, -1)
            out: list[dict[str, Any]] = []
            for item in raw:
                try:
                    row = json.loads(item)
                except (ValueError, TypeError):
                    continue
                if isinstance(row, dict) and int(row.get("seq") or 0) > after:
                    out.append(row)
            return out
        except RECOVERABLE_ERRORS:
            pass
    with _lock:
        bucket = _events.get(turn_id) or []
        _touched[turn_id] = time.time()
        return [dict(row) for row in bucket if int(row["seq"]) > after]


def has_replay(turn_id: str) -> bool:
    if not turn_id:
        return False
    with _lock:
        if _events.get(turn_id) or turn_id in _status:
            return True
    client, prefix = _redis()
    if client is not None:
        try:
            return bool(client.exists(_events_key(turn_id, prefix)))
        except RECOVERABLE_ERRORS:
            return False
    return False


def claim_runner(turn_id: str) -> bool:
    """抢占该 turn 的生产权；返回 True 表示由当前请求负责跑任务。"""
    if not turn_id:
        return True
    with _lock:
        if turn_id in _running:
            return False
        _running.add(turn_id)
        _touched[turn_id] = time.time()
    return True


def release_runner(turn_id: str) -> None:
    with _lock:
        _running.discard(turn_id)


def mark_finished(turn_id: str, status: str = "done") -> None:
    if not turn_id:
        return
    with _lock:
        _status[turn_id] = status
        _running.discard(turn_id)
        _touched[turn_id] = time.time()
    client, prefix = _redis()
    if client is not None:
        try:
            client.set(_status_key(turn_id, prefix), status, ex=REPLAY_TTL_SECONDS)
        except RECOVERABLE_ERRORS:
            pass


def finish_status(turn_id: str) -> str | None:
    """返回 ``done`` / ``error`` / ``aborted``；仍在运行时返回 None。"""
    if not turn_id:
        return None
    with _lock:
        local = _status.get(turn_id)
        if local:
            return local
    client, prefix = _redis()
    if client is not None:
        try:
            value = client.get(_status_key(turn_id, prefix))
            if isinstance(value, bytes):
                value = value.decode()
            if value:
                return str(value)
        except RECOVERABLE_ERRORS:
            return None
    return None


def clear(turn_id: str) -> None:
    with _lock:
        _events.pop(turn_id, None)
        _status.pop(turn_id, None)
        _running.discard(turn_id)
        _touched.pop(turn_id, None)
    client, prefix = _redis()
    if client is not None:
        try:
            client.delete(
                _events_key(turn_id, prefix),
                _seq_key(turn_id, prefix),
                _status_key(turn_id, prefix),
            )
        except RECOVERABLE_ERRORS:
            pass
