"""
月度财务报表调度器

提供：
- ``generate_monthly_finance_summary(tenant_id, year, month)``：汇总指定月份的
  入库单 / 审批 / 财务交易数据，返回结构化月报。
- ``schedule_monthly_job()``：注册 Celery beat 定时任务，每月 1 号 00:30 触发
  月报生成（发布 ``report.monthly_summary_requested`` 事件）。

设计要点：
- 仅依赖 ``app.db.session.get_db`` + SQLAlchemy 原生查询，避免触发
  ``app.services`` 包级循环导入。
- ``generate_monthly_finance_summary`` 为纯查询函数，无副作用，便于单测 mock。
- ``schedule_monthly_job`` 通过 ``celery_app.conf.beat_schedule`` 注册，幂等。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.extensions import celery_app
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _month_range(year: int, month: int) -> tuple[date, date]:
    """返回某月的 [第一天, 下月第一天) 区间。"""
    if month < 1 or month > 12:
        raise ValueError(f"非法月份: {month}")
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def generate_monthly_finance_summary(
    tenant_id: int | None,
    year: int,
    month: int,
) -> dict[str, Any]:
    """生成月度财务汇总报表。

    汇总维度：
    - 入库单：当月入库总数、总金额、按状态分组的数量
    - 审批：当月审批记录数、通过/拒绝数
    - 财务交易：当月交易总数、按 transaction_type 分组的金额合计

    Args:
        tenant_id: 租户 ID（None 表示不分租户）
        year: 年份（如 2026）
        month: 月份（1-12）

    Returns:
        ``{"success": bool, "summary": {...}, "period": {...}}``
    """
    start, end = _month_range(year, month)

    summary: dict[str, Any] = {
        "total_inbound_amount": 0.0,
        "total_inbound_count": 0,
        "total_approved_count": 0,
        "total_rejected_count": 0,
        "total_approval_count": 0,
        "total_transaction_amount": 0.0,
        "total_transaction_count": 0,
        "by_inbound_status": {},
        "by_transaction_type": {},
    }

    try:
        from sqlalchemy import func

        from app.db.models import PurchaseInbound
        from app.db.models.approval import ApprovalRequest
        from app.db.models.finance import FinancialTransaction
        from app.db.session import get_db
    except RECOVERABLE_ERRORS as exc:
        logger.exception("[MonthlyReport] 模型导入失败: %s", exc)
        return {
            "success": False,
            "error": f"import failed: {exc}",
            "summary": summary,
            "period": {"year": year, "month": month, "tenant_id": tenant_id},
        }

    try:
        with get_db() as db:
            # 入库单汇总
            inbound_query = db.query(
                PurchaseInbound.status,
                func.count(PurchaseInbound.id).label("count"),
                func.coalesce(func.sum(PurchaseInbound.total_amount), 0).label(
                    "amount"
                ),
            ).filter(
                PurchaseInbound.inbound_date >= start,
                PurchaseInbound.inbound_date < end,
            )
            if tenant_id is not None:
                inbound_query = inbound_query.filter(
                    PurchaseInbound.tenant_id == tenant_id
                )
            for status, count, amount in inbound_query.group_by(
                PurchaseInbound.status
            ).all():
                count = int(count or 0)
                amount = float(amount or 0)
                summary["by_inbound_status"][status or "unknown"] = {
                    "count": count,
                    "amount": amount,
                }
                summary["total_inbound_count"] += count
                summary["total_inbound_amount"] += amount
                if status == "approved":
                    summary["total_approved_count"] += count
                elif status == "rejected":
                    summary["total_rejected_count"] += count

            # 审批汇总
            approval_query = db.query(
                ApprovalRequest.status,
                func.count(ApprovalRequest.id).label("count"),
            ).filter(
                ApprovalRequest.submitted_at >= start,
                ApprovalRequest.submitted_at < end,
            )
            if tenant_id is not None:
                approval_query = approval_query.filter(
                    ApprovalRequest.tenant_id == tenant_id
                )
            approval_count = 0
            for status, count in approval_query.group_by(
                ApprovalRequest.status
            ).all():
                approval_count += int(count or 0)
            summary["total_approval_count"] = approval_count

            # 财务交易汇总
            tx_query = db.query(
                FinancialTransaction.transaction_type,
                func.count(FinancialTransaction.id).label("count"),
                func.coalesce(func.sum(FinancialTransaction.amount), 0).label(
                    "amount"
                ),
            ).filter(
                FinancialTransaction.transaction_date >= start,
                FinancialTransaction.transaction_date < end,
            )
            if tenant_id is not None:
                tx_query = tx_query.filter(
                    FinancialTransaction.tenant_id == tenant_id
                )
            for tx_type, count, amount in tx_query.group_by(
                FinancialTransaction.transaction_type
            ).all():
                count = int(count or 0)
                amount = float(amount or 0)
                summary["by_transaction_type"][tx_type or "unknown"] = {
                    "count": count,
                    "amount": amount,
                }
                summary["total_transaction_count"] += count
                summary["total_transaction_amount"] += amount

    except RECOVERABLE_ERRORS as exc:
        logger.exception("[MonthlyReport] 查询失败: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "summary": summary,
            "period": {"year": year, "month": month, "tenant_id": tenant_id},
        }

    return {
        "success": True,
        "summary": summary,
        "period": {
            "year": year,
            "month": month,
            "tenant_id": tenant_id,
            "start_date": start.isoformat(),
            "end_date": (end - timedelta(days=1)).isoformat(),
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Celery beat 定时任务
# ---------------------------------------------------------------------------
@celery_app.task(name="monthly_report.generate_finance_summary")
def _monthly_finance_summary_task(
    tenant_id: int | None = None, year: int | None = None, month: int | None = None
) -> dict[str, Any]:
    """Celery 任务：生成月度财务汇总并发布 ``report.monthly_summary_generated``。

    未传 year/month 时默认取上个月（每月 1 号 00:30 跑时即上月数据）。
    """
    if year is None or month is None:
        today = date.today()
        first_of_month = today.replace(day=1)
        last_month = first_of_month - timedelta(days=1)
        year = year or last_month.year
        month = month or last_month.month

    logger.info(
        "[MonthlyReport] Celery beat 触发: tenant=%s year=%s month=%s",
        tenant_id,
        year,
        month,
    )

    result = generate_monthly_finance_summary(tenant_id, year, month)

    # 发布 NeuroBus 事件（成功/失败均发布）
    try:
        from app.neuro_bus.bus import get_neuro_bus
        from app.neuro_bus.events.base import NeuroEvent

        bus = get_neuro_bus()
        event_type = (
            "report.monthly_summary_generated"
            if result.get("success")
            else "report.monthly_summary_failed"
        )
        event = NeuroEvent(
            event_type=event_type,
            payload={
                "tenant_id": tenant_id,
                "year": year,
                "month": month,
                "result": result,
            },
            source="MonthlyReportScheduler",
        )
        bus.publish(event)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("[MonthlyReport] 发布事件失败: %s", exc)

    return result


def schedule_monthly_job(
    *, tenant_id: int | None = None, hour: int = 0, minute: int = 30
) -> None:
    """注册每月 1 号 ``hour:minute`` 触发的 Celery beat 任务（幂等）。

    默认 00:30，覆盖月初零点高峰。

    使用 ``celery_app.conf.beat_schedule`` 注册；同 key 重复注册会覆盖旧值。
    """
    try:
        from celery.schedules import crontab
    except ImportError:
        # celery 未安装（_CeleryStub 环境），跳过注册
        logger.info("[MonthlyReport] celery 未安装，跳过 beat 注册")
        return

    schedule_key = "monthly-report-finance-summary"
    celery_app.conf.beat_schedule = {
        **getattr(celery_app.conf, "beat_schedule", {}),
        schedule_key: {
            "task": "monthly_report.generate_finance_summary",
            "schedule": crontab(hour=hour, minute=minute, day_of_month=1),
            "kwargs": {"tenant_id": tenant_id},
        },
    }
    logger.info(
        "[MonthlyReport] 已注册 beat schedule: %s @ 每月1日 %02d:%02d",
        schedule_key,
        hour,
        minute,
    )


__all__ = [
    "generate_monthly_finance_summary",
    "schedule_monthly_job",
]
