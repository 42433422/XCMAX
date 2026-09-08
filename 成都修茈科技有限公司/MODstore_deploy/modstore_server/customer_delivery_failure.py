"""Business verification failure returns to the original ticket with bounded rework."""

from __future__ import annotations

from typing import Any

from modstore_server.customer_issue_delivery_contract import issue_resolution
from modstore_server.customer_issue_intake import enqueue_issue
from modstore_server.customer_service_tools import json_dumps


def apply_runtime_failure(
    db: Any, ticket: Any, evidence: dict[str, Any], record: dict[str, Any]
) -> None:
    generation = str(record.get("generation") or "")
    resolution = issue_resolution(ticket, evidence)
    resolution.update(
        state="repair_failed",
        runtime_failure=record.get("business_verification"),
        failed_generation=generation,
        last_error="客户宿主实际业务验证失败",
    )
    evidence["resolution"] = resolution
    ticket.status, ticket.closed_at, ticket.decision_status = "processing", None, "pending"
    handled = list(evidence.get("automatic_rework_generations") or [])
    if generation in handled:
        return
    if not record.get("release_evidence"):
        resolution.update(
            state="awaiting_runtime", last_error="业务验证失败且宿主发行身份尚未核实，待核实后返工"
        )
        return
    evidence["acceptance_status"] = "pending"
    if len(handled) >= 1:
        resolution["last_error"] = "自动返工后业务验证仍失败，保留原单待进一步排查"
        return
    evidence["automatic_rework_generations"] = [*handled, generation]
    evidence["runtime_mod_id"] = record["id"]
    source: dict[str, Any] = next(
        (row for row in evidence.get("delivery_artifacts", []) if row.get("id") == record["id"]), {}
    )
    evidence["rework_artifact_kind"] = (
        "employee" if source.get("source_employee_pack_id") else "module"
    )
    evidence.setdefault("target_mod_id", record["id"])
    evidence["installed_version"] = record["version"]
    evidence["requirements"] = str(evidence.get("requirements") or ticket.summary or "")
    evidence["runtime_failure"] = record["business_verification"]
    resolution["state"] = "queued_rework"
    ticket.evidence_json = json_dumps(evidence)
    enqueue_issue(db, ticket, revision=f"runtime-failed:{generation}", private_factory=True)


def reconcile_runtime_failures(db: Any, ticket: Any) -> bool:
    from modstore_server.customer_delivery_receipts import trusted_host_release
    from modstore_server.customer_service_tools import json_loads

    evidence = json_loads(ticket.evidence_json, {})
    generation = str(evidence.get("delivery_generation") or "")
    for record in evidence.get("receipt_events", []):
        if (
            record.get("stage") != "verification_failed"
            or record.get("release_evidence")
            or str(record.get("generation") or "") != generation
        ):
            continue
        release = trusted_host_release(str(record.get("host_sha") or ""))
        if not release:
            continue
        record["release_evidence"] = release
        record["failure_recorded"] = True
        apply_runtime_failure(db, ticket, evidence, record)
        ticket.evidence_json = json_dumps(evidence)
        db.flush()
        return True
    return False
