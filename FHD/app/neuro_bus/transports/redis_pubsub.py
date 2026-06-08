"""
NeuroBus Redis Pub/Sub 桥 — 跨 Pod / 跨进程事件广播。

启用：XCAGI_NEURO_BUS_REDIS_PUBSUB=1
URL：XCAGI_NEURO_BUS_REDIS_URL 或 CACHE_REDIS_URL / REDIS_URL（db 默认 3）
"""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import json
import logging
import os
import threading
import uuid
from typing import TYPE_CHECKING, Any

from app.neuro_bus.events.base import NeuroEvent

if TYPE_CHECKING:
    from app.neuro_bus.bus import NeuroBus

logger = logging.getLogger(__name__)

CHANNEL = "neurobus:events"
_REMOTE_FLAG = "_neuro_remote_ingest"
_ORIGIN_FLAG = "_neuro_origin_instance"


def redis_pubsub_enabled() -> bool:
    return os.environ.get("XCAGI_NEURO_BUS_REDIS_PUBSUB", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolve_redis_url() -> str | None:
    for key in (
        "XCAGI_NEURO_BUS_REDIS_URL",
        "CACHE_REDIS_URL",
        "REDIS_URL",
    ):
        raw = os.environ.get(key, "").strip()
        if raw:
            return raw
    return None


class RedisPubSubBridge:
    """将本地 publish 广播到 Redis；订阅端 ingest 回本地队列（防环）。"""

    def __init__(self, bus: NeuroBus) -> None:
        self._bus = bus
        self._instance_id = str(uuid.uuid4())
        self._redis = None
        self._pubsub = None
        self._listener_thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def connect(self) -> bool:
        url = _resolve_redis_url()
        if not url:
            logger.warning("NeuroBus Redis Pub/Sub: no REDIS URL configured")
            return False
        try:
            import redis

            self._redis = redis.from_url(url, decode_responses=True)
            self._redis.ping()
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            self._pubsub.subscribe(CHANNEL)
            logger.info("NeuroBus Redis Pub/Sub connected channel=%s", CHANNEL)
            return True
        except OPERATIONAL_ERRORS as exc:
            logger.error("NeuroBus Redis Pub/Sub connect failed: %s", exc)
            self._redis = None
            self._pubsub = None
            return False

    def start(self) -> None:
        if not self.connect():
            return

        def _listen() -> None:
            assert self._pubsub is not None
            while not self._stop.is_set():
                try:
                    message = self._pubsub.get_message(timeout=1.0)
                    if not message or message.get("type") != "message":
                        continue
                    self._handle_message(message.get("data"))
                except OPERATIONAL_ERRORS as exc:
                    if not self._stop.is_set():
                        logger.warning("NeuroBus Redis listener error: %s", exc)

        self._listener_thread = threading.Thread(
            target=_listen,
            name="neurobus_redis_pubsub",
            daemon=True,
        )
        self._listener_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._pubsub is not None:
            try:
                self._pubsub.unsubscribe(CHANNEL)
                self._pubsub.close()
            except OPERATIONAL_ERRORS:
                pass
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=2.0)
        self._listener_thread = None
        self._pubsub = None
        if self._redis is not None:
            try:
                self._redis.close()
            except OPERATIONAL_ERRORS:
                pass
        self._redis = None

    def publish_remote(self, event: NeuroEvent) -> None:
        if self._redis is None:
            return
        if event.payload.get("local_only") is True:
            return
        envelope: dict[str, Any] = {
            "origin": self._instance_id,
            "event": event.to_dict(),
        }
        try:
            self._redis.publish(CHANNEL, json.dumps(envelope, ensure_ascii=False))
        except OPERATIONAL_ERRORS as exc:
            logger.warning("NeuroBus Redis publish failed: %s", exc)

    def _handle_message(self, raw: Any) -> None:
        if not raw:
            return
        try:
            envelope = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return
        if envelope.get("origin") == self._instance_id:
            return
        event_data = envelope.get("event")
        if not isinstance(event_data, dict):
            return
        event = NeuroEvent.from_dict(event_data, preserve_queue_identity=True)
        payload = dict(event.payload or {})
        payload[_REMOTE_FLAG] = True
        payload[_ORIGIN_FLAG] = envelope.get("origin")
        event.payload = payload
        self._bus.ingest_remote_event(event)
