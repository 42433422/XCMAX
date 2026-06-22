"""核心 app service 的 NeuroBus 真实落地消费者。

背景（2026-06-22 落地）：Application 层多个核心服务已在 default-ON 路径
（``XCAGI_NEURO_INTENT`` 默认开启）发布领域事件（``application.*``），但此前**没有任何
消费者**订阅这些精确 event_type —— 事件进入总线后命中 ``No handlers for event`` 被直接丢弃，
属于「只发布、无消费」的 SHALLOW 采用。

本模块为其中三个服务补齐**真实消费者 + 持久副作用**，使其达到「真实落地（REAL）」标准
（produce → consume → 持久 side-effect，且在运行期默认路径生效）：

- ``unit_products_import`` → ``application.products.imported``：持久落库 + 失效产品列表缓存。
- ``conversation``         → ``application.conversation.message_saved``：持久落库（会话消息投影）。
- ``customer``             → ``application.customer.changed``：持久落库 + 失效产品/客户读缓存。

副作用统一写入 :class:`app.db.models.neuro_event_log.NeuroEventLog`（应用主库，dev/test/prod
一致可用、可查询、可对账），不依赖仅在特定部署存在的 Redis；产品/客户缓存失效为**尽力而为**的
额外真实副作用（无 Redis 时安全 no-op）。消费者经 ``bus.subscribe(精确 event_type, handler)``
注册（与 Product 领域处理器同一机制），按 event_type 精确路由，与发布端一一对应。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 已对这些 engine（按 id 去重）确保过建表，避免每次事件都做一次反射检查。
_ensured_binds: set[int] = set()


def _persist_event_log(event: NeuroEvent, *, side_effect: str = "") -> int | None:
    """将一条已消费事件持久化到 ``neuro_event_log``，返回行 id（失败返回 None）。

    durable side-effect：写应用主库一行。表按需惰性创建（``checkfirst``），因此无需依赖
    ``init_db`` 的建表顺序，在 dev/test/prod 任意环境都成立。
    """
    try:
        from app.db import SessionLocal
        from app.db.models.neuro_event_log import NeuroEventLog

        meta = event.metadata
        with SessionLocal() as db:
            bind = db.get_bind()
            if bind is not None and id(bind) not in _ensured_binds:
                NeuroEventLog.__table__.create(bind=bind, checkfirst=True)
                _ensured_binds.add(id(bind))

            row = NeuroEventLog(
                created_at=datetime.now(),
                event_type=event.event_type,
                domain=(getattr(meta, "domain", "") or ""),
                source=(getattr(meta, "source", "") or ""),
                correlation_id=(getattr(meta, "correlation_id", "") or ""),
                payload=json.dumps(event.payload, ensure_ascii=False, default=str)[:4000],
                side_effect=side_effect,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            logger.debug(
                "[ApplicationConsumers] 持久化事件 %s -> neuro_event_log#%s",
                event.event_type,
                row.id,
            )
            return int(row.id)
    except RECOVERABLE_ERRORS as exc:  # 总线层已隔离，这里只保证不静默丢可观测性
        logger.warning(
            "[ApplicationConsumers] 持久化事件失败 type=%s: %s", event.event_type, exc
        )
        return None


def _invalidate_product_cache_best_effort() -> bool:
    """尽力失效产品读缓存（无 Redis 时安全 no-op）。返回是否成功调用失效。"""
    try:
        from app.services.products_service import ProductsService

        ProductsService()._invalidate_product_cache()
        return True
    except RECOVERABLE_ERRORS as exc:
        logger.debug("[ApplicationConsumers] 产品缓存失效跳过: %s", exc)
        return False


async def handle_products_imported(event: NeuroEvent) -> dict[str, Any]:
    """消费 ``application.products.imported``：持久落库 + 失效产品列表缓存。"""
    invalidated = _invalidate_product_cache_best_effort()
    row_id = _persist_event_log(
        event,
        side_effect="product_cache_invalidated" if invalidated else "persisted",
    )
    return {"success": row_id is not None, "event_log_id": row_id, "cache_invalidated": invalidated}


async def handle_conversation_message_saved(event: NeuroEvent) -> dict[str, Any]:
    """消费 ``application.conversation.message_saved``：持久落库（会话消息投影）。"""
    row_id = _persist_event_log(event, side_effect="persisted")
    return {"success": row_id is not None, "event_log_id": row_id}


async def handle_customer_changed(event: NeuroEvent) -> dict[str, Any]:
    """消费 ``application.customer.changed``：持久落库 + 失效产品/客户读缓存。

    客户增删改会影响以客户维度聚合的产品/单位列表缓存，故一并尽力失效。
    """
    invalidated = _invalidate_product_cache_best_effort()
    row_id = _persist_event_log(
        event,
        side_effect="customer_cache_invalidated" if invalidated else "persisted",
    )
    return {"success": row_id is not None, "event_log_id": row_id, "cache_invalidated": invalidated}


# 发布端 event_type → 消费者 的精确映射（与 application_neuro_bridge 的 _publish 一一对应）。
_CONSUMERS: tuple[tuple[str, Any], ...] = (
    ("application.products.imported", handle_products_imported),
    ("application.conversation.message_saved", handle_conversation_message_saved),
    ("application.customer.changed", handle_customer_changed),
)


def register_application_event_consumers(bus) -> int:
    """注册三个核心 app service 的真实消费者到总线。返回注册数量。"""
    count = 0
    for event_type, handler in _CONSUMERS:
        bus.subscribe(event_type, handler)
        count += 1
    logger.info(
        "[ApplicationConsumers] 已注册 %s 个核心 app service 消费者: %s",
        count,
        ", ".join(t for t, _ in _CONSUMERS),
    )
    return count
