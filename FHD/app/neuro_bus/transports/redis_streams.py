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
    from app.neuro_bus.events.events_base import NeuroEvent

STREAM_KEY = "neurobus:events"
DLQ_KEY = "neurobus:dlq"
CONSUMER_GROUP = "neurobus-workers"
MAXLEN = 100000

# MAXLEN is a soft retention target, never permission to discard pending work.
# Redis 6.2+ MINID removes strictly older IDs. Calculate the fence and trim
# atomically on the server so group creation/delivery/ACK cannot race it.
TRIM_BATCH = 256
_SAFE_TRIM = """
local key = KEYS[1]
local excess = redis.call('XLEN', key) - tonumber(ARGV[1])
if excess <= 0 then return 0 end

-- Compare canonical decimal strings: Lua doubles cannot represent every
-- unsigned 64-bit stream ID exactly.
local function valid(id)
    return type(id) == 'string' and string.match(id, '^%d+%-%d+$')
end
local function decimal_less(a, b)
    if #a ~= #b then return #a < #b end
    return a < b
end
local function less(a, b)
    local am, as = string.match(a, '^(%d+)%-(%d+)$')
    local bm, bs = string.match(b, '^(%d+)%-(%d+)$')
    if am ~= bm then return decimal_less(am, bm) end
    return decimal_less(as, bs)
end

local groups = redis.call('XINFO', 'GROUPS', key)
if #groups == 0 then return 0 end
local fence = nil
for _, group in ipairs(groups) do
    local name, delivered, pending_count
    for i = 1, #group, 2 do
        if group[i] == 'name' then name = group[i + 1] end
        if group[i] == 'last-delivered-id' then delivered = group[i + 1] end
        if group[i] == 'pending' then pending_count = group[i + 1] end
    end
    if type(name) ~= 'string' or not valid(delivered)
        or type(pending_count) ~= 'number' or pending_count < 0 then
        return 0
    end
    -- Keep the last delivered ID and everything newer.
    if not fence or less(delivered, fence) then fence = delivered end
    if pending_count > 0 then
        local pending = redis.call('XPENDING', key, name, '-', '+', 1)
        if #pending ~= 1 or not valid(pending[1][1]) then return 0 end
        if less(pending[1][1], fence) then fence = pending[1][1] end
    end
    if fence == '0-0' then return 0 end
end

-- Bound exact trimming to a single batch without overshooting MAXLEN.
-- The extra entry is the first ID that must remain.
local batch = math.min(excess, tonumber(ARGV[2]))
local entries = redis.call('XRANGE', key, '-', '+', 'COUNT', batch + 1)
if #entries ~= batch + 1 then return 0 end
local retain = entries[#entries][1]
if not valid(retain) then return 0 end
if less(retain, fence) then fence = retain end
return redis.call('XTRIM', key, 'MINID', '=', fence)
"""


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
        from redis.exceptions import RedisError

        try:
            # A newly created group must not skip retained, unread history.
            self._redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0-0", mkstream=True)
            logger.info("created consumer group %s on %s", CONSUMER_GROUP, STREAM_KEY)
        except RedisError as e:
            # BUSYGROUP 表示已存在（进程重启后重复创建是正常路径）。
            # redis 的 ResponseError 不属于 RECOVERABLE_ERRORS 家族，必须显式兜住，
            # 否则重启即崩溃（2026-09-09 R12 真实 Redis 验收发现）。
            if "BUSYGROUP" not in str(e):
                logger.debug("xgroup create: %s", e)

    def publish(self, event_dict: dict[str, Any]) -> str | None:
        """发布事件到 Stream。"""
        if self._redis is None:
            return None
        msg_id = self._redis.xadd(
            STREAM_KEY,
            fields={"payload": json.dumps(event_dict, ensure_ascii=False)},
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
        if self._redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id):
            self.trim_acknowledged()

    def trim_acknowledged(self) -> int:
        """Trim only the acknowledged prefix shared by all existing groups.

        Missing progress or an unsupported Redis command must never fall
        back to length-based deletion. Maintenance failure must not turn
        a successful ACK into a failed business receipt.
        """
        if self._redis is None:
            return 0
        from redis.exceptions import RedisError

        try:
            return int(self._redis.eval(_SAFE_TRIM, 1, STREAM_KEY, MAXLEN, TRIM_BATCH))
        except RedisError:
            logger.warning("safe stream trim failed; retaining backlog", exc_info=True)
            return 0

    def send_to_dlq(self, event_dict: dict[str, Any], original_msg_id: str) -> None:
        """失败消息转入 DLQ 并 ACK 原消息。"""
        if self._redis is None:
            return
        # No managed DLQ consumer progress yet: retain failures rather
        # than silently dropping them at a length watermark.
        self._redis.xadd(
            DLQ_KEY,
            {"payload": json.dumps(event_dict, ensure_ascii=False), "original_id": original_msg_id},
        )
        self.ack(original_msg_id)
        logger.warning("message %s moved to DLQ", original_msg_id)
