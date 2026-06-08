"""08:25 release_train 编排：Phase B/C 产线串联 + ProductionLine + installer/major 员工链。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _orchestrator_digest_mode() -> str:
    return (
        (os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE", "shadow") or "shadow")
        .strip()
        .lower()
    )


def _persist_orchestrator_audit(record_id: int, payload: Dict[str, Any]) -> None:
    """写入 digest 记录 vibe_prep_meta_json，便于审计 primary vs shadow。"""
    if record_id <= 0 or not isinstance(payload, dict):
        return
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(DailyDigestRecord, int(record_id))
            if row is None:
                return
            meta: Dict[str, Any] = {}
            raw = (getattr(row, "vibe_prep_meta_json", None) or "").strip()
            if raw.startswith("{"):
                try:
                    meta = json.loads(raw)
                except json.JSONDecodeError:
                    meta = {}
            if not isinstance(meta, dict):
                meta = {}
            meta["orchestrator_audit"] = payload
            row.vibe_prep_meta_json = json.dumps(meta, ensure_ascii=False)
            session.commit()
    except Exception:
        logger.exception("persist orchestrator_audit failed record_id=%s", record_id)


def _load_digest_release_meta(record_id: int) -> Dict[str, Any]:
    from modstore_server.models import DailyDigestRecord, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        row = session.get(DailyDigestRecord, int(record_id))
        if row is None:
            return {}
        return {
            "day": row.day,
            "release_train_before": (row.release_train_before or "").strip(),
            "release_train_after": (row.release_train_after or "").strip(),
            "release_kind": (row.release_kind or "daily").strip() or "daily",
        }


def run_daily_release_train_orchestrator_job(
    *,
    record_id: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    raw = (os.environ.get("MODSTORE_RELEASE_TRAIN_ENABLED", "1") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return {"ok": True, "skipped": True, "reason": "MODSTORE_RELEASE_TRAIN_ENABLED=0"}

    mode = _orchestrator_digest_mode()
    if mode in ("off", "legacy"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE=off",
        }

    from modstore_server.daily_vibe_line_execute_job import find_digest_record_for_execute
    from modstore_server.digest_daily_line_chain import (
        execute_installer_employee_chain,
        execute_phase_b_line_chain,
        execute_production_pipeline_chain,
    )

    rid = find_digest_record_for_execute(record_id=record_id)
    if not rid:
        return {"ok": False, "error": "no digest record for release_train orchestrator"}

    meta = _load_digest_release_meta(rid)
    kind = str(meta.get("release_kind") or "daily")
    rt_after = str(meta.get("release_train_after") or "")
    shadow = mode == "shadow"

    result: Dict[str, Any] = {
        "ok": True,
        "record_id": rid,
        "release_kind": kind,
        "release_train": rt_after,
        "digest_mode": mode,
        "shadow": shadow,
        "push_installer": kind in ("installer", "major"),
        "push_major": kind == "major",
    }

    if shadow:
        logger.info(
            "release_train orchestrator shadow record_id=%s kind=%s rt=%s",
            rid,
            kind,
            rt_after,
        )
    elif mode in ("primary", "digest") and not force:
        try:
            from modstore_server.daily_orchestrator_job import run_daily_orchestrator_job

            orch = run_daily_orchestrator_job(bypass_digest_gate=True)
            result["daily_orchestrator"] = orch
        except Exception:
            logger.exception("release_train orchestrator: daily_orchestrator failed")

    try:
        result["phase_b"] = execute_phase_b_line_chain(rid, shadow=shadow, force=force)
        if not result["phase_b"].get("ok"):
            result["ok"] = False
    except Exception:
        logger.exception("release_train orchestrator: phase_b line chain failed")
        result["phase_b"] = {"ok": False, "error": "phase_b failed"}
        result["ok"] = False

    try:
        result["phase_c_pipeline"] = execute_production_pipeline_chain(
            rid,
            release_train=rt_after,
            release_kind=kind,
            shadow=shadow,
        )
        if not result["phase_c_pipeline"].get("ok", True):
            result["ok"] = False
    except Exception:
        logger.exception("release_train orchestrator: production pipeline failed")
        result["phase_c_pipeline"] = {"ok": False, "error": "pipeline failed"}
        result["ok"] = False

    if kind in ("installer", "major"):
        try:
            result["phase_c"] = execute_installer_employee_chain(
                rid,
                release_train=rt_after,
                release_kind=kind,
                shadow=shadow,
            )
            result["installer_plan"] = result["phase_c"]
            if kind == "major":
                result["major_plan"] = result["phase_c"]
            if not result["phase_c"].get("ok", True):
                result["ok"] = False
        except Exception:
            logger.exception("release_train orchestrator: installer/major chain failed")
            result["phase_c"] = {"ok": False, "error": "phase_c failed"}
            result["ok"] = False

    _persist_orchestrator_audit(
        rid,
        {
            "orchestrator_mode": mode,
            "shadow": shadow,
            "release_kind": kind,
            "release_train": rt_after,
            "ok": bool(result.get("ok")),
            "ran_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    return result


def cron_trigger_for_release_train_orchestrator():
    """默认 08:25（北京时间），晚于 08:15 Phase A。"""
    try:
        from zoneinfo import ZoneInfo

        from apscheduler.triggers.cron import CronTrigger

        tz = ZoneInfo(
            os.environ.get("MODSTORE_RELEASE_TRAIN_ORCHESTRATOR_TZ", "Asia/Shanghai").strip()
        )
        hour = int(os.environ.get("MODSTORE_RELEASE_TRAIN_ORCHESTRATOR_HOUR", "8"))
        minute = int(os.environ.get("MODSTORE_RELEASE_TRAIN_ORCHESTRATOR_MINUTE", "25"))
        return CronTrigger(hour=hour, minute=minute, timezone=tz)
    except Exception:
        from apscheduler.triggers.cron import CronTrigger

        return CronTrigger(hour=8, minute=25)
