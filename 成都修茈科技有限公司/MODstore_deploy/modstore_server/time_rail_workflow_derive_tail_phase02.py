# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# ruff: noqa: E402, F401, I001
"""Time-rail derivation tail phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.time_rail_workflow")


def _derive_from_sources_tail_phase_02(state):
    state["staged"] = _facade()._latest_ops_staged_change()
    if state["staged"] is not None:
        state["staged_detail"] = {
            "id": getattr(state["staged"], "id", None),
            "branch": getattr(state["staged"], "branch", ""),
            "status": getattr(state["staged"], "status", ""),
            "files_changed_count": getattr(state["staged"], "files_changed_count", None),
        }
        state["created"] = _facade()._iso_or_none(getattr(state["staged"], "created_at", None))
        state["approved"] = _facade()._iso_or_none(getattr(state["staged"], "approved_at", None))
        state["deployed"] = _facade()._iso_or_none(getattr(state["staged"], "deployed_at", None))
        state["derived"]["STG"] = _facade()._node_status_shell(
            "STG",
            last_run=state["created"],
            ok=True,
            source="ops_staged_changes",
            detail=state["staged_detail"],
        )
        if state["approved"]:
            state["derived"]["APPR"] = _facade()._node_status_shell(
                "APPR",
                last_run=state["approved"],
                ok=True,
                source="ops_staged_changes",
                detail=state["staged_detail"],
            )
        if state["deployed"]:
            state["derived"]["V10SYNC"] = _facade()._node_status_shell(
                "V10SYNC",
                last_run=state["deployed"],
                ok=True,
                source="ops_staged_changes",
                detail=state["staged_detail"],
            )
            state["derived"]["MERGE"] = _facade()._node_status_shell(
                "MERGE",
                last_run=state["deployed"],
                ok=True,
                source="ops_staged_changes",
                detail=state["staged_detail"],
            )
        else:
            for state["nid"], state["reason"] in (
                ("APPR", "ops_staged_change_waiting_approval"),
                ("V10SYNC", "ops_staged_change_not_deployed"),
                ("MERGE", "ops_staged_change_not_deployed"),
                ("WB_M", "ops_staged_change_not_deployed"),
            ):
                if state["nid"] not in state["derived"]:
                    state["derived"][state["nid"]] = _facade()._decision_not_taken_status(
                        state["nid"],
                        last_run=state["approved"] or state["created"],
                        source="ops_staged_changes",
                        reason=state["reason"],
                        detail=state["staged_detail"],
                    )
    state["cr"] = _facade()._latest_change_request()
    if state["cr"] is not None:
        state["branch"] = str(getattr(state["cr"], "git_branch", "") or "")
        state["base_sha"] = str(getattr(state["cr"], "base_commit_sha", "") or "")
        state["staged_sha"] = str(getattr(state["cr"], "staged_commit_sha", "") or "")
        state["approved"] = _facade()._iso_or_none(getattr(state["cr"], "approved_at", None))
        state["applied"] = _facade()._iso_or_none(getattr(state["cr"], "applied_at", None))
        state["cr_detail"] = {
            "id": getattr(state["cr"], "id", None),
            "source_employee_id": getattr(state["cr"], "source_employee_id", ""),
            "status": getattr(state["cr"], "status", ""),
            "change_kind": getattr(state["cr"], "change_kind", ""),
            "git_branch": state["branch"],
            "base_commit_sha": state["base_sha"],
            "staged_commit_sha": state["staged_sha"],
        }
        state["created"] = _facade()._iso_or_none(
            getattr(state["cr"], "created_at", None) or getattr(state["cr"], "submitted_at", None)
        )
        state["derived"]["CS_CHG"] = _facade()._node_status_shell(
            "CS_CHG",
            last_run=state["created"],
            ok=True,
            source="employee_change_requests",
            detail=state["cr_detail"],
        )
        if state["branch"] or state["staged_sha"]:
            state["derived"]["GITCR"] = _facade()._node_status_shell(
                "GITCR",
                last_run=state["created"],
                ok=bool(state["branch"] and state["staged_sha"]),
                source="employee_change_requests.git",
                detail=state["cr_detail"],
                observed=True,
            )
            if "STG" not in state["derived"] and state["branch"] and state["staged_sha"]:
                state["derived"]["STG"] = _facade()._node_status_shell(
                    "STG",
                    last_run=state["created"],
                    ok=True,
                    source="employee_change_requests.git",
                    detail=state["cr_detail"],
                    observed=True,
                )
        if state["approved"] and "APPR" not in state["derived"]:
            state["derived"]["APPR"] = _facade()._node_status_shell(
                "APPR",
                last_run=state["approved"],
                ok=True,
                source="employee_change_requests",
                detail=state["cr_detail"],
            )
        elif "APPR" not in state["derived"]:
            state["derived"]["APPR"] = _facade()._decision_not_taken_status(
                "APPR",
                last_run=state["created"],
                source="employee_change_requests",
                reason="change_request_waiting_approval",
                detail=state["cr_detail"],
            )
        for state["nid"] in ("V10SYNC", "MERGE", "WB_M"):
            if state["nid"] in state["derived"]:
                continue
            state["derived"][state["nid"]] = _facade()._decision_not_taken_status(
                state["nid"],
                last_run=state["applied"] or state["approved"] or state["created"],
                source="employee_change_requests",
                reason="change_request_not_deployed",
                detail=state["cr_detail"],
            )
        state["derived"]["O7"] = _facade()._node_status_shell(
            "O7",
            last_run=state["created"],
            ok=True,
            source="employee_change_requests",
            detail={"bridge": "feedback-to-change-request", **state["cr_detail"]},
        )
        state["derived"]["Vibe08"] = _facade()._node_status_shell(
            "Vibe08",
            last_run=state["created"],
            ok=True,
            source="employee_change_requests",
            detail={"bridge": "change-request-to-next-digest", **state["cr_detail"]},
        )
    for state["nid"] in ("O5", "O6"):
        if state["nid"] not in state["derived"]:
            state["derived"][state["nid"]] = _facade()._decision_not_taken_status(
                state["nid"],
                last_run=state["latest_digest_created"],
                source="production_line_orchestrator.static_skip",
                reason="static_skip_step_not_triggered",
                detail={"release_kind": state["latest_release_kind"] or "unknown"},
            )
    _facade()._ensure_non_triggered_time_rail_decisions(
        state["derived"],
        last_run=state["latest_digest_created"],
        record_id=int(state["latest_digest_record_id"] or 0),
        release_kind=state["latest_release_kind"] or "unknown",
        line_dispatch=state["latest_line_dispatch"],
        phase_c_pipeline=state["latest_phase_c_pipeline"],
        phase_c=state["latest_phase_c"],
        guard_active=bool(state["guard"]),
    )
    _facade()._ensure_p2_line_mappings(
        state["derived"],
        record_id=int(state["latest_digest_record_id"] or 0),
        release_kind=state["latest_release_kind"] or "unknown",
    )
    return state["derived"]
