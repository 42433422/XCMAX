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
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, func, select

from modstore_server.db.base import get_session_factory
from modstore_server.db.strategic import (
    StrategicActionItem,
    StrategicDecision as StrategicDecisionModel,
    StrategicReport as StrategicReportModel,
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


class StrategicReportService:
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

    def _collect_digest_metrics(
        self,
        start: date,
        end: date,
    ) -> Tuple[List[int], Dict[str, Any]]:
        """从 ``daily_digest_records`` 聚合期间内的指标。

        使用容错字段读取（不同 schema 演进版本可能有不同字段）。
        """
        session = self._session_factory()()
        try:
            # daily_digest_records 表的 day 字段是 'YYYY-MM-DD' 字符串
            start_str = start.isoformat()
            end_str = end.isoformat()
            try:
                from modstore_server.models import DailyDigestRecord
            except ImportError:
                return [], {"note": "DailyDigestRecord model unavailable"}

            stmt = (
                select(DailyDigestRecord)
                .where(DailyDigestRecord.day >= start_str)
                .where(DailyDigestRecord.day <= end_str)
                .order_by(DailyDigestRecord.day)
            )
            rows = session.execute(stmt).scalars().all()
            ids = [int(r.id) for r in rows if r.id is not None]
            metrics: Dict[str, Any] = {
                "total": len(rows),
                "days": [r.day for r in rows if getattr(r, "day", None)],
            }
            # 容错读取可能的字段
            for field_name in (
                "release_kind",
                "release_train_before",
                "release_train_after",
            ):
                values = [getattr(r, field_name, "") for r in rows if getattr(r, field_name, None)]
                if values:
                    metrics[field_name] = values
            return ids, metrics
        except Exception as exc:
            logger.warning("collect_digest_metrics failed: %s", exc)
            return [], {"error": str(exc)}
        finally:
            session.close()

    def _collect_decision_metrics(self, start: date, end: date) -> Dict[str, Any]:
        """聚合 ``strategic_decisions`` 表指标。"""
        session = self._session_factory()()
        try:
            start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
            end_dt = datetime.combine(
                end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
            )

            rows = (
                session.execute(
                    select(StrategicDecisionModel)
                    .where(StrategicDecisionModel.proposed_at >= start_dt)
                    .where(StrategicDecisionModel.proposed_at < end_dt)
                )
                .scalars()
                .all()
            )

            total = len(rows)
            by_status: Dict[str, int] = {}
            by_decided_by: Dict[str, int] = {}
            by_autonomy_action: Dict[str, int] = {}
            for r in rows:
                by_status[r.status] = by_status.get(r.status, 0) + 1
                if r.decided_by:
                    by_decided_by[r.decided_by] = by_decided_by.get(r.decided_by, 0) + 1
                if r.autonomy_action:
                    by_autonomy_action[r.autonomy_action] = (
                        by_autonomy_action.get(r.autonomy_action, 0) + 1
                    )

            return {
                "total": total,
                "by_status": by_status,
                "by_decided_by": by_decided_by,
                "by_autonomy_action": by_autonomy_action,
                "auto_approved_rate": (
                    by_status.get("auto_approved", 0)
                    + by_status.get("completed", 0)
                    + by_status.get("executing", 0)
                )
                / max(total, 1),
            }
        except Exception as exc:
            logger.warning("collect_decision_metrics failed: %s", exc)
            return {"error": str(exc)}
        finally:
            session.close()

    def _collect_action_item_metrics(self, start: date, end: date) -> Dict[str, Any]:
        """聚合 ``strategic_action_items`` 表指标。"""
        session = self._session_factory()()
        try:
            start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
            end_dt = datetime.combine(
                end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
            )

            rows = (
                session.execute(
                    select(StrategicActionItem)
                    .where(StrategicActionItem.created_at >= start_dt)
                    .where(StrategicActionItem.created_at < end_dt)
                )
                .scalars()
                .all()
            )

            total = len(rows)
            by_status: Dict[str, int] = {}
            by_assignee: Dict[str, int] = {}
            overdue = 0
            now = datetime.now(timezone.utc)
            for r in rows:
                by_status[r.status] = by_status.get(r.status, 0) + 1
                by_assignee[r.assigned_to] = by_assignee.get(r.assigned_to, 0) + 1
                if r.status not in ("completed", "cancelled") and r.due_at and r.due_at < now:
                    overdue += 1

            return {
                "total": total,
                "by_status": by_status,
                "by_assignee": by_assignee,
                "overdue": overdue,
                "completion_rate": by_status.get("completed", 0) / max(total, 1),
            }
        except Exception as exc:
            logger.warning("collect_action_item_metrics failed: %s", exc)
            return {"error": str(exc)}
        finally:
            session.close()

    def _collect_incident_metrics(self, start: date, end: date) -> Dict[str, Any]:
        """聚合 ``incident_events`` 表指标（容错）。"""
        session = self._session_factory()()
        try:
            try:
                from modstore_server.models import IncidentEvent
            except ImportError:
                return {"note": "IncidentEvent model unavailable"}

            start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
            end_dt = datetime.combine(
                end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
            )
            count = (
                session.execute(
                    select(func.count(IncidentEvent.id))
                    .where(IncidentEvent.created_at >= start_dt)
                    .where(IncidentEvent.created_at < end_dt)
                ).scalar()
                or 0
            )

            return {"total": int(count)}
        except Exception as exc:
            logger.warning("collect_incident_metrics failed: %s", exc)
            return {"error": str(exc)}
        finally:
            session.close()

    # ---------------- 内部：风险与建议 ----------------

    def _derive_risks(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从聚合指标推导风险预警。"""
        risks: List[Dict[str, Any]] = []
        decisions = metrics.get("decisions", {}) or {}
        action_items = metrics.get("action_items", {}) or {}

        # 风险 1：决策通过率低
        total_decisions = int(decisions.get("total", 0) or 0)
        if total_decisions >= 5:
            by_status = decisions.get("by_status", {}) or {}
            rejected = int(by_status.get("rejected", 0) or 0)
            rejection_rate = rejected / total_decisions
            if rejection_rate > 0.3:
                risks.append(
                    {
                        "id": "high-rejection-rate",
                        "severity": "high",
                        "description": f"决策否决率 {rejection_rate:.0%}（{rejected}/{total_decisions}）",
                        "suggestion": "复盘否决原因，校准提议质量或边界规则",
                    }
                )

        # 风险 2：action items 逾期率高
        total_ai = int(action_items.get("total", 0) or 0)
        if total_ai >= 5:
            overdue = int(action_items.get("overdue", 0) or 0)
            overdue_rate = overdue / total_ai
            if overdue_rate > 0.2:
                risks.append(
                    {
                        "id": "high-overdue-action-items",
                        "severity": "medium",
                        "description": f"Action items 逾期率 {overdue_rate:.0%}（{overdue}/{total_ai}）",
                        "suggestion": "检查责任人负载与到期估算合理性",
                    }
                )

        # 风险 3：自治边界无匹配过多
        by_autonomy = decisions.get("by_autonomy_action", {}) or {}
        require_human = int(by_autonomy.get("require_human", 0) or 0)
        if total_decisions >= 5 and require_human / max(total_decisions, 1) > 0.8:
            risks.append(
                {
                    "id": "excessive-manual-intervention",
                    "severity": "medium",
                    "description": f"require_human 占比 {require_human}/{total_decisions}，AI 自治度过低",
                    "suggestion": "评估是否扩展 auto/report_only 边界规则",
                }
            )

        return risks

    def _derive_recommendations(
        self,
        metrics: Dict[str, Any],
        risks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """从指标 + 风险推导下周/月建议。"""
        recommendations: List[Dict[str, Any]] = []
        decisions = metrics.get("decisions", {}) or {}
        action_items = metrics.get("action_items", {}) or {}

        # 建议 1：基于风险
        for risk in risks:
            recommendations.append(
                {
                    "id": f"address-{risk['id']}",
                    "priority": "high" if risk["severity"] == "high" else "medium",
                    "description": risk["suggestion"],
                    "source_risk": risk["id"],
                }
            )

        # 建议 2：自治度提升
        total_decisions = int(decisions.get("total", 0) or 0)
        auto_approved_rate = float(decisions.get("auto_approved_rate", 0) or 0)
        if total_decisions >= 5 and auto_approved_rate < 0.5:
            recommendations.append(
                {
                    "id": "increase-autonomy",
                    "priority": "medium",
                    "description": f"AI 自治通过率 {auto_approved_rate:.0%}，可评估低风险操作纳入 auto/report_only",
                    "source_metric": "auto_approved_rate",
                }
            )

        # 建议 3：action items 完成率
        total_ai = int(action_items.get("total", 0) or 0)
        if total_ai >= 5:
            completion_rate = float(action_items.get("completion_rate", 0) or 0)
            if completion_rate < 0.7:
                recommendations.append(
                    {
                        "id": "improve-action-item-completion",
                        "priority": "high" if completion_rate < 0.4 else "medium",
                        "description": f"Action items 完成率 {completion_rate:.0%}，需排查执行层瓶颈",
                        "source_metric": "completion_rate",
                    }
                )

        return recommendations

    # ---------------- 内部：Markdown 渲染 ----------------

    def _render_weekly_markdown(
        self,
        *,
        period: WeeklyReportPeriod,
        metrics: Dict[str, Any],
        risks: List[Dict[str, Any]],
        recommendations: List[Dict[str, Any]],
    ) -> str:
        lines: List[str] = [
            f"# 战略层周报 · {period.year}-W{period.week:02d}",
            f"**周期**：{period.start_date.isoformat()} → {period.end_date.isoformat()}",
            f"**生成时间**：{datetime.now(timezone.utc).isoformat()}",
            "",
            "## 1. 决策账本",
            f"- 总决策数：{metrics.get('decisions', {}).get('total', 0)}",
            f"- 自治通过率：{(metrics.get('decisions', {}).get('auto_approved_rate', 0) or 0):.1%}",
            f"- 按状态：{metrics.get('decisions', {}).get('by_status', {})}",
            f"- 按决策者：{metrics.get('decisions', {}).get('by_decided_by', {})}",
            f"- 按自治等级：{metrics.get('decisions', {}).get('by_autonomy_action', {})}",
            "",
            "## 2. 行动项",
            f"- 总数：{metrics.get('action_items', {}).get('total', 0)}",
            f"- 完成率：{(metrics.get('action_items', {}).get('completion_rate', 0) or 0):.1%}",
            f"- 逾期数：{metrics.get('action_items', {}).get('overdue', 0)}",
            f"- 按状态：{metrics.get('action_items', {}).get('by_status', {})}",
            "",
            "## 3. 事故",
            f"- 总数：{metrics.get('incidents', {}).get('total', 0)}",
            "",
            "## 4. 风险预警",
        ]
        if not risks:
            lines.append("- 无显著风险")
        else:
            for r in risks:
                lines.append(
                    f"- **[{r['severity'].upper()}] {r['id']}**：{r['description']} — {r['suggestion']}"
                )
        lines.append("")
        lines.append("## 5. 下周建议")
        if not recommendations:
            lines.append("- 无具体建议，保持当前节奏")
        else:
            for rec in recommendations:
                lines.append(f"- **[{rec['priority'].upper()}] {rec['id']}**：{rec['description']}")
        lines.append("")
        return "\n".join(lines)

    def _render_monthly_markdown(
        self,
        *,
        year: int,
        month: int,
        first_day: date,
        last_day: date,
        metrics: Dict[str, Any],
        risks: List[Dict[str, Any]],
        recommendations: List[Dict[str, Any]],
    ) -> str:
        lines: List[str] = [
            f"# 战略层月报 · {year}-{month:02d}",
            f"**周期**：{first_day.isoformat()} → {last_day.isoformat()}",
            f"**生成时间**：{datetime.now(timezone.utc).isoformat()}",
            "",
            "## 1. 决策账本月度汇总",
            f"- 总决策数：{metrics.get('decisions', {}).get('total', 0)}",
            f"- 自治通过率：{(metrics.get('decisions', {}).get('auto_approved_rate', 0) or 0):.1%}",
            f"- 按状态：{metrics.get('decisions', {}).get('by_status', {})}",
            f"- 按决策者：{metrics.get('decisions', {}).get('by_decided_by', {})}",
            "",
            "## 2. 行动项月度汇总",
            f"- 总数：{metrics.get('action_items', {}).get('total', 0)}",
            f"- 完成率：{(metrics.get('action_items', {}).get('completion_rate', 0) or 0):.1%}",
            f"- 逾期数：{metrics.get('action_items', {}).get('overdue', 0)}",
            "",
            "## 3. 事故月度汇总",
            f"- 总数：{metrics.get('incidents', {}).get('total', 0)}",
            "",
            "## 4. 风险预警",
        ]
        if not risks:
            lines.append("- 无显著风险")
        else:
            for r in risks:
                lines.append(
                    f"- **[{r['severity'].upper()}] {r['id']}**：{r['description']} — {r['suggestion']}"
                )
        lines.append("")
        lines.append("## 5. 下月建议")
        if not recommendations:
            lines.append("- 无具体建议，保持当前节奏")
        else:
            for rec in recommendations:
                lines.append(f"- **[{rec['priority'].upper()}] {rec['id']}**：{rec['description']}")
        lines.append("")
        return "\n".join(lines)

    # ---------------- 内部：持久化 ----------------

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
