"""Fixture-only database health receipt auditor; never connects or mutates."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("database_snapshot")
    issues: list[dict[str, str]] = []
    if not isinstance(snapshot, dict):
        issues.append(
            {"code": "missing_database_snapshot", "detail": "database_snapshot is required"}
        )
        snapshot = {}
    checks = {
        "connection_unreachable": snapshot.get("connection_ok") is not True,
        "migration_drift": bool(snapshot.get("migration_drift")),
        "backup_stale": int(snapshot.get("backup_age_hours") or 999999) > 24,
        "slow_queries_present": int(snapshot.get("slow_query_count") or 0) > 0,
        "write_capability_present": snapshot.get("read_only") is not True,
    }
    for code, failed in checks.items():
        if failed:
            issues.append(
                {"code": code, "detail": "supplied snapshot did not satisfy the reviewed threshold"}
            )
    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "needs_review",
        "summary": "supplied database health snapshot is within thresholds"
        if approved
        else "database snapshot needs review",
        "issues": issues,
        "evidence": ["fixture_only", "no_database_connection", "no_sql_execution", "no_migration"],
        "read_only": True,
        "side_effects": [],
    }


__all__ = ["run"]
