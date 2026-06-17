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


def _record_time_rail_runtime(result: Dict[str, Any]) -> None:
    """把 08:25 编排结果投影到时间轨 runtime 节点。"""
    try:
        from modstore_server.time_rail_runtime import record_node_run

        meta = {
            "record_id": result.get("record_id"),
            "release_train": result.get("release_train"),
            "release_kind": result.get("release_kind"),
            "digest_mode": result.get("digest_mode"),
            "shadow": result.get("shadow"),
        }
        ok = bool(result.get("ok"))
        record_node_run("ORCH", ok=ok, source="daily_release_train_orchestrator_job", meta=meta)
        record_node_run("KIND", ok=True, source="daily_release_train_orchestrator_job", meta=meta)
        record_node_run("BR", ok=bool(result.get("digest_mode") in ("primary", "digest")), source="daily_release_train_orchestrator_job", meta=meta)

        phase_b = result.get("phase_b") if isinstance(result.get("phase_b"), dict) else {}
        line_results = phase_b.get("line_results") if isinstance(phase_b.get("line_results"), dict) else {}
        for line_key, node_id in (("P-W", "PW"), ("P-App", "APPB"), ("S-R", "SR")):
            row = line_results.get(line_key) if isinstance(line_results.get(line_key), dict) else {}
            if row:
                record_node_run(node_id, ok=bool(row.get("ok")), source="daily_release_train_orchestrator_job.phase_b", meta={**meta, "line": line_key})

        pipeline = result.get("phase_c_pipeline") if isinstance(result.get("phase_c_pipeline"), dict) else {}
        step_ids = list(
            pipeline.get("executed_steps")
            or pipeline.get("step_ids")
            or pipeline.get("planned_steps")
            or []
        )
        for step in ("P3", "P4", "P5", "P6", "P7", "P8", "P9"):
            if step in step_ids:
                record_node_run(step, ok=bool(pipeline.get("ok")), source="daily_release_train_orchestrator_job.phase_c_pipeline", meta={**meta, "step_ids": step_ids})
        if any(step in step_ids for step in ("P5", "P6")):
            record_node_run("CANARY", ok=bool(pipeline.get("ok")), source="daily_release_train_orchestrator_job.phase_c_pipeline", meta={**meta, "step_ids": step_ids})
        if pipeline.get("rollback"):
            record_node_run("ROLLBACK", ok=False, source="daily_release_train_orchestrator_job.phase_c_pipeline", meta={**meta, "rollback": pipeline.get("rollback")})

        phase_c = result.get("phase_c") if isinstance(result.get("phase_c"), dict) else {}
        steps = phase_c.get("steps") if isinstance(phase_c.get("steps"), list) else []
        for step_row in steps:
            if not isinstance(step_row, dict):
                continue
            node_id = {"P9": "P9I", "P5": "P5I", "P6": "P6I"}.get(str(step_row.get("step") or ""))
            if node_id:
                record_node_run(node_id, ok=bool(step_row.get("ok")), source="daily_release_train_orchestrator_job.phase_c", meta={**meta, "step": step_row.get("step")})
        if isinstance(phase_c.get("fastgate"), dict):
            record_node_run("FASTGATE", ok=bool(phase_c["fastgate"].get("ok")), source="daily_release_train_orchestrator_job.phase_c", meta={**meta, "fastgate": phase_c.get("fastgate")})
        if isinstance(phase_c.get("download_release"), dict):
            record_node_run("DLSSOT", ok=bool(phase_c["download_release"].get("ok")), source="daily_release_train_orchestrator_job.phase_c", meta={**meta, "download_release": phase_c.get("download_release")})
        if isinstance(phase_c.get("rollback"), dict):
            record_node_run("ROLLBACK", ok=False, source="daily_release_train_orchestrator_job.phase_c", meta={**meta, "rollback": phase_c.get("rollback")})
    except Exception:
        logger.exception("release_train orchestrator: time_rail runtime record failed")


def run_daily_release_train_orchestrator_job(
    *,
    record_id: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    raw = (os.environ.get("MODSTORE_RELEASE_TRAIN_ENABLED", "1") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return {"ok": True, "skipped": True, "reason": "MODSTORE_RELEASE_TRAIN_ENABLED=0"}

    from modstore_server.automation_primary import skip_daily_automation_result

    delegated = skip_daily_automation_result(job="release_train_orchestrator")
    if delegated and not force:
        return delegated

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
        # release_train orchestrator 的 Phase B 默认不再复用 P-App 更新线（仅 P-W + S-R）：
        # P-App 已在 Phase A 做补丁派发，避免在同日重复触发更新流。
        result["phase_b"] = execute_phase_b_line_chain(
            rid, shadow=shadow, force=force, include_app=False
        )
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
    _record_time_rail_runtime(result)

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
