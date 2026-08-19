"""Metric collection, risk derivation and rendering for strategic reports."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import func, select

from modstore_server.db.strategic import StrategicActionItem
from modstore_server.db.strategic import StrategicDecision as StrategicDecisionModel

logger = logging.getLogger(__name__)


class StrategicReportAnalysisMixin:
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
        period: Any,
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
