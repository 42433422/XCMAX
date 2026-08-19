# ruff: noqa
"""Auto-merge and security telemetry scanners."""
from __future__ import annotations
import logging
import sys
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _facade() -> Any:
    return sys.modules["modstore_server.telemetry_backlog_loop"]


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
        sample = recent_runs[-30:]
        total = len(sample)
        if total < 3:
            return signals
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
            (
                1
                for r in auto_merge_runs
                if isinstance(r, dict) and "completed" in str(r.get("status") or "").lower()
            )
        )
        success_rate = auto_merge_success / auto_merge_total
        rollback_runs = sum(
            (
                1
                for r in sample
                if isinstance(r, dict)
                and any(
                    (
                        term in str(r.get("status") or r.get("action") or "").lower()
                        for term in ("rollback", "revert", "regression", "回滚", "退回")
                    )
                )
            )
        )
        rollback_rate = rollback_runs / total
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
                        "description": f"自动合并成功率 {success_rate * 100:.1f}%（{auto_merge_success}/{auto_merge_total}），低于 80% 阈值",
                    },
                }
            )
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
                        "description": f"回滚率 {rollback_rate * 100:.1f}%（{rollback_runs}/{total}），高于 20% 阈值",
                    },
                }
            )
    except Exception:
        _facade().logger.debug("auto merge metrics scan skipped")
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

        repo_root = Path(_facade().__file__).resolve().parents[3]
        metrics_dir = repo_root / "FHD" / "metrics"
        if not metrics_dir.is_dir():
            return signals
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)
        gitleaks_files = sorted(metrics_dir.glob("gitleaks-*.json"), reverse=True)
        if gitleaks_files:
            latest = gitleaks_files[0]
            mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                try:
                    data = json.loads(latest.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "runs" in data:
                        total_findings = sum(
                            (
                                len(run.get("results", []))
                                for run in data.get("runs", [])
                                if isinstance(run, dict)
                            )
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
        _facade().logger.debug("security scan metrics scan skipped")
    return signals
