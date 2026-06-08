"""Redis Streams bridge for incident events.

This module is intentionally lightweight:
- ``publish_event`` appends events to a durable Redis Stream.
- ``read_group`` + ``ack`` provide consumer-group reads for workers/scripts.

When Redis is unavailable, callers should gracefully fall back to existing
in-process dispatch paths.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_redis_client = None
_redis_lock = threading.Lock()


def _stream_enabled_switch() -> bool:
    raw = (os.environ.get("MODSTORE_EVENT_STREAM_ENABLED", "1") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def redis_url() -> str:
    return (
        os.environ.get("MODSTORE_EVENT_STREAM_URL")
        or os.environ.get("MODSTORE_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or ""
    ).strip()


def stream_key() -> str:
    return (os.environ.get("MODSTORE_EVENT_STREAM_KEY") or "modstore:events:stream").strip()


def _stream_maxlen() -> int:
    try:
        return max(0, int(os.environ.get("MODSTORE_EVENT_STREAM_MAXLEN", "20000")))
    except ValueError:
        return 20000


def stream_enabled() -> bool:
    return _stream_enabled_switch() and bool(redis_url())


def _client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        url = redis_url()
        if not url:
            return None
        try:
            import redis
        except ImportError:
            logger.warning("redis-py not installed; Redis Streams disabled")
            return None
        try:
            _redis_client = redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=8.0,
                retry_on_timeout=True,
                health_check_interval=30,
            )
        except Exception:
            logger.exception("redis stream init failed")
            return None
    return _redis_client


def publish_event(
    *,
    event_type: str,
    payload: Dict[str, Any],
    source: str,
    incident_id: int = 0,
    event_id: str = "",
    fingerprint: str = "",
) -> Dict[str, Any]:
    if not stream_enabled():
        return {"ok": False, "reason": "disabled"}
    r = _client()
    if r is None:
        return {"ok": False, "reason": "redis client unavailable"}

    now_iso = datetime.now(timezone.utc).isoformat()
    resolved_event_id = (event_id or "").strip()
    if not resolved_event_id:
        sid = int(incident_id or 0)
        suffix = f"{time.time_ns():x}"[-12:]
        resolved_event_id = f"{event_type}:{sid or suffix}"

    data = {
        "event_id": resolved_event_id[:256],
        "event_type": str(event_type or "")[:128],
        "source": str(source or "")[:128],
        "incident_id": str(int(incident_id or 0)),
        "fingerprint": str(fingerprint or "")[:128],
        "occurred_at": now_iso,
        "payload_json": json.dumps(payload or {}, ensure_ascii=False, default=str)[:200_000],
    }
    key = stream_key()
    try:
        maxlen = _stream_maxlen()
        if maxlen > 0:
            mid = r.xadd(key, data, maxlen=maxlen, approximate=True)
        else:
            mid = r.xadd(key, data)
        return {"ok": True, "stream": key, "message_id": str(mid)}
    except Exception as exc:
        logger.exception("redis stream publish failed event=%s", event_type)
        return {"ok": False, "error": str(exc)[:300], "stream": key}


def ensure_group(group_name: str, *, key: str | None = None) -> Dict[str, Any]:
    if not stream_enabled():
        return {"ok": False, "reason": "disabled"}
    r = _client()
    if r is None:
        return {"ok": False, "reason": "redis client unavailable"}
    stream = (key or stream_key()).strip() or stream_key()
    group = (group_name or "").strip()
    if not group:
        return {"ok": False, "reason": "group_name required"}
    try:
        r.xgroup_create(stream, group, id="0-0", mkstream=True)
        return {"ok": True, "created": True, "stream": stream, "group": group}
    except Exception as exc:
        msg = str(exc)
        if "BUSYGROUP" in msg:
            return {"ok": True, "created": False, "stream": stream, "group": group}
        logger.exception("redis stream ensure_group failed stream=%s group=%s", stream, group)
        return {"ok": False, "error": msg[:300], "stream": stream, "group": group}


def read_group(
    group_name: str,
    consumer_name: str,
    *,
    count: int = 20,
    block_ms: int = 3000,
    start_id: str = ">",
    key: str | None = None,
) -> Dict[str, Any]:
    if not stream_enabled():
        return {"ok": False, "reason": "disabled", "events": []}
    r = _client()
    if r is None:
        return {"ok": False, "reason": "redis client unavailable", "events": []}

    stream = (key or stream_key()).strip() or stream_key()
    group = (group_name or "").strip()
    consumer = (consumer_name or "").strip()
    if not group or not consumer:
        return {"ok": False, "reason": "group_name/consumer_name required", "events": []}

    ensure_res = ensure_group(group, key=stream)
    if not ensure_res.get("ok"):
        return {
            "ok": False,
            "reason": ensure_res.get("error") or "ensure_group failed",
            "events": [],
        }

    try:
        rows = r.xreadgroup(
            group,
            consumer,
            {stream: start_id or ">"},
            count=max(1, int(count or 20)),
            block=max(0, int(block_ms or 0)),
        )
    except Exception as exc:
        logger.exception("redis stream read_group failed stream=%s group=%s", stream, group)
        return {"ok": False, "error": str(exc)[:300], "events": []}

    events: List[Dict[str, Any]] = []
    for _stream_name, messages in rows or []:
        for mid, fields in messages or []:
            raw = fields if isinstance(fields, dict) else {}
            payload_raw = raw.get("payload_json") or "{}"
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}
            events.append(
                {
                    "message_id": str(mid),
                    "stream": stream,
                    "event_id": str(raw.get("event_id") or "")[:256],
                    "event_type": str(raw.get("event_type") or "")[:128],
                    "source": str(raw.get("source") or "")[:128],
                    "incident_id": int(str(raw.get("incident_id") or "0") or 0),
                    "fingerprint": str(raw.get("fingerprint") or "")[:128],
                    "occurred_at": str(raw.get("occurred_at") or ""),
                    "payload": payload if isinstance(payload, dict) else {},
                    "raw_fields": raw,
                }
            )
    return {"ok": True, "events": events, "stream": stream, "group": group, "consumer": consumer}


def ack(group_name: str, message_ids: List[str], *, key: str | None = None) -> Dict[str, Any]:
    if not stream_enabled():
        return {"ok": False, "reason": "disabled"}
    r = _client()
    if r is None:
        return {"ok": False, "reason": "redis client unavailable"}
    group = (group_name or "").strip()
    stream = (key or stream_key()).strip() or stream_key()
    mids = [str(m).strip() for m in (message_ids or []) if str(m).strip()]
    if not group or not mids:
        return {"ok": False, "reason": "group_name/message_ids required"}
    try:
        n = r.xack(stream, group, *mids)
        return {"ok": True, "acked": int(n or 0), "stream": stream, "group": group}
    except Exception as exc:
        logger.exception("redis stream ack failed stream=%s group=%s", stream, group)
        return {"ok": False, "error": str(exc)[:300], "stream": stream, "group": group}


__all__ = [
    "ack",
    "ensure_group",
    "publish_event",
    "read_group",
    "redis_url",
    "stream_enabled",
    "stream_key",
]
