"""定制交付的最终闭环判定。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from modstore_server.customer_delivery_receipts import all_artifacts_running
from modstore_server.customer_service_delivery_models import (
    custom_delivery_commerce_blockers,
)
from modstore_server.models_cs import CustomerServiceTicket


def complete_delivery_if_ready(ticket: CustomerServiceTicket, evidence: dict[str, Any]) -> None:
    """商务、客户验收和全部产物在正式主线宿主的业务验证齐全才完成。"""
    artifact_rows = evidence.get("delivery_artifacts")
    artifact_rows = artifact_rows if isinstance(artifact_rows, list) else []
    artifacts = {
        (str(row.get("kind")), str(row.get("id")))
        for row in artifact_rows
        if isinstance(row, dict) and row.get("kind") and row.get("id")
    }
    run_rows = evidence.get("runs")
    run_rows = run_rows if isinstance(run_rows, list) else []
    runs = [r for r in run_rows if isinstance(r, dict)]
    for run in reversed(runs):
        if artifacts:
            break
        artifact_value = run.get("artifact")
        artifact: dict[str, Any] = artifact_value if isinstance(artifact_value, dict) else {}
        if artifact.get("mod_id"):
            artifacts.add(("module", str(artifact["mod_id"])))
        if artifact.get("pack_id"):
            artifacts.add(("employee", str(artifact["pack_id"])))
        if artifacts:
            break
    receipt_rows = evidence.get("install_receipts")
    receipt_rows = receipt_rows if isinstance(receipt_rows, list) else []
    receipts = [r for r in receipt_rows if isinstance(r, dict)]
    installed = {(str(r.get("kind")), str(r.get("id"))) for r in receipts}
    if (
        str(evidence.get("acceptance_status") or "") == "accepted"
        and not custom_delivery_commerce_blockers(evidence)
        and artifacts
        and artifacts.issubset(installed)
        and all_artifacts_running(ticket, evidence)
    ):
        closed_at = datetime.now(UTC)
        setattr(ticket, "status", "resolved")
        setattr(ticket, "decision_status", "approved")
        setattr(ticket, "closed_at", closed_at)
        evidence["delivered_at"] = closed_at.isoformat()
        from modstore_server.customer_issue_delivery_contract import issue_resolution

        resolution = issue_resolution(ticket, evidence)
        resolution.update(state="resolved", resolved_at=closed_at.isoformat())
        evidence["resolution"] = resolution
