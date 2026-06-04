"""用户行为埋点路由（阶段 7：可观察性闭环）。

前端/桌面端通过 ``POST /api/analytics/event`` 上报轻量用户行为事件，
事件落到 Prometheus ``user_events_total`` 指标，供产品决策（漏斗 / 留存 / 功能使用）。

设计原则：
- 极简、永不抛错给调用方（埋点失败不应影响用户操作）。
- 不存储 PII；tenant_id 仅作多租户聚合维度。
- 高基数防护：event/surface 长度截断 + 数量限制。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.utils.metrics import record_user_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_MAX_BATCH = 50
_MAX_LABEL_LEN = 64


def _clean(value: object, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return text[:_MAX_LABEL_LEN]


@router.post("/event")
def track_event(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """上报单个用户行为事件。

    Body: ``{"event": "click_export", "surface": "web", "tenant_id": "t1"}``
    """
    try:
        record_user_event(
            event=_clean(body.get("event"), "unknown"),
            surface=_clean(body.get("surface"), "unknown"),
            tenant_id=_clean(body.get("tenant_id"), "default"),
        )
        return JSONResponse({"success": True})
    except Exception as e:  # 埋点不可影响主流程
        logger.debug("analytics event ignored: %s", e)
        return JSONResponse({"success": True, "degraded": True})


@router.post("/events")
def track_events_batch(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """批量上报用户行为事件（前端节流后一次性提交）。"""
    events = body.get("events") or []
    if not isinstance(events, list):
        return JSONResponse({"success": False, "message": "events 必须为数组"}, status_code=400)
    accepted = 0
    for item in events[:_MAX_BATCH]:
        if not isinstance(item, dict):
            continue
        try:
            record_user_event(
                event=_clean(item.get("event"), "unknown"),
                surface=_clean(item.get("surface"), "unknown"),
                tenant_id=_clean(item.get("tenant_id"), "default"),
            )
            accepted += 1
        except Exception:
            continue
    return JSONResponse({"success": True, "accepted": accepted})
