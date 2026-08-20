# mypy: disable-error-code="union-attr"
"""Live evidence resolvers and read-side status for the strategic council."""

from __future__ import annotations

from typing import Any, Mapping

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _council_module():
    from modstore_server import strategic_council

    return strategic_council


def live_persy_evidence(strategy_intent: str) -> dict[str, Any]:
    """Retrieve real Persy chunks and retain only source identities/digests."""
    council = _council_module()
    try:
        from modstore_server.xiaoc_cs_ssot import retrieve_persy_knowledge

        chunks = retrieve_persy_knowledge(strategy_intent, top_k=5)
    except RECOVERABLE_ERRORS as exc:
        return {
            "grounded": False,
            "dataset_id": "persy-knowledge",
            "source_count": 0,
            "document_refs": [],
            "error": type(exc).__name__,
        }
    references: list[str] = []
    evidence_rows: list[dict[str, str]] = []
    for index, chunk in enumerate(chunks if isinstance(chunks, list) else []):
        if not isinstance(chunk, dict):
            continue
        reference = ""
        for key in (
            "document_id",
            "source_id",
            "chunk_id",
            "id",
            "source_name",
            "source",
        ):
            reference = council._text(chunk.get(key), 256)
            if reference:
                break
        if not reference:
            reference = f"chunk-{index + 1}-{council._digest(chunk)[:16]}"
        references.append(reference)
        evidence_rows.append({"ref": reference, "sha256": council._digest(chunk)})
    return {
        "grounded": bool(references),
        "dataset_id": "persy-knowledge",
        "source_count": len(references),
        "document_refs": references,
        "query_sha256": council._digest(strategy_intent),
        "retrieval_sha256": council._digest(evidence_rows),
        "source": "persy_live_retrieval",
    }


def live_para_evidence(*, goal_id: str, loop_run_id: str, para_task_id: str) -> dict[str, Any]:
    """Verify Goal and Para linkage against the strategic DB and Loop ledger."""
    council = _council_module()
    goal_status = ""
    try:
        from modstore_server.db.base import get_session_factory
        from modstore_server.db.strategic import StrategicDecision

        with get_session_factory()() as session:
            goal = (
                session.query(StrategicDecision)
                .filter(StrategicDecision.decision_id == goal_id)
                .first()
            )
            goal_status = council._text(getattr(goal, "status", ""), 64) if goal else ""
    except RECOVERABLE_ERRORS:
        goal_status = ""
    loop_rows: list[dict[str, Any]] = []
    try:
        from modstore_server.self_maintenance_loop_runner import _read_ledger

        loop_rows = [
            row
            for row in _read_ledger(limit=20_000)
            if council._text(row.get("run_id"), 128) == loop_run_id
        ]
    except RECOVERABLE_ERRORS:
        loop_rows = []
    linked_rows = [
        row
        for row in loop_rows
        if council._text(row.get("para_task_id") or row.get("task_id"), 128) == para_task_id
    ]
    latest = loop_rows[-1] if loop_rows else {}
    return {
        "linked": bool(goal_status and linked_rows),
        "source_verified": bool(goal_status and linked_rows),
        "goal_id": goal_id,
        "loop_run_id": loop_run_id,
        "para_task_id": para_task_id,
        "goal_status": goal_status,
        "loop_status": council._text(latest.get("status") or latest.get("phase"), 64),
        "task_status": council._text(linked_rows[-1].get("status"), 64) if linked_rows else "",
        "source": "strategic_decisions+self_maintenance_loop_ledger",
        "loop_evidence_sha256": council._digest(linked_rows),
    }


def live_veto_state(*, run_id: str, loop_run_id: str) -> dict[str, Any]:
    """Read the existing redline channel and immutable autonomy audit."""
    council = _council_module()
    try:
        from modstore_server.autonomy_decision_audit import (
            build_autonomy_decision_evidence,
        )
        from modstore_server.redline_approval_gate import get_pending_redline_requests

        pending = get_pending_redline_requests()
        audit = build_autonomy_decision_evidence(window_days=30, limit=1000)
        rows = audit.get("items") if isinstance(audit.get("items"), list) else []
        correlated_vetoes = [
            row
            for row in rows
            if isinstance(row, dict)
            and council._text(row.get("decision"), 32) == "veto"
            and council._text(row.get("run_id"), 128) in {run_id, loop_run_id}
        ]
        return {
            "available": True,
            "vetoed": bool(correlated_vetoes),
            "pending_count": len(pending),
            "source": "redline_approval+autonomy_decision_audit",
            "audit_append_only_enforced": audit.get("append_only_enforced") is True,
            "correlated_veto_count": len(correlated_vetoes),
        }
    except RECOVERABLE_ERRORS as exc:
        return {
            "available": False,
            "vetoed": False,
            "pending_count": 0,
            "source": "redline_approval+autonomy_decision_audit",
            "error": type(exc).__name__,
        }


def public_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "receipt_id",
            "created_at",
            "proposal_id",
            "run_id",
            "package_id",
            "version",
            "package_sha256",
            "goal_id",
            "loop_run_id",
            "para_task_id",
            "request_sha256",
            "record_hash",
            "verified",
            "blockers",
            "roles",
            "veto",
        )
    }


def strategic_council_status(*, limit: int = 20) -> dict[str, Any]:
    council = _council_module()
    try:
        from modstore_server.retort_clarification_gate import (
            list_clarifications,
            sweep_expired_clarifications,
        )

        sweep_expired_clarifications()
        clarification_summary = list_clarifications(include_terminal=False, limit=20)
    except RECOVERABLE_ERRORS as exc:
        clarification_summary = {
            "ok": False,
            "error": type(exc).__name__,
            "open_count": 0,
        }
    path = council.strategic_council_ledger_path()
    if not path.is_file():
        return {
            "schema": council.STATUS_SCHEMA_VERSION,
            "ok": True,
            "ready": False,
            "append_only": True,
            "hash_chain_verified": True,
            "verified_receipt_count": 0,
            "attempt_count": 0,
            "roles": {},
            "latest_receipt": {},
            "recent_receipts": [],
            "retort_clarifications": clarification_summary,
        }
    with path.open("r", encoding="utf-8") as file_obj:
        rows = council._read_rows_unlocked(file_obj)
    integrity_ok, _ = council._verify_rows(rows)
    verified = [row for row in rows if row.get("verified") is True] if integrity_ok else []
    latest = verified[-1] if verified else {}
    roles = latest.get("roles") if isinstance(latest.get("roles"), dict) else {}
    bounded = max(1, min(int(limit or 20), 100))
    return {
        "schema": council.STATUS_SCHEMA_VERSION,
        "ok": integrity_ok,
        "ready": bool(integrity_ok and latest),
        "append_only": True,
        "hash_chain_verified": integrity_ok,
        "verified_receipt_count": len(verified),
        "attempt_count": len(rows),
        "roles": roles,
        "latest_receipt": public_receipt(latest) if latest else {},
        "recent_receipts": [public_receipt(row) for row in rows[-bounded:]],
        "retort_clarifications": clarification_summary,
    }
