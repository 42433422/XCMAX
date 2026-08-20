# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.time_rail_workflow")


def _ensure_non_triggered_time_rail_decisions(
    derived: _facade().Dict[str, _facade().Dict[str, _facade().Any]],
    *,
    last_run: _facade().Optional[str],
    record_id: int,
    release_kind: str,
    line_dispatch: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    phase_c_pipeline: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    phase_c: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    guard_active: bool = False,
) -> None:
    """Mark branch steps that were decided but intentionally not run in this cadence."""
    base_detail = {"record_id": record_id, "release_kind": release_kind or "unknown"}

    def mark(
        node_id: str,
        *,
        source: str,
        reason: str,
        detail: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    ):
        if node_id in derived:
            return
        out_detail = dict(base_detail)
        out_detail.update(detail or {})
        derived[node_id] = _facade()._decision_not_taken_status(
            node_id, last_run=last_run, source=source, reason=reason, detail=out_detail
        )

    if not guard_active:
        mark(
            "DRPROBE",
            source="release_train.backup_guard",
            reason="no_active_backup_guard",
            detail={"active": False},
        )
    dispatch = line_dispatch or {}
    for line, line_node, p2_node in (("P-W", "PW", "P2W"), ("S-R", "SR", "P2R")):
        total = _facade()._line_total_sections(dispatch, line)
        if total == 0:
            detail = {"line": line, "total_sections": 0}
            mark(
                line_node,
                source="daily_digest.vibe_prep_line_dispatch",
                reason="line_has_no_work_items",
                detail=detail,
            )
            mark(
                p2_node,
                source=f"time_rail.derive.{line_node}",
                reason="line_has_no_work_items",
                detail={**detail, "from_node": line_node},
            )
    if release_kind not in ("installer", "major"):
        for nid in ("P9I", "P5I", "P6I", "FASTGATE", "DLSSOT"):
            mark(nid, source="daily_digest.release_kind", reason="release_kind_not_installer")
    pipeline = phase_c_pipeline or {}
    step_ids = list(
        pipeline.get("executed_steps")
        or pipeline.get("step_ids")
        or pipeline.get("planned_steps")
        or []
    )
    if pipeline or release_kind == "daily":
        for step in ("P4", "P5", "P6", "P9"):
            if step not in step_ids:
                mark(
                    step,
                    source="daily_digest.phase_c_pipeline",
                    reason="phase_c_step_not_planned",
                    detail={"step_ids": step_ids},
                )
        if "P5" not in step_ids and "P6" not in step_ids:
            mark(
                "CANARY",
                source="daily_digest.phase_c_pipeline",
                reason="canary_not_scheduled_without_release",
                detail={"step_ids": step_ids},
            )
        if "P6" not in step_ids:
            for nid in ("P6POP", "P6PW"):
                mark(
                    nid,
                    source="daily_digest.phase_c_pipeline",
                    reason="update_push_not_scheduled",
                    detail={"step_ids": step_ids},
                )
        mark(
            "P9G",
            source="release_train.json",
            reason="generation_cadence_not_due",
            detail={"step_ids": step_ids},
        )
    rollback = (
        pipeline.get("rollback")
        if isinstance(pipeline.get("rollback"), dict)
        else (
            (phase_c or {}).get("rollback")
            if isinstance((phase_c or {}).get("rollback"), dict)
            else None
        )
    )
    if not rollback:
        mark(
            "ROLLBACK",
            source="daily_digest.phase_c_pipeline",
            reason="rollback_not_required",
            detail={"step_ids": step_ids},
        )
    mark(
        "HEAL",
        source="daily_digest.phase_c_pipeline",
        reason="self_heal_not_required",
        detail={"step_ids": step_ids},
    )


def _latest_ops_staged_change() -> _facade().Optional[_facade().Any]:
    try:
        from modstore_server.models import OpsStagedChange, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(OpsStagedChange).order_by(OpsStagedChange.id.desc()).limit(1).first()
            )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("time_rail: ops staged change unavailable", exc_info=True)
        return None


def _latest_change_request() -> _facade().Optional[_facade().Any]:
    try:
        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(EmployeeChangeRequest)
                .order_by(EmployeeChangeRequest.id.desc())
                .limit(1)
                .first()
            )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("time_rail: change request unavailable", exc_info=True)
        return None


def _action_item_stats(
    *, day: str = "", record_id: _facade().Optional[int] = None
) -> _facade().Dict[str, _facade().Any]:
    try:
        from modstore_server.digest_action_items import list_action_items

        items = list_action_items(day=day or None, limit=2000)
        if record_id:
            items = [it for it in items if int(it.get("record_id") or 0) == int(record_id)]
        by_kind: _facade().Dict[str, int] = {}
        by_status: _facade().Dict[str, int] = {}
        for it in items:
            by_kind[str(it.get("kind") or "")] = by_kind.get(str(it.get("kind") or ""), 0) + 1
            by_status[str(it.get("status") or "")] = (
                by_status.get(str(it.get("status") or ""), 0) + 1
            )
        return {"ok": True, "total": len(items), "by_kind": by_kind, "by_status": by_status}
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("time_rail: action item stats unavailable", exc_info=True)
        return {"ok": False, "total": 0, "by_kind": {}, "by_status": {}}


def _maintenance_backlog_by_node() -> _facade().Dict[str, _facade().Dict[str, _facade().Any]]:
    """读取已排队的时间轨自维护任务，作为缺证节点的可证明状态。"""
    try:
        from modstore_server.six_line_event_router import read_digest_backlog_entries

        rows = read_digest_backlog_entries()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("time_rail: maintenance backlog unavailable", exc_info=True)
        return {}
    out: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "") != "time-rail-observability":
            continue
        nid = str(row.get("node_id") or "").strip()
        if not nid:
            continue
        prev = out.get(nid)
        if prev and str(prev.get("at") or "") >= str(row.get("at") or ""):
            continue
        out[nid] = dict(row)
    return out


def _latest_digest_row() -> _facade().Optional[_facade().Any]:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(DailyDigestRecord)
                .order_by(DailyDigestRecord.id.desc())
                .limit(1)
                .first()
            )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("time_rail: latest digest unavailable", exc_info=True)
        return None


def _retention_metric() -> _facade().Optional[_facade().Any]:
    try:
        from modstore_server.models import EmployeeExecutionMetric, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(EmployeeExecutionMetric)
                .filter(EmployeeExecutionMetric.employee_id == "retention-officer")
                .order_by(EmployeeExecutionMetric.id.desc())
                .limit(1)
                .first()
            )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("time_rail: retention metric unavailable", exc_info=True)
        return None
