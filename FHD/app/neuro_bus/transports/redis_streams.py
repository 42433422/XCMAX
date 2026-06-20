# FHD/app/neuro_bus/transports/redis_streams.py
"""Redis Streams 桥 — 跨 Pod 事件广播，消费确认 + 持久化 + DLQ。

启用：XCAGI_NEURO_BUS_REDIS_TRANSPORT=streams
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.neuro_bus.bus import NeuroBus
    from app.neuro_bus.events.base import NeuroEvent

STREAM_KEY = "neurobus:events"
DLQ_KEY = "neurobus:dlq"
CONSUMER_GROUP = "neurobus-workers"
MAXLEN = 100000


def streams_enabled() -> bool:
    return os.environ.get("XCAGI_NEURO_BUS_REDIS_TRANSPORT", "").strip().lower() == "streams"


class RedisStreamsBridge:
    """Redis Streams 桥接器。"""

    def __init__(
        self,
        bus: NeuroBus,
        redis_client: Any | None = None,
        consumer_id: str | None = None,
    ) -> None:
        self._bus = bus
        self._redis = redis_client
        self._consumer_id = consumer_id or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._ensure_group()

    def _ensure_group(self) -> None:
        """确保消费组存在。"""
        if self._redis is None:
            return
        try:
            self._redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="$", mkstream=True)
            logger.info("created consumer group %s on %s", CONSUMER_GROUP, STREAM_KEY)
        except Exception as e:  # noqa: BLE001 - transport boundary: handle all redis errors gracefully
            # BUSYGROUP 表示已存在
            if "BUSYGROUP" not in str(e):
                logger.debug("xgroup create: %s", e)

    def publish(self, event_dict: dict[str, Any]) -> str | None:
        """发布事件到 Stream。"""
        if self._redis is None:
            return None
        msg_id = self._redis.xadd(
            STREAM_KEY,
            fields={"payload": json.dumps(event_dict, ensure_ascii=False)},
            maxlen=MAXLEN,
            approximate=True,
        )
        return msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

    def publish_remote(self, event: NeuroEvent) -> None:
        """发布事件到远程 Stream（接口兼容 RedisPubSubBridge）。"""
        if self._redis is None:
            return
        if event.payload.get("local_only") is True:
            return
        self.publish(event.to_dict())

    def consume(self, count: int = 100, block_ms: int = 5000) -> list[dict[str, Any]]:
        """从 Stream 消费消息（不自动 ACK）。"""
        if self._redis is None:
            return []
        result = self._redis.xreadgroup(
            CONSUMER_GROUP,
            self._consumer_id,
            {STREAM_KEY: ">"},
            count=count,
            block=block_ms,
        )
        messages: list[dict[str, Any]] = []
        for _stream, entries in result:
            for msg_id, fields in entries:
                payload = fields.get(b"payload") or fields.get("payload")
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                try:
                    msg = json.loads(payload)
                    msg["_msg_id"] = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                    messages.append(msg)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning("failed to decode stream message %s: %s", msg_id, e)
                    self.ack(msg_id)
        return messages

    def ack(self, msg_id: str) -> None:
        """确认消息已处理。"""
        if self._redis is None:
            return
        self._redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)

    def send_to_dlq(self, event_dict: dict[str, Any], original_msg_id: str) -> None:
        """失败消息转入 DLQ 并 ACK 原消息。"""
        if self._redis is None:
            return
        self._redis.xadd(
            DLQ_KEY,
            {"payload": json.dumps(event_dict, ensure_ascii=False), "original_id": original_msg_id},
            maxlen=MAXLEN,
            approximate=True,
        )
        self.ack(original_msg_id)
        logger.warning("message %s moved to DLQ", original_msg_id)
