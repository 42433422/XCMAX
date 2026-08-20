# mypy: disable-error-code="valid-type"
"""Self-maintenance merge-decision projection."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _score_summary(value: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "score": value.get("score"),
        "max_allowed": value.get("max_allowed"),
        "min_allowed": value.get("min_allowed"),
        "reason": value.get("reason"),
        "source": value.get("source"),
        "available": value.get("available"),
        "passed": value.get("passed"),
    }


def _merge_decision_summary(state, value: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(value, dict):
        return {}
    risk_v1 = _score_summary(value.get("risk_score"))
    safety_v2 = _score_summary(value.get("safety_score_v2"))
    safety_v3 = _score_summary(value.get("safety_score_v3"))
    qa = value.get("qa")
    if not isinstance(qa, dict):
        qa = {}
    review = value.get("review")
    if not isinstance(review, dict):
        review = {}
    final = value.get("final")
    if not isinstance(final, dict):
        final = {}
    roster_gate = value.get("roster_gate")
    if not isinstance(roster_gate, dict):
        roster_gate = {}
    governance_gate = value.get("governance_gate")
    if not isinstance(governance_gate, dict):
        governance_gate = {}
    active_gates = value.get("active_gates")
    state["active_gates"] = active_gates if isinstance(active_gates, dict) else {}
    evolution_gate = value.get("evolution_gate")
    if not isinstance(evolution_gate, dict):
        evolution_gate = {}
    return {
        "action": str(value.get("action") or "").strip(),
        "reason": str(value.get("reason") or "").strip(),
        "ok": value.get("ok"),
        "active_gates": state["active_gates"],
        "evolution_gate": evolution_gate,
        "risk_score_v1": risk_v1,
        "safety_score_v2": safety_v2,
        "safety_score_v3": safety_v3,
        "roster_gate": roster_gate,
        "governance_gate": governance_gate,
        "qa_verdict": str(qa.get("verdict") or "").strip(),
        "review_max_severity": str(review.get("max_severity") or "").strip(),
        "branch": str(
            value.get("branch")
            or value.get("target_branch")
            or final.get("branch")
            or final.get("target_branch")
            or ""
        ).strip(),
        "para_task_id": str(value.get("para_task_id") or final.get("para_task_id") or "").strip(),
    }
