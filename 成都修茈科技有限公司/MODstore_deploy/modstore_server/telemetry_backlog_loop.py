"""遥测 → Backlog → Auto-PR 闭环。

步骤10（AI自驱迭代）核心补齐：
- 从生产遥测数据（用户行为、异常、性能指标）自动提取改进建议
- 将建议写入 backlog 队列
- 由 intake-dispatcher → task-router-officer 派发给对应员工
- 员工执行后通过 CR 管线自动提交 PR
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _telemetry_loop_enabled() -> bool:
    return os.environ.get("XCAGI_TELEMETRY_BACKLOG_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def ingest_telemetry_signal(
    signal_type: str,
    payload: Dict[str, Any],
    *,
    source: str = "telemetry",
) -> Dict[str, Any]:
    """接收遥测信号，转化为 backlog 任务。

    支持的信号类型：
    - user_behavior: 用户行为数据（功能使用频率、路径分析）
    - error_spike: 错误率突增
    - performance_degradation: 性能指标下降
    - feature_request: 用户反馈/功能请求
    - coverage_drop: 测试覆盖率下降
    - market_signal: 市场竞品动态
    """
    if not _telemetry_loop_enabled():
        return {"ok": True, "skipped": True, "reason": "telemetry backlog disabled"}

    priority_map = {
        "error_spike": "high",
        "performance_degradation": "high",
        "coverage_drop": "medium",
        "user_behavior": "low",
        "feature_request": "medium",
        "market_signal": "low",
    }
    priority = priority_map.get(signal_type, "low")

    risk_map = {"high": "medium", "medium": "low", "low": "low"}
    risk_level = risk_map.get(priority, "low")

    summary = _build_backlog_summary(signal_type, payload)
    detail = _build_backlog_detail(signal_type, payload)

    from modstore_server.employee_autonomy_service import create_employee_suggestion

    target_ids = _target_employees_for_signal(signal_type)
    result = create_employee_suggestion(
        source_employee_id="intake-dispatcher",
        summary=summary,
        detail=detail,
        payload={"signal_type": signal_type, **payload},
        target_employee_ids=target_ids,
        kind="telemetry_backlog",
        risk_level=risk_level,
        auto_dispatch=True,
        emit_event=True,
    )

    from modstore_server.incident_bus import publish

    publish(
        "telemetry.backlog.created",
        {
            "signal_type": signal_type,
            "suggestion_id": result.get("suggestion_id"),
            "priority": priority,
        },
        source="telemetry_backlog_loop",
    )

    return {
        "ok": True,
        "signal_type": signal_type,
        "priority": priority,
        "suggestion_id": result.get("suggestion_id"),
    }


def run_telemetry_scan(
    *,
    fhd_base_url: Optional[str] = None,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """主动扫描遥测数据源，提取改进信号。

    数据源：
    1. FHD API /api/health/metrics（若可用）
    2. CI 失败率统计
    3. 覆盖率趋势
    4. 员工执行指标
    """
    if not _telemetry_loop_enabled():
        return {"ok": True, "skipped": True}

    signals = []

    signals.extend(_scan_employee_execution_metrics(lookback_hours))
    signals.extend(_scan_coverage_trend())
    signals.extend(_scan_ci_failure_rate(lookback_hours))
    signals.extend(_scan_market_signals(lookback_hours))

    results = []
    for signal in signals:
        try:
            r = ingest_telemetry_signal(
                signal_type=signal["type"],
                payload=signal["payload"],
                source=signal.get("source", "telemetry_scan"),
            )
            results.append(r)
        except Exception as exc:
            logger.warning("telemetry signal ingest failed: %s", exc)
            results.append({"ok": False, "error": str(exc)})

    market_payloads = [s["payload"] for s in signals if s.get("type") == "market_signal"]
    release_plan = {}
    if market_payloads:
        try:
            release_plan = plan_release_candidate_from_market(market_payloads)
        except Exception as exc:
            logger.warning("release_planning from market failed: %s", exc)

    return {
        "ok": True,
        "signals_found": len(signals),
        "signals_ingested": len([r for r in results if r.get("ok")]),
        "release_planning": release_plan,
    }


def plan_release_candidate_from_market(
    market_payloads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """P10：聚合市场信号，生成下一版本候选建议单（不自动发版）。"""
    if not market_payloads:
        return {"ok": True, "skipped": True, "reason": "no market payloads"}

    themes: List[str] = []
    for p in market_payloads:
        theme = str(p.get("suggested_theme") or p.get("description") or "").strip()
        if theme and theme not in themes:
            themes.append(theme[:120])
    theme_line = themes[0] if themes else "市场反馈汇总"
    summary = f"[版本规划] 下一版本候选：{theme_line}"
    detail_lines = ["基于 market_signal 扫描聚合："]
    for i, t in enumerate(themes[:8], 1):
        detail_lines.append(f"{i}. {t}")
    detail = "\n".join(detail_lines)

    from modstore_server.employee_autonomy_service import create_employee_suggestion

    return create_employee_suggestion(
        source_employee_id="intake-dispatcher",
        summary=summary,
        detail=detail,
        payload={
            "kind": "release_planning",
            "themes": themes,
            "market_signal_count": len(market_payloads),
        },
        target_employee_ids=[
            "intake-dispatcher",
            "task-router-officer",
            "deploy-release-officer",
        ],
        kind="release_planning",
        risk_level="low",
        auto_dispatch=True,
        emit_event=True,
    )


def _scan_market_signals(lookback_hours: int) -> List[Dict[str, Any]]:
    """扫描市场动态：文件注入、近期建议单、运营入库记录。"""
    signals: List[Dict[str, Any]] = []
    signals.extend(_scan_market_signals_from_file())
    signals.extend(_scan_market_signals_from_db(lookback_hours))
    return signals


def _scan_market_signals_from_file() -> List[Dict[str, Any]]:
    import json

    path = os.environ.get("XCAGI_MARKET_SIGNALS_FILE", "").strip()
    if not path or not os.path.isfile(path):
        return []
    try:
        raw = json.loads(open(path, encoding="utf-8").read())
    except Exception as exc:
        logger.warning("market signals file unreadable: %s", exc)
        return []
    items = raw if isinstance(raw, list) else raw.get("signals") or []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("description") or item.get("message") or "").strip()
        if not desc:
            continue
        out.append(
            {
                "type": "market_signal",
                "source": "market_signals_file",
                "payload": {
                    "description": desc,
                    "suggested_theme": item.get("suggested_theme") or desc[:80],
                    "source": item.get("source") or "file",
                },
            }
        )
    return out


def _scan_market_signals_from_db(lookback_hours: int) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    try:
        from datetime import datetime, timedelta, timezone

        from modstore_server.db.employee_ops import EmployeeSuggestion
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        with sf() as session:
            rows = (
                session.query(EmployeeSuggestion)
                .filter(EmployeeSuggestion.created_at >= cutoff)
                .order_by(EmployeeSuggestion.id.desc())
                .limit(30)
                .all()
            )
            for row in rows:
                kind = str(getattr(row, "kind", "") or "").lower()
                summary = str(getattr(row, "summary", "") or "")
                if "market" not in kind and "市场" not in summary and "竞品" not in summary:
                    continue
                signals.append(
                    {
                        "type": "market_signal",
                        "source": "employee_suggestion_scan",
                        "payload": {
                            "description": summary[:200],
                            "suggested_theme": summary[:80],
                            "suggestion_id": getattr(row, "id", None),
                        },
                    }
                )
    except Exception:
        logger.debug("market signals db scan skipped", exc_info=True)
    return signals


def _target_employees_for_signal(signal_type: str) -> List[str]:
    """制作线 P10：编码类信号直达 fhd-core-maintainer，市场信号走 intake。"""
    if signal_type in ("coverage_drop", "error_spike", "performance_degradation"):
        return ["fhd-core-maintainer", "test-qa-runner"]
    if signal_type == "market_signal":
        return ["intake-dispatcher", "task-router-officer"]
    return ["task-router-officer"]


def _build_backlog_summary(signal_type: str, payload: Dict[str, Any]) -> str:
    type_labels = {
        "user_behavior": "用户行为洞察",
        "error_spike": "错误率突增告警",
        "performance_degradation": "性能下降告警",
        "feature_request": "功能需求反馈",
        "coverage_drop": "覆盖率下降",
        "market_signal": "市场动态信号",
    }
    label = type_labels.get(signal_type, signal_type)
    desc = payload.get("description", "") or payload.get("message", "")
    if desc:
        return f"[遥测] {label}: {desc[:100]}"
    return f"[遥测] {label}"


def _build_backlog_detail(signal_type: str, payload: Dict[str, Any]) -> str:
    lines = [f"信号类型: {signal_type}"]
    for k, v in payload.items():
        if isinstance(v, (str, int, float, bool)):
            lines.append(f"- {k}: {v}")
        elif isinstance(v, list) and len(v) <= 10:
            lines.append(f"- {k}: {', '.join(str(x) for x in v)}")
    return "\n".join(lines)


def _scan_employee_execution_metrics(lookback_hours: int) -> List[Dict[str, Any]]:
    signals = []
    try:
        from datetime import datetime, timedelta, timezone

        from modstore_server.models import EmployeeExecutionMetric, get_session_factory

        sf = get_session_factory()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        with sf() as session:
            high_failure = (
                session.query(EmployeeExecutionMetric)
                .filter(EmployeeExecutionMetric.created_at >= cutoff)
                .all()
            )
            employee_failures: Dict[str, int] = {}
            for m in high_failure:
                if getattr(m, "success", True) is False:
                    eid = getattr(m, "employee_id", "unknown")
                    employee_failures[eid] = employee_failures.get(eid, 0) + 1

            for eid, count in employee_failures.items():
                if count >= 3:
                    signals.append(
                        {
                            "type": "error_spike",
                            "source": "employee_metrics",
                            "payload": {
                                "employee_id": eid,
                                "failure_count": count,
                                "lookback_hours": lookback_hours,
                                "description": f"员工 {eid} 在 {lookback_hours}h 内失败 {count} 次",
                            },
                        }
                    )
    except Exception:
        logger.debug("employee execution metrics scan skipped")

    return signals


def _scan_coverage_trend() -> List[Dict[str, Any]]:
    signals = []
    try:
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        with sf() as session:
            from modstore_server.models import EmployeeExecutionMetric

            recent = (
                session.query(EmployeeExecutionMetric)
                .filter(EmployeeExecutionMetric.task_brief.contains("coverage"))
                .order_by(EmployeeExecutionMetric.created_at.desc())
                .limit(5)
                .all()
            )
            for r in recent:
                output = getattr(r, "output_json", {}) or {}
                coverage = output.get("coverage_percent")
                if coverage is not None and coverage < 60:
                    signals.append(
                        {
                            "type": "coverage_drop",
                            "source": "coverage_scan",
                            "payload": {
                                "coverage_percent": coverage,
                                "description": f"覆盖率 {coverage}% 低于目标 80%",
                            },
                        }
                    )
    except Exception:
        logger.debug("coverage trend scan skipped")

    return signals


def _scan_ci_failure_rate(lookback_hours: int) -> List[Dict[str, Any]]:
    signals = []
    try:
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        with sf() as session:
            from datetime import datetime, timedelta, timezone

            from modstore_server.models import OpsStagedChange

            cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
            recent_changes = (
                session.query(OpsStagedChange).filter(OpsStagedChange.created_at >= cutoff).all()
            )
            failed = sum(1 for c in recent_changes if getattr(c, "status", "") == "failed")
            total = len(recent_changes)
            if total > 0 and failed / total > 0.3:
                signals.append(
                    {
                        "type": "error_spike",
                        "source": "ci_failure_rate",
                        "payload": {
                            "failure_rate": round(failed / total * 100, 1),
                            "total_runs": total,
                            "failed_runs": failed,
                            "description": f"CI 失败率 {failed / total * 100:.1f}%（{failed}/{total}）",
                        },
                    }
                )
    except Exception:
        logger.debug("CI failure rate scan skipped")

    return signals
