"""
Report Domain Event Handlers

报表领域事件处理器（端到端编排链路第 4 段）：
- ``report.monthly_summary_requested``：调用
  ``generate_monthly_finance_summary`` 生成月度财务汇总；成功发布
  ``report.monthly_summary_generated``，失败发布
  ``report.monthly_summary_failed``。

设计要点：
- 所有 handler 必须 try/except，绝不抛出异常崩溃 NeuroBus dispatch loop。
- ``generate_monthly_finance_summary`` 来自
  ``app.application.monthly_report_scheduler``，由于 ``app.services`` 包存在
  循环导入，采用模块级占位 + 延迟导入模式，便于测试 patch（参考
  ``inventory_domain_handlers.py`` 同模式）。
"""

from __future__ import annotations

import logging
from typing import Any

from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.domains.report_domain import (
    REPORT_MONTHLY_SUMMARY_FAILED,
    REPORT_MONTHLY_SUMMARY_GENERATED,
)
from app.neuro_bus.events.base import EventPriority, NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 模块级占位：测试通过 patch("...generate_monthly_finance_summary") 替换；
# 生产环境在 handler 内延迟导入，规避 app.services 包级循环导入。
generate_monthly_finance_summary = None


# ---------------------------------------------------------------------------
# 工具：发布事件（模块级，便于在异步 handler 中调用）
# ---------------------------------------------------------------------------
def _publish_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "ReportServiceDomain",
    priority: EventPriority = EventPriority.NORMAL,
) -> str:
    """发布 NeuroBus 事件；失败不抛异常，返回空字符串。"""
    # 延迟导入：避免模块级绑定导致测试 patch 不生效（test isolation）
    from app.neuro_bus.bus import get_neuro_bus

    try:
        bus = get_neuro_bus()
        event = NeuroEvent(
            event_type=event_type,
            payload=payload,
            source=source,
            priority=priority,
        )
        bus.publish(event)
        return event.metadata.event_id
    except RECOVERABLE_ERRORS as exc:
        logger.warning("发布事件失败 %s: %s", event_type, exc)
        return ""


def _resolve_generator():
    """返回月报生成函数：优先模块级（测试 patch），其次延迟导入。"""
    gen = generate_monthly_finance_summary
    if gen is not None:
        return gen
    from app.application.monthly_report_scheduler import (
        generate_monthly_finance_summary as _lazy_gen,
    )

    return _lazy_gen


# ---------------------------------------------------------------------------
# Handler: report.monthly_summary_requested → generate_monthly_finance_summary
# ---------------------------------------------------------------------------
async def handle_monthly_summary_requested(event: NeuroEvent) -> dict[str, Any]:
    """消费 ``report.monthly_summary_requested``：生成月度财务汇总。

    流程：
    1. 从 event payload 读取 tenant_id / year / month
    2. 调用 ``generate_monthly_finance_summary(tenant_id, year, month)``（位置参数）
    3. 成功 → 发布 ``report.monthly_summary_generated``（带 summary）
    4. 失败 → 发布 ``report.monthly_summary_failed``（带 error）

    任何异常都被捕获，绝不抛出。
    """
    payload = dict(event.payload or {})
    tenant_id = payload.get("tenant_id")
    year = payload.get("year")
    month = payload.get("month")

    logger.info(
        "[ReportServiceDomain] 处理 monthly_summary_requested: tenant=%s year=%s month=%s",
        tenant_id,
        year,
        month,
    )

    # 解析生成函数（支持测试 patch）
    try:
        gen_fn = _resolve_generator()
    except RECOVERABLE_ERRORS as exc:
        logger.exception(
            "[ReportServiceDomain] generate_monthly_finance_summary 延迟导入失败: %s",
            exc,
        )
        _publish_event(
            REPORT_MONTHLY_SUMMARY_FAILED,
            {
                "tenant_id": tenant_id,
                "year": year,
                "month": month,
                "error": f"import failed: {exc}",
                "stage": "import",
            },
            source="ReportServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": str(exc),
            "stage": "import",
            "tenant_id": tenant_id,
        }

    try:
        result = gen_fn(tenant_id, year, month)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 — 任何异常都不能崩溃总线
        logger.exception("[ReportServiceDomain] generate_monthly_finance_summary 抛异常: %s", exc)
        _publish_event(
            REPORT_MONTHLY_SUMMARY_FAILED,
            {
                "tenant_id": tenant_id,
                "year": year,
                "month": month,
                "error": str(exc),
                "stage": "generate",
            },
            source="ReportServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": str(exc),
            "stage": "generate",
            "tenant_id": tenant_id,
        }

    if not result.get("success"):
        error_msg = result.get("error") or "generate_monthly_finance_summary returned failure"
        logger.warning("[ReportServiceDomain] 月报生成业务失败: %s", error_msg)
        _publish_event(
            REPORT_MONTHLY_SUMMARY_FAILED,
            {
                "tenant_id": tenant_id,
                "year": year,
                "month": month,
                "error": error_msg,
                "stage": "business",
            },
            source="ReportServiceDomain",
            priority=EventPriority.HIGH,
        )
        return {
            "success": False,
            "error": error_msg,
            "stage": "business",
            "tenant_id": tenant_id,
        }

    generated_event_id = _publish_event(
        REPORT_MONTHLY_SUMMARY_GENERATED,
        {
            "tenant_id": tenant_id,
            "year": year,
            "month": month,
            "summary": result.get("summary", {}),
            "period": result.get("period", {}),
            "generated_at": result.get("generated_at"),
        },
        source="ReportServiceDomain",
    )

    logger.info(
        "[ReportServiceDomain] 月报已生成 tenant=%s year=%s month=%s event_id=%s",
        tenant_id,
        year,
        month,
        generated_event_id,
    )

    return {
        "success": True,
        "tenant_id": tenant_id,
        "year": year,
        "month": month,
        "summary": result.get("summary", {}),
        "generated_event_id": generated_event_id,
    }


# ---------------------------------------------------------------------------
# 注册入口（与 finance/inventory/ocr 等域保持一致的类形态）
# ---------------------------------------------------------------------------
class ReportServiceDomainHandlers:
    """Report 领域事件处理器（向后兼容类）"""

    def __init__(self):
        self.bus = get_neuro_bus()

    def register(self):
        """注册所有事件处理器"""
        self.bus.subscribe("report.monthly_summary_requested", handle_monthly_summary_requested)
        logger.info(
            "[ReportServiceDomain] 已注册 %d 个事件处理器",
            len(self.bus._handlers.get("report.monthly_summary_requested", [])),
        )


_handlers: ReportServiceDomainHandlers | None = None


def get_report_handlers() -> ReportServiceDomainHandlers:
    """获取领域处理器单例"""
    global _handlers
    if _handlers is None:
        _handlers = ReportServiceDomainHandlers()
    return _handlers


def register_report_domain_handlers(bus):
    """注册所有 Report 领域事件处理器到 NeuroBus"""
    handlers = get_report_handlers()
    handlers.register()
    logger.info("[ReportDomain] 所有事件处理器已注册")
