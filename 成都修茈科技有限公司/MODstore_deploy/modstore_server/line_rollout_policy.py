"""产线灰度放开策略：P-S 优先 primary，其余维持 shadow；CR 预算与通过率门禁。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

DISPATCH_PS = "P-S"
DISPATCH_PW = "P-W"
DISPATCH_APP = "P-App"
DISPATCH_SR = "S-R"


def _env_lines(name: str, default: str) -> List[str]:
    raw = (os.environ.get(name, default) or default).strip()
    if not raw or raw.lower() in ("*", "all", "none", ""):
        return []
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]


def primary_lines() -> List[str]:
    """默认仅 P-S 补丁线 primary；可用 MODSTORE_LINE_PRIMARY_LINES 覆盖。"""
    lines = _env_lines("MODSTORE_LINE_PRIMARY_LINES", "P-S")
    return lines or [DISPATCH_PS]


def shadow_lines_override() -> List[str]:
    """显式保持 shadow 的产线（即使全局 primary）。"""
    return _env_lines(
        "MODSTORE_LINE_SHADOW_LINES",
        "P-W,P-App,S-R",
    )


def resolve_line_execution_mode(
    dispatch_line: str,
    *,
    phase: str = "A",
    global_digest_mode: str = "shadow",
) -> str:
    """返回 auto | shadow（dry_run 由 executor 根据 mode=shadow 设置）。"""
    line = (dispatch_line or "").strip()
    global_mode = (global_digest_mode or "shadow").strip().lower()

    if line in shadow_lines_override():
        return "shadow"

    if global_mode in ("off", "legacy"):
        return "shadow"

    if global_mode == "shadow":
        # 全局 shadow 时，primary_lines 中的产线仍可 auto（灰度放开）
        if line in primary_lines():
            return "auto"
        return "shadow"

    # global primary：非 shadow override 的产线 auto
    if line in shadow_lines_override():
        return "shadow"
    if line in primary_lines() or not primary_lines():
        return "auto"
    return "shadow"


def _cr_budget_max() -> int:
    try:
        return max(1, int(os.environ.get("MODSTORE_DAILY_CR_BUDGET_MAX", "10")))
    except ValueError:
        return 10


def _cr_lines_budget() -> int:
    try:
        return max(10, int(os.environ.get("MODSTORE_DAILY_CR_LINES_BUDGET", "200")))
    except ValueError:
        return 200


def check_daily_cr_budget(*, digest_record_id: int = 0) -> Dict[str, Any]:
    """检查当日已落盘 CR 数量与行数预算。"""
    try:
        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        sf = get_session_factory()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        with sf() as session:
            rows = (
                session.query(EmployeeChangeRequest)
                .filter(EmployeeChangeRequest.created_at >= cutoff)
                .filter(EmployeeChangeRequest.status.in_(("applied", "pending", "approved")))
                .all()
            )
        count = len(rows)
        total_lines = 0
        for r in rows:
            try:
                data = json.loads(r.diff_blob or "{}")
                content = str(data.get("content") or "")
                total_lines += len(content.splitlines())
            except Exception:
                pass
        max_cr = _cr_budget_max()
        max_lines = _cr_lines_budget()
        ok = count < max_cr and total_lines < max_lines
        return {
            "ok": ok,
            "cr_count_24h": count,
            "cr_lines_24h": total_lines,
            "budget_max_cr": max_cr,
            "budget_max_lines": max_lines,
            "digest_record_id": int(digest_record_id or 0),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("check_daily_cr_budget failed")
        return {"ok": True, "skipped": True, "error": str(exc)}


def line_rollout_pass_rate(*, dispatch_line: str, lookback_days: int = 7) -> Dict[str, Any]:
    """近 N 天该产线 CR 验证通过率（applied / total）。"""
    try:
        lookback_days = max(1, min(int(lookback_days or 7), 30))
    except ValueError:
        lookback_days = 7
    min_rate = 0.8
    try:
        min_rate = float(os.environ.get("MODSTORE_LINE_ROLLOUT_MIN_PASS_RATE", "0.8"))
    except ValueError:
        pass

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    try:
        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        sf = get_session_factory()
        line_tag = (dispatch_line or "").strip()
        with sf() as session:
            rows = (
                session.query(EmployeeChangeRequest)
                .filter(EmployeeChangeRequest.created_at >= cutoff)
                .all()
            )
        matched = [
            r
            for r in rows
            if line_tag and line_tag in str(getattr(r, "task_brief", "") or "")
        ]
        if not matched:
            return {
                "ok": True,
                "pass_rate": 1.0,
                "sample_size": 0,
                "min_pass_rate": min_rate,
                "dispatch_line": line_tag,
            }
        applied = sum(1 for r in matched if (r.status or "") in ("applied", "approved"))
        rate = applied / len(matched) if matched else 1.0
        return {
            "ok": rate >= min_rate,
            "pass_rate": round(rate, 4),
            "sample_size": len(matched),
            "applied_count": applied,
            "min_pass_rate": min_rate,
            "dispatch_line": line_tag,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "skipped": True, "error": str(exc)}


def should_allow_line_primary(dispatch_line: str) -> Dict[str, Any]:
    """综合 primary 名单 + 通过率 + CR 预算。"""
    mode = resolve_line_execution_mode(
        dispatch_line,
        global_digest_mode=os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE", "shadow"),
    )
    budget = check_daily_cr_budget()
    rollout = line_rollout_pass_rate(dispatch_line=dispatch_line)
    allowed = mode == "auto" and budget.get("ok", True) and rollout.get("ok", True)
    return {
        "allowed": allowed,
        "mode": mode,
        "budget": budget,
        "rollout": rollout,
    }


__all__ = [
    "check_daily_cr_budget",
    "line_rollout_pass_rate",
    "primary_lines",
    "resolve_line_execution_mode",
    "should_allow_line_primary",
]
