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
        "auto_merge_degradation": "high",
        "security_scan_alert": "high",
        "coverage_ratchet_gap": "high",
        "workflow_drift": "medium",
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
    # Phase 4 监控与调优：自动合并成功率 + 安全扫描指标
    signals.extend(_scan_auto_merge_metrics())
    signals.extend(_scan_security_scan_metrics())
    # P1 监控补齐：覆盖率棘轮差距 + 工作流漂移
    signals.extend(_scan_coverage_ratchet_gap())
    signals.extend(_scan_workflow_drift())

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
    if signal_type == "auto_merge_degradation":
        return ["github-pr-gatekeeper", "change-request-auditor"]
    if signal_type == "security_scan_alert":
        return ["security-secrets-guard", "vibe-coding-maintainer"]
    if signal_type == "coverage_ratchet_gap":
        return ["test-qa-runner", "fhd-core-maintainer"]
    if signal_type == "workflow_drift":
        return ["fhd-core-maintainer", "change-request-auditor"]
    return ["task-router-officer"]


def _build_backlog_summary(signal_type: str, payload: Dict[str, Any]) -> str:
    type_labels = {
        "user_behavior": "用户行为洞察",
        "error_spike": "错误率突增告警",
        "performance_degradation": "性能下降告警",
        "feature_request": "功能需求反馈",
        "coverage_drop": "覆盖率下降",
        "market_signal": "市场动态信号",
        "auto_merge_degradation": "自动合并退化告警",
        "security_scan_alert": "安全扫描告警",
        "coverage_ratchet_gap": "覆盖率棘轮回退告警",
        "workflow_drift": "工作流漂移告警",
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


# ---------------------------------------------------------------------------
# Phase 4 监控与调优：自动合并成功率 + 安全扫描指标
# ---------------------------------------------------------------------------


def _scan_auto_merge_metrics() -> List[Dict[str, Any]]:
    """扫描 self-maintenance loop memory，追踪自动合并成功率。

    数据源：self_maintenance_loop_memory.json 的 recent_runs
    信号类型：auto_merge_degradation（成功率 < 80% 或回滚率 > 20% 时触发）
    """
    signals = []
    try:
        from modstore_server.self_maintenance_loop_runner import _load_loop_memory

        memory = _load_loop_memory()
        if not isinstance(memory, dict):
            return signals

        recent_runs = memory.get("recent_runs")
        if not isinstance(recent_runs, list) or not recent_runs:
            return signals

        # 统计最近 30 次运行
        sample = recent_runs[-30:]
        total = len(sample)
        if total < 3:
            return signals  # 样本不足

        # 自动合并成功：action 含 auto_merged 且 status 含 completed/merged
        auto_merge_runs = [
            r
            for r in sample
            if isinstance(r, dict)
            and (
                "auto_merge" in str(r.get("action") or "")
                or "low_risk" in str(r.get("action") or "")
            )
        ]
        auto_merge_total = len(auto_merge_runs)
        if auto_merge_total == 0:
            return signals

        auto_merge_success = sum(
            1
            for r in auto_merge_runs
            if isinstance(r, dict) and "completed" in str(r.get("status") or "").lower()
        )
        success_rate = auto_merge_success / auto_merge_total

        # 回滚率
        rollback_runs = sum(
            1
            for r in sample
            if isinstance(r, dict)
            and any(
                term in str(r.get("status") or r.get("action") or "").lower()
                for term in ("rollback", "revert", "regression", "回滚", "退回")
            )
        )
        rollback_rate = rollback_runs / total

        # 成功率 < 80% 触发信号
        if success_rate < 0.8:
            signals.append(
                {
                    "type": "auto_merge_degradation",
                    "source": "auto_merge_metrics",
                    "payload": {
                        "success_rate": round(success_rate * 100, 1),
                        "auto_merge_total": auto_merge_total,
                        "auto_merge_success": auto_merge_success,
                        "rollback_rate": round(rollback_rate * 100, 1),
                        "description": (
                            f"自动合并成功率 {success_rate * 100:.1f}%"
                            f"（{auto_merge_success}/{auto_merge_total}），低于 80% 阈值"
                        ),
                    },
                }
            )

        # 回滚率 > 20% 触发信号
        if rollback_rate > 0.2:
            signals.append(
                {
                    "type": "auto_merge_degradation",
                    "source": "auto_merge_metrics",
                    "payload": {
                        "success_rate": round(success_rate * 100, 1),
                        "rollback_rate": round(rollback_rate * 100, 1),
                        "rollback_count": rollback_runs,
                        "total_runs": total,
                        "description": (
                            f"回滚率 {rollback_rate * 100:.1f}%"
                            f"（{rollback_runs}/{total}），高于 20% 阈值"
                        ),
                    },
                }
            )
    except Exception:
        logger.debug("auto merge metrics scan skipped")

    return signals


def _scan_security_scan_metrics() -> List[Dict[str, Any]]:
    """扫描安全扫描指标文件，追踪 gitleaks/CodeQL/Trivy 扫描结果。

    数据源：FHD/metrics/ 目录下的安全扫描结果文件
    信号类型：security_scan_alert（发现高危漏洞/泄漏时触发）
    """
    signals = []
    try:
        import json
        from pathlib import Path

        # 定位 metrics 目录
        repo_root = Path(__file__).resolve().parents[3]
        metrics_dir = repo_root / "FHD" / "metrics"
        if not metrics_dir.is_dir():
            return signals

        # 扫描最近 7 天的安全指标文件
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)

        # 查找 gitleaks 扫描结果（SARIF 或 JSON）
        gitleaks_files = sorted(metrics_dir.glob("gitleaks-*.json"), reverse=True)
        if gitleaks_files:
            latest = gitleaks_files[0]
            mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                try:
                    data = json.loads(latest.read_text(encoding="utf-8"))
                    # 兼容 SARIF 和简单 JSON 格式
                    if isinstance(data, dict) and "runs" in data:
                        total_findings = sum(
                            len(run.get("results", []))
                            for run in data.get("runs", [])
                            if isinstance(run, dict)
                        )
                    elif isinstance(data, list):
                        total_findings = len(data)
                    else:
                        total_findings = 0

                    if total_findings > 0:
                        signals.append(
                            {
                                "type": "security_scan_alert",
                                "source": "gitleaks_scan",
                                "payload": {
                                    "findings": total_findings,
                                    "file": latest.name,
                                    "description": f"gitleaks 发现 {total_findings} 处密钥泄漏",
                                },
                            }
                        )
                except (json.JSONDecodeError, OSError):
                    pass

        # 扫描 CodeQL 扫描结果（SARIF）
        codeql_files = sorted(metrics_dir.glob("codeql-*.sarif"), reverse=True)
        if codeql_files:
            latest = codeql_files[0]
            mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                try:
                    data = json.loads(latest.read_text(encoding="utf-8"))
                    high_count = 0
                    total_alerts = 0
                    for run in data.get("runs", []):
                        if not isinstance(run, dict):
                            continue
                        results = run.get("results", [])
                        total_alerts += len(results)
                        for res in results:
                            if not isinstance(res, dict):
                                continue
                            level = str(res.get("level") or "").lower()
                            if level == "error":
                                high_count += 1

                    if high_count > 0:
                        signals.append(
                            {
                                "type": "security_scan_alert",
                                "source": "codeql_scan",
                                "payload": {
                                    "high_alerts": high_count,
                                    "total_alerts": total_alerts,
                                    "file": latest.name,
                                    "description": f"CodeQL 发现 {high_count} 个高危告警（共 {total_alerts} 个）",
                                },
                            }
                        )
                except (json.JSONDecodeError, OSError):
                    pass

        # 扫描 Trivy 容器扫描结果
        trivy_files = sorted(metrics_dir.glob("trivy-*.json"), reverse=True)
        if trivy_files:
            latest = trivy_files[0]
            mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                try:
                    data = json.loads(latest.read_text(encoding="utf-8"))
                    critical_high = 0
                    for result in data.get("Results", []):
                        if not isinstance(result, dict):
                            continue
                        for vuln in result.get("Vulnerabilities", []):
                            if not isinstance(vuln, dict):
                                continue
                            sev = str(vuln.get("Severity") or "").upper()
                            if sev in ("CRITICAL", "HIGH"):
                                critical_high += 1

                    if critical_high > 0:
                        signals.append(
                            {
                                "type": "security_scan_alert",
                                "source": "trivy_scan",
                                "payload": {
                                    "critical_high_vulns": critical_high,
                                    "file": latest.name,
                                    "description": f"Trivy 发现 {critical_high} 个 CRITICAL/HIGH 漏洞",
                                },
                            }
                        )
                except (json.JSONDecodeError, OSError):
                    pass
    except Exception:
        logger.debug("security scan metrics scan skipped")

    return signals


# ---------------------------------------------------------------------------
# P1 监控补齐：覆盖率棘轮差距 + 工作流漂移
# ---------------------------------------------------------------------------


def _scan_coverage_ratchet_gap() -> List[Dict[str, Any]]:
    """扫描覆盖率历史，检测棘轮回退。

    数据源：FHD/metrics/coverage-history.jsonl
    信号类型：coverage_ratchet_gap（覆盖率回退 > 1% 时触发）
    """
    signals = []
    try:
        import json
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        history_file = repo_root / "FHD" / "metrics" / "coverage-history.jsonl"
        if not history_file.is_file():
            return signals

        lines = history_file.read_text(encoding="utf-8").splitlines()
        # 取最近 10 条有效记录
        records = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    records.append(rec)
            except json.JSONDecodeError:
                continue
            if len(records) >= 10:
                break

        if len(records) < 2:
            return signals

        # 找到最新的有值记录和上一个有值记录
        def _valid_rec(rec: Dict[str, Any]) -> bool:
            return rec.get("backend_lines") is not None or rec.get("frontend_lines") is not None

        valid = [r for r in records if _valid_rec(r)]
        if len(valid) < 2:
            return signals

        latest = valid[0]
        prev = valid[1]

        # 后端覆盖率回退检测
        latest_be = latest.get("backend_lines")
        prev_be = prev.get("backend_lines")
        if isinstance(latest_be, (int, float)) and isinstance(prev_be, (int, float)):
            delta = latest_be - prev_be
            if delta < -1.0:  # 回退超过 1%
                signals.append(
                    {
                        "type": "coverage_ratchet_gap",
                        "source": "coverage_history_backend",
                        "payload": {
                            "latest": latest_be,
                            "previous": prev_be,
                            "delta": round(delta, 2),
                            "dimension": "backend_lines",
                            "latest_commit": latest.get("commit", "unknown"),
                            "previous_commit": prev.get("commit", "unknown"),
                            "description": (
                                f"后端行覆盖率回退 {abs(delta):.2f}%"
                                f"（{prev_be:.2f}% → {latest_be:.2f}%）"
                            ),
                        },
                    }
                )

        # 前端覆盖率回退检测
        latest_fe = latest.get("frontend_lines")
        prev_fe = prev.get("frontend_lines")
        if isinstance(latest_fe, (int, float)) and isinstance(prev_fe, (int, float)):
            delta = latest_fe - prev_fe
            if delta < -1.0:
                signals.append(
                    {
                        "type": "coverage_ratchet_gap",
                        "source": "coverage_history_frontend",
                        "payload": {
                            "latest": latest_fe,
                            "previous": prev_fe,
                            "delta": round(delta, 2),
                            "dimension": "frontend_lines",
                            "latest_commit": latest.get("commit", "unknown"),
                            "previous_commit": prev.get("commit", "unknown"),
                            "description": (
                                f"前端行覆盖率回退 {abs(delta):.2f}%"
                                f"（{prev_fe:.2f}% → {latest_fe:.2f}%）"
                            ),
                        },
                    }
                )
    except Exception:
        logger.debug("coverage ratchet gap scan skipped")

    return signals


def _scan_workflow_drift() -> List[Dict[str, Any]]:
    """检测 GitHub Actions workflow 漂移（根仓 SSOT 与源文件不一致）。

    数据源：根仓 .github/workflows/fhd-*.yml 与 FHD/.github/workflows/*.yml
    信号类型：workflow_drift（源文件比生成文件新时触发）
    """
    signals = []
    try:
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        root_wf = repo_root / ".github" / "workflows"
        fhd_wf = repo_root / "FHD" / ".github" / "workflows"
        if not root_wf.is_dir() or not fhd_wf.is_dir():
            return signals

        # 根仓 fhd-*.yml 文件头含 `# CI SSOT: generated from FHD/.github/workflows/{src}.yml`
        # 检测：源文件 mtime > 生成文件 mtime → 漂移
        drifted = []
        for gen_file in root_wf.glob("fhd-*.yml"):
            try:
                header = gen_file.read_text(encoding="utf-8").splitlines()[:3]
            except OSError:
                continue
            src_name = None
            for line in header:
                if "generated from" in line:
                    # 提取 FHD/.github/workflows/{src}.yml
                    marker = "FHD/.github/workflows/"
                    idx = line.find(marker)
                    if idx >= 0:
                        rest = line[idx + len(marker) :]
                        # 取到 .yml 结束
                        end = rest.find(".yml")
                        if end >= 0:
                            src_name = rest[: end + len(".yml")]
                    break
            if not src_name:
                continue
            src_file = fhd_wf / src_name
            if not src_file.is_file():
                continue
            gen_mtime = gen_file.stat().st_mtime
            src_mtime = src_file.stat().st_mtime
            # 源文件比生成文件新超过 60 秒（容忍文件系统精度）
            if src_mtime - gen_mtime > 60:
                drifted.append(
                    {
                        "generated": gen_file.name,
                        "source": src_name,
                        "source_mtime": src_mtime,
                        "generated_mtime": gen_mtime,
                    }
                )

        if drifted:
            drift_list = ", ".join(d["source"] for d in drifted[:5])
            signals.append(
                {
                    "type": "workflow_drift",
                    "source": "workflow_sync_check",
                    "payload": {
                        "drifted_count": len(drifted),
                        "drifted_files": drift_list,
                        "description": (
                            f"检测到 {len(drifted)} 个 workflow 漂移"
                            f"（源文件更新但未同步到根仓）：{drift_list}"
                        ),
                    },
                }
            )
    except Exception:
        logger.debug("workflow drift scan skipped")

    return signals
