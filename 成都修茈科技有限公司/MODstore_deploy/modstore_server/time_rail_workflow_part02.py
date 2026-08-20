# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# ruff: noqa: E402, F401, I001
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.time_rail_workflow")


from modstore_server.time_rail_workflow_derive_tail import _derive_from_sources_tail


def _derive_from_sources() -> _facade().Dict[str, _facade().Dict[str, _facade().Any]]:
    """从 release_train / digest / backup 等现有 SSOT 推导节点状态。"""
    derived: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    guard = None
    rt_state: _facade().Dict[str, _facade().Any] = {}
    try:
        from modstore_server.release_train import active_backup_guard, load_state

        guard = active_backup_guard()
        rt_state = load_state() or {}
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("time_rail: release_train unavailable", exc_info=True)
    if guard:
        derived["DRFAIL"] = _facade()._node_status_shell(
            "DRFAIL",
            last_run=_facade()._iso_or_none(
                guard.get("last_probe_at") or guard.get("at") or guard.get("set_at")
            ),
            ok=False,
            guard_active=True,
            source="release_train.backup_guard",
            detail={"reason": guard.get("reason"), "day": guard.get("day")},
        )
        derived["DRPROBE"] = _facade()._node_status_shell(
            "DRPROBE",
            last_run=_facade()._iso_or_none(guard.get("last_probe_at") or guard.get("set_at")),
            ok=guard.get("probe_escalated") is not True,
            guard_active=True,
            source="release_train.backup_guard",
            detail={
                "probe_retry_count": guard.get("probe_retry_count"),
                "probe_escalated": guard.get("probe_escalated"),
            },
        )
    else:
        derived["DRFAIL"] = _facade()._node_status_shell(
            "DRFAIL",
            ok=True,
            source="release_train.backup_guard",
            detail={"active": False},
            observed=True,
            proof_status="proved_ok",
        )
    try:
        from modstore_server.daily_backup_job import list_backups

        backups = list_backups(limit=5)
        if backups:
            latest = backups[0]
            derived["BK"] = _facade()._node_status_shell(
                "BK",
                last_run=latest.get("mtime"),
                ok=True,
                source="backups.dir",
                detail={"name": latest.get("name"), "bytes": latest.get("bytes")},
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("time_rail: backup list unavailable", exc_info=True)
    try:
        from modstore_server.release_train import history_dir

        hdir = history_dir()
        ondemand = sorted(hdir.glob("*ondemand*.json"), key=lambda p: p.name, reverse=True)
        if ondemand:
            latest_ondemand = ondemand[0]
            derived["BKOND"] = _facade()._node_status_shell(
                "BKOND",
                last_run=_facade()
                .datetime.fromtimestamp(latest_ondemand.stat().st_mtime, _facade().timezone.utc)
                .isoformat(),
                ok=True,
                source="release_train_history.ondemand",
                detail={"name": latest_ondemand.name, "path": str(latest_ondemand)},
            )
    except RECOVERABLE_ERRORS:
        _facade().logger.debug("time_rail: ondemand backup history unavailable", exc_info=True)
    if rt_state:
        current = str(rt_state.get("current") or "1.0.0.0")
        day_index = int(rt_state.get("day_index") or 0)
        bump_ok = guard is None
        rt_detail = {
            "current": current,
            "last_bump_day": rt_state.get("last_bump_day"),
            "day_index": day_index,
        }
        derived["RT"] = _facade()._node_status_shell(
            "RT",
            last_run=_facade()._iso_or_none(rt_state.get("last_bump_at")),
            ok=bump_ok,
            guard_active=guard is not None,
            source="release_train.json",
            detail=rt_detail,
            observed=True,
        )
        major_today = day_index > 0 and day_index % 100 == 0
        installer_today = current.split(".")[-1:] == ["0"] and day_index > 0
        every_30 = day_index > 0 and day_index % 30 == 0
        derived["CENT"] = _facade()._node_status_shell(
            "CENT",
            last_run=_facade()._iso_or_none(rt_state.get("last_bump_at")),
            ok=None,
            source="release_train.json",
            detail={**rt_detail, "decision": major_today},
            observed=True,
            proof_status="decision_true" if major_today else "decision_false",
        )
        derived["MAJ"] = _facade()._node_status_shell(
            "MAJ",
            last_run=_facade()._iso_or_none(
                rt_state.get("last_major_push_at") or rt_state.get("last_bump_at")
            ),
            ok=True if major_today else None,
            source="release_train.json",
            detail={**rt_detail, "is_major_day": major_today},
            observed=True,
            proof_status="planned" if major_today else "decision_not_taken",
        )
        derived["GATE"] = _facade()._node_status_shell(
            "GATE",
            last_run=_facade()._iso_or_none(rt_state.get("last_bump_at")),
            ok=None,
            source="release_train.json",
            detail={**rt_detail, "decision": installer_today},
            observed=True,
            proof_status="decision_true" if installer_today else "decision_false",
        )
        derived["P6G"] = _facade()._node_status_shell(
            "P6G",
            last_run=_facade()._iso_or_none(rt_state.get("last_bump_at")),
            ok=None,
            source="release_train.json",
            detail={**rt_detail, "decision": every_30},
            observed=True,
            proof_status="decision_true" if every_30 else "decision_false",
        )
    metric = _facade()._retention_metric()
    if metric is not None:
        err = str(getattr(metric, "error", "") or "").strip()
        derived["R"] = _facade()._node_status_shell(
            "R",
            last_run=_facade()._iso_or_none(getattr(metric, "created_at", None)),
            ok=not err,
            source="employee_execution_metric",
            detail={"task_brief": getattr(metric, "task_brief", ""), "error": err},
        )
    latest_digest_created: _facade().Optional[str] = None
    latest_digest_record_id = 0
    latest_release_kind = ""
    latest_line_dispatch: _facade().Dict[str, _facade().Any] = {}
    latest_phase_c_pipeline: _facade().Dict[str, _facade().Any] = {}
    latest_phase_c: _facade().Dict[str, _facade().Any] = {}
    digest = _facade()._latest_digest_row()
    state = {
        "derived": derived,
        "digest": digest,
        "guard": guard,
        "latest_digest_created": latest_digest_created,
        "latest_digest_record_id": latest_digest_record_id,
        "latest_line_dispatch": latest_line_dispatch,
        "latest_phase_c": latest_phase_c,
        "latest_phase_c_pipeline": latest_phase_c_pipeline,
        "latest_release_kind": latest_release_kind,
    }
    return _derive_from_sources_tail(state)


from modstore_server.time_rail_workflow_part02_part01 import (
    collect_node_runtime_status as collect_node_runtime_status,
)
from modstore_server.time_rail_workflow_part02_part01 import graph_api_payload as graph_api_payload
from modstore_server.time_rail_workflow_part02_part01 import (
    sync_missing_evidence_backlog as sync_missing_evidence_backlog,
)
