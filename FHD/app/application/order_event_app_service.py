"""MODstore 订单事件桥接门面：routes 经此访问 app.services.order_event_bridge。

保持架构依赖方向（routes → application → services），避免 webhook 路由直连 services 层。
"""

from __future__ import annotations

from typing import Any


def ingest_paid_event(
    envelope: dict[str, Any],
    *,
    hmac_signature: str | None = None,
    raw: bytes | None = None,
) -> dict[str, Any]:
    from app.services.order_event_bridge import ingest_paid_event as _ingest

    return _ingest(
        envelope,
        hmac_signature=hmac_signature,
        raw=raw,
    )


__all__ = ["ingest_paid_event"]
