"""Redis Streams work-queue transport with a supervised consumer lifecycle."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import uuid
from typing import TYPE_CHECKING, Any

from app.neuro_bus.events.events_base import NeuroEvent

if TYPE_CHECKING:
    from app.neuro_bus.bus import NeuroBus

logger = logging.getLogger(__name__)

STREAM_KEY = "neurobus:events"
DLQ_KEY = "neurobus:dlq"
CONSUMER_GROUP = "neurobus-workers"
CLAIM_IDLE_MS = 60000
MAX_DELIVERIES = 5
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


# Check ownership and finalize/renew atomically: a stale consumer must never
# ACK a message that another worker has recovered. JUSTID does not add retries.
_OWNED = """
local p = redis.call('XPENDING', KEYS[1], ARGV[1], ARGV[2], ARGV[2], 1)
if #p == 0 or p[1][2] ~= ARGV[3] then return 0 end
"""
_ACK = _OWNED + "return redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])"
_RENEW = _OWNED + """
local ids = redis.call('XCLAIM', KEYS[1], ARGV[1], ARGV[3], 0, ARGV[2], 'JUSTID')
return #ids
"""
_DEAD_LETTER = _OWNED + """
redis.call('XADD', KEYS[2], '*', 'payload', ARGV[4], 'original_id', ARGV[2])
return redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
"""


def streams_enabled() -> bool:
    return os.environ.get("XCAGI_NEURO_BUS_REDIS_TRANSPORT", "").strip().lower() == "streams"


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class RedisStreamsBridge:
    """One supervised worker per bus; Redis PEL is the recovery source."""

    def __init__(
        self,
        bus: NeuroBus,
        redis_client: Any | None = None,
        consumer_id: str | None = None,
        *,
        owns_client: bool = False,
    ) -> None:
        self._bus = bus
        self._redis = redis_client
        self._owns_client = owns_client
        self._consumer_id = consumer_id or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._group_ready = False
        self._claim_cursor = "0-0"

    def _ensure_group(self) -> None:
        from redis.exceptions import ResponseError

        if self._redis is None:
            raise RuntimeError("Redis Streams client missing")
        if self._group_ready:
            return
        try:
            # First startup must see any events published before group creation.
            self._redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._group_ready = True

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if self._redis is None:
            raise RuntimeError("Redis Streams client missing")
        self._stop = asyncio.Event()
        self._group_ready = False
        self._claim_cursor = "0-0"
        self._task = asyncio.create_task(self._run(), name="neurobus_redis_streams")
        self._task.add_done_callback(self._report_exit)

    @staticmethod
    def _report_exit(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception() is not None:
            exc = task.exception()
            logger.error(
                "Redis Streams worker terminated", exc_info=(type(exc), exc, exc.__traceback__)
            )

    async def stop(self) -> None:
        task = self._task
        if self._stop is not None:
            self._stop.set()
        try:
            if task is not None:
                await asyncio.shield(task)
        finally:
            self._group_ready = False
            if task is None or task.done():
                self._task = None
                if self._owns_client and self._redis is not None:
                    await asyncio.to_thread(self._redis.close)

    def get_stats(self) -> dict[str, Any]:
        running = self._task is not None and not self._task.done()
        return {"running": running, "ready": running and self._group_ready}

    def publish(self, event_dict: dict[str, Any]) -> str | None:
        if self._redis is None:
            return None
        # Do not trim pending or never-delivered events via approximate MAXLEN.
        return _text(self._redis.xadd(
            STREAM_KEY, fields={"payload": json.dumps(event_dict, ensure_ascii=False)}
        ))

    def publish_remote(self, event: NeuroEvent) -> str | None:
        from redis.exceptions import RedisError

        if event.payload.get("local_only") is True:
            return None
        try:
            return self.publish(event.to_dict())
        except RedisError:
            logger.exception("Redis Streams publish unconfirmed")
            return None

    def _decode(self, entries: Any) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for raw_id, fields in entries:
            msg_id = _text(raw_id)
            payload = fields.get(b"payload", fields.get("payload"))
            try:
                msg = json.loads(payload)
                if not isinstance(msg, dict):
                    raise ValueError("expected event object")
                msg["_msg_id"] = msg_id
                messages.append(msg)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                # Preserve invalid data for inspection; ACK only with DLQ insertion.
                self.send_to_dlq(
                    {"reason": "invalid_stream_payload", "raw_payload": repr(payload)}, msg_id
                )
        return messages

    def consume(self, count: int = 100, block_ms: int = 5000) -> list[dict[str, Any]]:
        """Manual compatibility API. Valid messages are never auto-ACKed."""
        if self._redis is None:
            return []
        self._ensure_group()
        result = self._redis.xreadgroup(
            CONSUMER_GROUP, self._consumer_id, {STREAM_KEY: ">"}, count=count, block=block_ms
        )
        return [msg for _, entries in result for msg in self._decode(entries)]

    def _recover_one(self) -> list[dict[str, Any]]:
        self._ensure_group()
        result = self._redis.xautoclaim(
            STREAM_KEY, CONSUMER_GROUP, self._consumer_id,
            min_idle_time=CLAIM_IDLE_MS, start_id=self._claim_cursor, count=1,
        )
        self._claim_cursor = _text(result[0])
        if len(result) > 2 and result[2]:
            logger.error("Redis Streams PEL entries were deleted before recovery: %s", result[2])
        return self._decode(result[1])

    def ack(self, msg_id: str) -> bool:
        if self._redis is None:
            return False
        acknowledged = bool(
            self._redis.eval(_ACK, 1, STREAM_KEY, CONSUMER_GROUP, msg_id, self._consumer_id)
        )
        if acknowledged:
            self.trim_acknowledged()
        return acknowledged

    def trim_acknowledged(self) -> int:
        """Trim the ACKed prefix safe for every existing consumer group.

        Redis maintenance failure is fail-closed and cannot undo an existing
        fenced ACK. Slow or pending groups retain their original payloads.
        """
        if self._redis is None:
            return 0
        from redis.exceptions import RedisError

        try:
            return int(self._redis.eval(_SAFE_TRIM, 1, STREAM_KEY, MAXLEN, TRIM_BATCH))
        except RedisError:
            logger.warning("safe stream trim failed; retaining backlog", exc_info=True)
            return 0

    def _renew(self, msg_id: str) -> bool:
        return bool(self._redis.eval(
            _RENEW, 1, STREAM_KEY, CONSUMER_GROUP, msg_id, self._consumer_id
        ))

    def send_to_dlq(self, event_dict: dict[str, Any], original_msg_id: str) -> bool:
        if self._redis is None:
            return False
        # Preserve atomic DLQ insertion and fenced XACK; trim after success.
        acknowledged = bool(self._redis.eval(
            _DEAD_LETTER, 2, STREAM_KEY, DLQ_KEY, CONSUMER_GROUP,
            original_msg_id, self._consumer_id, json.dumps(event_dict, ensure_ascii=False),
        ))
        if acknowledged:
            self.trim_acknowledged()
        return acknowledged

    def _delivery_count(self, msg_id: str) -> int:
        rows = self._redis.xpending_range(
            STREAM_KEY, CONSUMER_GROUP, min=msg_id, max=msg_id, count=1
        )
        return int(rows[0]["times_delivered"]) if rows else 0

    async def _run(self) -> None:
        from redis.exceptions import RedisError

        assert self._stop is not None
        delay = 0.25
        while not self._stop.is_set():
            try:
                messages = await asyncio.to_thread(self._recover_one)
                if not messages and not self._stop.is_set():
                    messages = await asyncio.to_thread(self.consume, 1, 1000)
                if self._stop.is_set():
                    break
                for message in messages:
                    await self._deliver(message)
                delay = 0.25
            except RedisError:
                self._group_ready = False
                logger.exception("Redis Streams consumer disconnected; pending messages retained")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    delay = min(delay * 2, 5.0)

    async def _deliver(self, message: dict[str, Any]) -> None:
        assert self._stop is not None
        msg_id = message["_msg_id"]
        data = {key: value for key, value in message.items() if key != "_msg_id"}
        try:
            if (
                not isinstance(data.get("event_type"), str)
                or not data["event_type"]
                or not isinstance(data.get("payload"), dict)
            ):
                raise ValueError("invalid event type or payload")
            if (
                not isinstance(data.get("metadata"), dict)
                or not isinstance(data["metadata"].get("event_id"), str)
                or not data["metadata"]["event_id"]
            ):
                raise ValueError("missing stable event identity")
            event = NeuroEvent.from_dict(data, preserve_queue_identity=True)
            # Poison data must not terminate the dispatcher after admission.
            meta = event.metadata
            if (
                not isinstance(meta.domain, str)
                or (meta.dedup_key is not None and not isinstance(meta.dedup_key, str))
                or not math.isfinite(meta.timestamp)
                or not math.isfinite(meta.timeout_ms)
            ):
                raise ValueError("invalid event metadata")
            expired = event.is_expired()
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            await asyncio.to_thread(
                self.send_to_dlq, {"reason": "invalid_event", "event": data}, msg_id
            )
            return
        if expired:
            await asyncio.to_thread(self.send_to_dlq, {"reason": "expired", "event": data}, msg_id)
            return

        # Claim ownership before entering the existing bus queue, and keep it
        # alive while processing. Delivery remains at-least-once across crashes.
        if not await asyncio.to_thread(self._renew, msg_id):
            return
        delivery = asyncio.create_task(self._bus.deliver_stream_event(event))
        stopping = asyncio.create_task(self._stop.wait())
        try:
            while not delivery.done():
                done, _ = await asyncio.wait(
                    (delivery, stopping), timeout=CLAIM_IDLE_MS / 3000,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stopping in done:
                    return
                if not delivery.done() and not await asyncio.to_thread(self._renew, msg_id):
                    logger.warning("Redis Streams ownership lost for %s", msg_id)
                    return
            if self._stop.is_set():
                return
            outcome = delivery.result()
            if outcome == "handled":
                await asyncio.to_thread(self.ack, msg_id)
            elif outcome == "retry":
                if await asyncio.to_thread(self._delivery_count, msg_id) >= MAX_DELIVERIES:
                    await asyncio.to_thread(
                        self.send_to_dlq,
                        {"reason": "admission_retry_exhausted", "event": data},
                        msg_id,
                    )
            else:
                # Handler failure can have partial side effects. Preserve it for
                # reconciliation; do not blindly re-execute all handlers.
                await asyncio.to_thread(
                    self.send_to_dlq, {"reason": outcome, "event": data}, msg_id
                )
        finally:
            for task in (delivery, stopping):
                if not task.done():
                    task.cancel()
            await asyncio.gather(delivery, stopping, return_exceptions=True)
