"""08:15 cron：消费当日摘要四产线清单，Phase A 执行 P-S + P-App 补丁派发。"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _today_digest_day() -> str:
    try:
        from zoneinfo import ZoneInfo

        tz_name = os.environ.get("MODSTORE_DAILY_DIGEST_TZ", "Asia/Shanghai").strip()
        tz = ZoneInfo(tz_name)
        return datetime.now(tz).strftime("%Y-%m-%d")
    except RECOVERABLE_ERRORS:
        return datetime.utcnow().strftime("%Y-%m-%d")


def find_digest_record_for_execute(
    *,
    day: Optional[str] = None,
    record_id: Optional[int] = None,
) -> Optional[int]:
    from modstore_server.models import DailyDigestRecord, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        if record_id and int(record_id) > 0:
            row = session.get(DailyDigestRecord, int(record_id))
            return int(row.id) if row else None
        target_day = (day or _today_digest_day()).strip()
        row = (
            session.query(DailyDigestRecord)
            .filter(DailyDigestRecord.day == target_day)
            .order_by(DailyDigestRecord.id.desc())
            .first()
        )
        if row is None:
            row = (
                session.query(DailyDigestRecord)
                .order_by(DailyDigestRecord.id.desc())
                .first()
            )
        return int(row.id) if row else None


def run_daily_vibe_line_execute_job(
    *,
    record_id: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    raw = (
        (os.environ.get("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1") or "")
        .strip()
        .lower()
    )
    if raw in ("0", "false", "no", "off"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "MODSTORE_DAILY_VIBE_EXECUTE_ENABLED=0",
        }

    from modstore_server.autonomy_guard_delegate import request_action

    risk_decision, pending = request_action(
        "daily_vibe_dispatch",
        action_id=f"daily-vibe-dispatch:{_today_digest_day()}",
        payload={"record_id": record_id, "force": force},
        source="daily_vibe_line_execute.cron",
    )
    if not risk_decision.allowed:
        pending_state = str((pending or {}).get("state") or "")
        return {
            "ok": False,
            "skipped": True,
            "reason": (
                "autonomy_guard_rejected_or_terminal"
                if pending_state in {"rejected", "executed", "execution_failed"}
                else (
                    "autonomy_guard_pending_approval"
                    if risk_decision.requires_confirmation
                    else "autonomy_guard_blocked"
                )
            ),
            "pending_approval": pending,
            "risk_decision": risk_decision.to_dict(),
        }

    from modstore_server.automation_primary import skip_daily_automation_result

    delegated = skip_daily_automation_result(job="daily_vibe_line_execute")
    if delegated and not force:
        return delegated

    rid = find_digest_record_for_execute(record_id=record_id)
    if not rid:
        return {"ok": False, "error": "no digest record found"}

    release_kind = ""
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        with get_session_factory()() as session:
            row = session.get(DailyDigestRecord, int(rid))
            if row is not None:
                release_kind = (row.release_kind or "").strip()
    except RECOVERABLE_ERRORS:
        pass
    if release_kind:
        logger.info("daily vibe line execute release kind resolved")

    from modstore_server.digest_daily_line_chain import execute_phase_a_line_chain

    out = execute_phase_a_line_chain(rid, force=force)
    if out.get("ok") and not out.get("skipped"):
        logger.info("daily vibe line execute completed")
    elif out.get("skipped"):
        logger.info("daily vibe line execute skipped")
    else:
        logger.warning("daily vibe line execute failed")
    return out


def cron_trigger_for_vibe_line_execute():
    """默认 08:15（北京时间），晚于 08:00 摘要 + Vibe 预备。"""
    try:
        from zoneinfo import ZoneInfo

        from apscheduler.triggers.cron import CronTrigger

        tz = ZoneInfo(
            os.environ.get("MODSTORE_DAILY_VIBE_EXECUTE_TZ", "Asia/Shanghai").strip()
        )
        hour = int(os.environ.get("MODSTORE_DAILY_VIBE_EXECUTE_HOUR", "8"))
        minute = int(os.environ.get("MODSTORE_DAILY_VIBE_EXECUTE_MINUTE", "15"))
        return CronTrigger(hour=hour, minute=minute, timezone=tz)
    except RECOVERABLE_ERRORS:
        from apscheduler.triggers.cron import CronTrigger

        return CronTrigger(hour=8, minute=15)
