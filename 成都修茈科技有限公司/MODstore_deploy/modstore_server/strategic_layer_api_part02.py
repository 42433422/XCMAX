# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.strategic_layer_api")


@_facade().router.post("/autonomy/seed", response_model=_facade().Dict[str, _facade().Any])
def seed_autonomy_rules(
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """幂等 seed 默认自治边界规则（13 条）。"""
    try:
        inserted = _facade().seed_default_boundaries()
        return {"ok": True, "inserted": inserted, "skipped": 13 - inserted, "total_default": 13}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("seed_default_boundaries failed")
        raise _facade().HTTPException(500, f"seed failed: {exc}") from exc


@_facade().router.get("/health", response_model=_facade().Dict[str, _facade().Any])
def strategic_layer_health(
    _: _facade().User = _facade().Depends(_facade().get_current_user),
) -> _facade().Dict[str, _facade().Any]:
    """战略层健康检查（用于 CI smoke 与监控）。"""
    try:
        ledger = _facade()._ledger()
        decisions = ledger.list_recent(limit=1)
        action_items = _facade()._meeting_service().list_action_items(limit=1)
        reports = _facade()._report_service().list_reports(limit=1)
        return {
            "ok": True,
            "component": "strategic-layer",
            "decisions_queryable": True,
            "decisions_sample_count": len(decisions),
            "action_items_queryable": True,
            "action_items_sample_count": len(action_items),
            "reports_queryable": True,
            "reports_sample_count": len(reports),
            "autonomy_actions": [a.value for a in _facade().AutonomyAction],
            "decision_statuses": [s.value for s in _facade().DecisionStatus],
            "decision_types": [t.value for t in _facade().DecisionType],
            "decided_by": [d.value for d in _facade().DecidedBy],
            "meeting_statuses": [s.value for s in _facade().MeetingStatus],
            "meeting_types": [t.value for t in _facade().MeetingType],
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("strategic layer health check failed")
        raise _facade().HTTPException(500, f"health check failed: {exc}") from exc
