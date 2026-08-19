"""战略层周报/月报自动产出服务。

基于 ``daily_digest_records`` 表 + ``strategic_decisions`` + ``strategic_action_items``
+ ``incident_events`` 聚合，自动产出战略层周报（每周一）和月报（每月 1 日）。

报告结构：
- ``content_md``：Markdown 战略级摘要（趋势、风险、建议）
- ``metrics_json``：聚合指标（覆盖率、CI、loop、部署、决策、action items、incident）
- ``risks_json``：风险预警列表
- ``recommendations_json``：下周/月建议列表
- ``source_digest_ids_json``：覆盖期间的 daily_digest_record IDs

触发方式：
- APScheduler 每周一 09:00 UTC 触发 ``generate_weekly_report``
- APScheduler 每月 1 日 10:00 UTC 触发 ``generate_monthly_report``
- 也可通过 API ``POST /api/xcmax/strategic/reports/weekly`` 手动触发
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, select

from modstore_server.db.base import get_session_factory
from modstore_server.db.strategic import StrategicReport as StrategicReportModel
from modstore_server.strategic_layer.strategic_report_analysis import (
    StrategicReportAnalysisMixin,
)

logger = logging.getLogger(__name__)


@dataclass
class WeeklyReportPeriod:
    """周报周期值对象（ISO 周一为起始）。"""

    year: int
    week: int
    start_date: date
    end_date: date

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def weekly_report_key(year: int, week: int) -> str:
    """周报唯一键：``weekly:2026-W29``。"""
    return f"weekly:{year}-W{week:02d}"


def monthly_report_key(year: int, month: int) -> str:
    """月报唯一键：``monthly:2026-07``。"""
    return f"monthly:{year}-{month:02d}"


def _iso_week_of(d: date) -> Tuple[int, int]:
    """返回 ``(year, week)``，按 ISO 8601 周日历（周一为起始）。"""
    iso_year, iso_week, _ = d.isocalendar()
    return iso_year, iso_week


def _week_period(d: Optional[date] = None) -> WeeklyReportPeriod:
    """计算 ``d`` 所在周的 ``WeeklyReportPeriod``（默认本周）。

    ISO 周一为起始，周日为结束。
    """
    if d is None:
        d = datetime.now(timezone.utc).date()
    iso_year, iso_week = _iso_week_of(d)
    # 周一 = d - weekday() 天（date.weekday() 周一=0）
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return WeeklyReportPeriod(year=iso_year, week=iso_week, start_date=monday, end_date=sunday)


def _month_range(year: int, month: int) -> Tuple[date, date]:
    """返回月份的 ``(first_day, last_day)``。"""
    first = date(year, month, 1)
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return first, last


class StrategicReportService(StrategicReportAnalysisMixin):
    """战略层周报/月报自动产出服务。"""

    def __init__(
        self,
        *,
        session_factory: Any = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory

    # ---------------- 周报 ----------------

    def generate_weekly_report(
        self,
        *,
        target_date: Optional[date] = None,
        actor: str = "ai-strategist",
    ) -> Dict[str, Any]:
        """生成周报（默认本周；幂等：若已存在则覆盖内容）。

        Args:
            target_date: 目标日期（默认今天）；周报覆盖该日所在 ISO 周
            actor: 生成者标识

        Returns:
            报告字典（含 ``report_key`` / ``metrics`` / ``content_md`` / ``risks`` / ``recommendations``）
        """
        period = _week_period(target_date)
        report_key = weekly_report_key(period.year, period.week)

        digest_ids, digest_metrics = self._collect_digest_metrics(
            period.start_date, period.end_date
        )
        decision_metrics = self._collect_decision_metrics(period.start_date, period.end_date)
        action_item_metrics = self._collect_action_item_metrics(period.start_date, period.end_date)
        incident_metrics = self._collect_incident_metrics(period.start_date, period.end_date)

        metrics: Dict[str, Any] = {
            "period": period.to_dict(),
            "digest_count": len(digest_ids),
            "digest": digest_metrics,
            "decisions": decision_metrics,
            "action_items": action_item_metrics,
            "incidents": incident_metrics,
        }
        risks = self._derive_risks(metrics)
        recommendations = self._derive_recommendations(metrics, risks)
        content_md = self._render_weekly_markdown(
            period=period,
            metrics=metrics,
            risks=risks,
            recommendations=recommendations,
        )

        return self._persist_report(
            report_key=report_key,
            report_type="weekly",
            period_start=period.start_date,
            period_end=period.end_date,
            content_md=content_md,
            metrics=metrics,
            risks=risks,
            recommendations=recommendations,
            source_digest_ids=digest_ids,
            actor=actor,
        )

    # ---------------- 月报 ----------------

    def generate_monthly_report(
        self,
        *,
        year: Optional[int] = None,
        month: Optional[int] = None,
        actor: str = "ai-strategist",
    ) -> Dict[str, Any]:
        """生成月报（默认上月；幂等：若已存在则覆盖内容）。"""
        today = datetime.now(timezone.utc).date()
        if year is None or month is None:
            # 默认上月
            first_of_this_month = date(today.year, today.month, 1)
            last_day_prev = first_of_this_month - timedelta(days=1)
            year = last_day_prev.year
            month = last_day_prev.month

        first_day, last_day = _month_range(year, month)
        report_key = monthly_report_key(year, month)

        digest_ids, digest_metrics = self._collect_digest_metrics(first_day, last_day)
        decision_metrics = self._collect_decision_metrics(first_day, last_day)
        action_item_metrics = self._collect_action_item_metrics(first_day, last_day)
        incident_metrics = self._collect_incident_metrics(first_day, last_day)

        metrics: Dict[str, Any] = {
            "period": {
                "year": year,
                "month": month,
                "start_date": first_day.isoformat(),
                "end_date": last_day.isoformat(),
            },
            "digest_count": len(digest_ids),
            "digest": digest_metrics,
            "decisions": decision_metrics,
            "action_items": action_item_metrics,
            "incidents": incident_metrics,
        }
        risks = self._derive_risks(metrics)
        recommendations = self._derive_recommendations(metrics, risks)
        content_md = self._render_monthly_markdown(
            year=year,
            month=month,
            first_day=first_day,
            last_day=last_day,
            metrics=metrics,
            risks=risks,
            recommendations=recommendations,
        )

        return self._persist_report(
            report_key=report_key,
            report_type="monthly",
            period_start=first_day,
            period_end=last_day,
            content_md=content_md,
            metrics=metrics,
            risks=risks,
            recommendations=recommendations,
            source_digest_ids=digest_ids,
            actor=actor,
        )

    # ---------------- 查询 ----------------

    def get_report(self, report_key: str) -> Optional[Dict[str, Any]]:
        session = self._session_factory()()
        try:
            row = session.execute(
                select(StrategicReportModel).where(StrategicReportModel.report_key == report_key)
            ).scalar_one_or_none()
            return _report_row_to_dict(row) if row else None
        finally:
            session.close()

    def list_reports(
        self,
        *,
        report_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        session = self._session_factory()()
        try:
            stmt = (
                select(StrategicReportModel)
                .order_by(desc(StrategicReportModel.period_start))
                .limit(max(1, min(limit, 200)))
            )
            if report_type is not None:
                stmt = stmt.where(StrategicReportModel.report_type == report_type)
            rows = session.execute(stmt).scalars().all()
            return [_report_row_to_dict(r) for r in rows]
        finally:
            session.close()

    # ---------------- 内部：数据采集 ----------------

    def _persist_report(
        self,
        *,
        report_key: str,
        report_type: str,
        period_start: date,
        period_end: date,
        content_md: str,
        metrics: Dict[str, Any],
        risks: List[Dict[str, Any]],
        recommendations: List[Dict[str, Any]],
        source_digest_ids: List[int],
        actor: str,
    ) -> Dict[str, Any]:
        session = self._session_factory()()
        try:
            row = session.execute(
                select(StrategicReportModel).where(StrategicReportModel.report_key == report_key)
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if row is None:
                row = StrategicReportModel(
                    report_key=report_key,
                    report_type=report_type,
                    period_start=period_start,
                    period_end=period_end,
                    content_md=content_md,
                    metrics_json=json.dumps(metrics, ensure_ascii=False, default=str),
                    risks_json=json.dumps(risks, ensure_ascii=False),
                    recommendations_json=json.dumps(recommendations, ensure_ascii=False),
                    source_digest_ids_json=json.dumps(source_digest_ids),
                    status="generated",
                    reviewed_by="",
                    reviewed_at=None,
                    review_notes="",
                    generated_by=actor,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.content_md = content_md
                row.metrics_json = json.dumps(metrics, ensure_ascii=False, default=str)
                row.risks_json = json.dumps(risks, ensure_ascii=False)
                row.recommendations_json = json.dumps(recommendations, ensure_ascii=False)
                row.source_digest_ids_json = json.dumps(source_digest_ids)
                row.generated_by = actor
                row.updated_at = now
            session.commit()
            logger.info(
                "strategic report persisted key=%s type=%s period=%s→%s",
                report_key,
                report_type,
                period_start.isoformat(),
                period_end.isoformat(),
            )
            return _report_row_to_dict(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _report_row_to_dict(row: StrategicReportModel) -> Dict[str, Any]:
    def _loads(s: str, default: Any) -> Any:
        if not s:
            return default
        try:
            return json.loads(s)
        except Exception:
            return default

    return {
        "id": row.id,
        "report_key": row.report_key,
        "report_type": row.report_type,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "content_md": row.content_md or "",
        "metrics": _loads(row.metrics_json, {}),
        "risks": _loads(row.risks_json, []),
        "recommendations": _loads(row.recommendations_json, []),
        "source_digest_ids": _loads(row.source_digest_ids_json, []),
        "status": row.status,
        "reviewed_by": row.reviewed_by or "",
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "review_notes": row.review_notes or "",
        "generated_by": row.generated_by or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


__all__ = [
    "StrategicReportService",
    "WeeklyReportPeriod",
    "monthly_report_key",
    "weekly_report_key",
]
