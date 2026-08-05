"""MODstore 订单事件桥接：payment.paid → FHD NeuroBus + 回款核销样板。

实现 `AI_EMPLOYEE_ORDER_HANDLING_SSOT.md` §6 P0-3：让「支付成功」事件进入 FHD 编排层，
消除「AI 不知道订单」断点。消费方依据 `PAYMENT_CONTRACT.md` §4 envelope 契约，
禁止在桥接层自定义事件格式。

职责：
  1. 验签（HMAC-SHA256，见 PAYMENT_CONTRACT HTTP 投递头）。
  2. 解析 `payment.paid` envelope 并校验必填字段。
  3. 幂等去重（envelope.id = "<type>:<aggregate_id>"）。
  4. 发布 `order.paid` 到 FHD NeuroBus。
  5. 履约样板：自动挂回款核销，把订单串进客户流水线（闭环终点）。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

PAID_EVENT_TYPE = "payment.paid"
REQUIRED_PAID_FIELDS = ("out_trade_no", "user_id", "subject", "total_amount")


def bridge_secret() -> str:
    """WEBHOOK secret；未配置时跳过校验（本地/沙箱）。"""
    return (os.environ.get("MODSTORE_ORDER_WEBHOOK_SECRET") or "").strip()


def verify_signature(
    raw: bytes,
    signature: str | None,
    *,
    timestamp: str | None = None,
    event_id: str | None = None,
) -> bool:
    """校验 `X-Modstore-Webhook-Signature: sha256=<hmac>` 头。

    与 MODstore ``webhook_dispatcher._signature`` 保持一致：
    ``HMAC-SHA256(secret, "{timestamp}.{event_id}.{body}")``。
    """
    secret = bridge_secret()
    if not secret:
        logger.info(
            "modstore webhook 未配置 MODSTORE_ORDER_WEBHOOK_SECRET，跳过验签 (event_id=%s)",
            event_id,
        )
        return True
    if not signature:
        logger.warning(
            "modstore webhook 缺少 X-Modstore-Webhook-Signature 头 (event_id=%s)", event_id
        )
        return False
    msg = f"{timestamp or ''}.{event_id or ''}.".encode("utf-8") + raw
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    sig = signature.replace("sha256=", "").strip()
    ok = hmac.compare_digest(expected, sig)
    if ok:
        logger.info("modstore webhook 验签通过 (event_id=%s)", event_id)
    else:
        logger.warning(
            "modstore webhook 验签失败 (event_id=%s, timestamp=%s)", event_id, timestamp
        )
    return ok


def event_dedup_key(envelope: dict[str, Any]) -> str:
    """幂等键：优先 envelope.id，回退 aggregate_id。"""
    return str(envelope.get("id") or envelope.get("aggregate_id") or "").strip()


def _seen_dedup() -> set[str]:
    """进程内幂等缓存（生产可外化为 event_store/dedup）。"""
    cache = getattr(_seen_dedup, "_cache", None)
    if cache is None:
        cache = set()
        _seen_dedup._cache = cache
    return cache


def parse_paid_envelope(envelope: dict[str, Any]) -> dict[str, Any] | None:
    """按 PAYMENT_CONTRACT §4 解析 `payment.paid` envelope，返回 data 或 None。"""
    if not isinstance(envelope, dict):
        logger.warning("modstore webhook body 非 dict: %r", type(envelope).__name__)
        return None
    if envelope.get("type") != PAID_EVENT_TYPE:
        logger.warning(
            "modstore webhook 事件类型不符，期望 %s 实际 %r",
            PAID_EVENT_TYPE,
            envelope.get("type"),
        )
        return None
    data = envelope.get("data")
    if not isinstance(data, dict):
        logger.warning("modstore webhook envelope.data 非 dict (id=%s)", envelope.get("id"))
        return None
    for field in REQUIRED_PAID_FIELDS:
        if field not in data:
            logger.warning("payment.paid 缺必填字段 %s (id=%s)", field, envelope.get("id"))
            return None
    logger.info(
        "modstore webhook 解析成功 type=%s id=%s out_trade_no=%s",
        PAID_EVENT_TYPE,
        envelope.get("id"),
        data.get("out_trade_no"),
    )
    return data


def emit_paid_event(data: dict[str, Any]) -> bool:
    """发布 `order.paid` 到 FHD NeuroBus；总线不可用时降级为日志（不阻断）。"""
    try:
        from app.neuro_bus.bus import get_neuro_bus
        from app.neuro_bus.events.base import NeuroEvent

        event = (
            NeuroEvent(
                event_type="order.paid",
                payload={
                    "out_trade_no": data["out_trade_no"],
                    "user_id": data.get("user_id"),
                    "subject": data.get("subject", ""),
                    "total_amount": data.get("total_amount", ""),
                    "order_kind": data.get("order_kind", ""),
                    "_source": "modstore-payment.paid",
                },
            )
            .with_source("modstore")
            .with_domain("order")
        )
        ok = bool(get_neuro_bus().publish(event))
        if ok:
            logger.info("order.paid 已发布到 NeuroBus (out_trade_no=%s)", data["out_trade_no"])
        else:
            logger.warning(
                "order.paid 发布到 NeuroBus 返回 False (out_trade_no=%s)", data["out_trade_no"]
            )
        return ok
    except Exception:
        logger.exception("emit order.paid failed out_trade_no=%s", data.get("out_trade_no"))
        return False


def _record_reconciliation_if_user(data: dict[str, Any]) -> None:
    """履约样板：payment.paid → 自动挂回款核销，把订单串进客户流水线。"""
    try:
        uid = int(data.get("user_id") or 0)
        if uid <= 0:
            logger.info("payment.paid 无 user_id，跳过核销: %s", data["out_trade_no"])
            return
        from app.services.user_cs_pipeline import record_reconciliation

        record_reconciliation(
            uid,
            amount_yuan=str(data.get("total_amount") or ""),
            order_ref=str(data["out_trade_no"]),
            source="order_bridge:payment.paid",
        )
        logger.info(
            "payment.paid 已挂回款核销 user_id=%s out_trade_no=%s amount=%s",
            uid,
            data.get("out_trade_no"),
            data.get("total_amount"),
        )
    except Exception:
        logger.exception("record_reconciliation failed out_trade_no=%s", data["out_trade_no"])


def ingest_paid_event(
    envelope: dict[str, Any],
    *,
    hmac_signature: str | None = None,
    raw: bytes | None = None,
    timestamp: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """处理一个 `payment.paid` envelope，返回处理结果。"""
    if raw is not None and hmac_signature is not None:
        if not verify_signature(
            raw, hmac_signature, timestamp=timestamp, event_id=event_id
        ):
            logger.warning(
                "ingest_paid_event 拒绝：验签失败 (event_id=%s)", event_id
            )
            return {"accepted": False, "reason": "invalid_signature"}

    data = parse_paid_envelope(envelope)
    if data is None:
        logger.warning("ingest_paid_event 拒绝：envelope 无效 (event_id=%s)", event_id)
        return {"accepted": False, "reason": "invalid_envelope"}

    dkey = event_dedup_key(envelope)
    if dkey and dkey in _seen_dedup():
        logger.info(
            "ingest_paid_event 幂等去重命中，跳过 (dkey=%s out_trade_no=%s)",
            dkey,
            data["out_trade_no"],
        )
        return {
            "accepted": True,
            "deduped": True,
            "out_trade_no": data["out_trade_no"],
        }
    if dkey:
        _seen_dedup().add(dkey)

    emitted = emit_paid_event(data)
    _record_reconciliation_if_user(data)
    logger.info(
        "ingest_paid_event 处理完成 out_trade_no=%s emitted=%s",
        data["out_trade_no"],
        emitted,
    )
    return {
        "accepted": True,
        "deduped": False,
        "emitted": emitted,
        "out_trade_no": data["out_trade_no"],
    }


__all__ = [
    "PAID_EVENT_TYPE",
    "bridge_secret",
    "event_dedup_key",
    "ingest_paid_event",
    "parse_paid_envelope",
    "verify_signature",
]
