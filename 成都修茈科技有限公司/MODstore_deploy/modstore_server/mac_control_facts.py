"""Read existing business sources; isolate unavailable evidence from empty results."""

import json
import re
import time

from modstore_server.models_cs import CustomerServiceTicket
from modstore_server.standard_delivery_api import build_standard_delivery_rows


def redact(text):
    return re.sub(
        r"(?i)(bearer\s+|(?:api[_-]?key|password|token|secret)\s*[:=]\s*)[^\s,;]+",
        r"\1[redacted]",
        str(text),
    )[:3000]


def customer_facts(db, customer_id=None, ticket_id=None):
    query = db.query(CustomerServiceTicket)
    if customer_id:
        query = query.filter_by(user_id=customer_id)
    if ticket_id:
        query = query.filter_by(id=ticket_id)
    tickets = []
    for row in query.order_by(CustomerServiceTicket.updated_at.desc()).limit(50):
        try:
            evidence = json.loads(row.evidence_json or "{}")
        except ValueError:
            evidence = {}
        resolution = evidence.get("resolution") or {}
        tickets.append(
            {
                "id": row.id,
                "ticket_no": row.ticket_no,
                "customer_id": row.user_id,
                "title": row.title,
                "status": row.status,
                "assigned_admin_id": row.assigned_admin_id,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "resolution": {
                    key: resolution.get(key)
                    for key in (
                        "state",
                        "route",
                        "target_mod_id",
                        "reported_version",
                        "incident_event_id",
                    )
                },
                "source": f"customer_service_tickets:{row.id}",
                "receipt_counts": {
                    key: len(evidence.get(key) or [])
                    for key in ("install_receipts", "receipt_events")
                },
            }
        )
    deliveries = build_standard_delivery_rows(db)
    if customer_id:
        deliveries = [r for r in deliveries if (r.get("account") or {}).get("id") == customer_id]
    return {
        "source": "customer_service_tickets+standard_delivery_api",
        "observed_at": time.time(),
        "customer_id": customer_id,
        "tickets": tickets,
        "deliveries": deliveries,
    }


def context_facts(db, request):
    from modstore_server.deploy_context import health_payload
    from modstore_server.operational_errors import RECOVERABLE_ERRORS

    result = {"observed_at": time.time(), "sources": []}
    if request.get("customer_id") or request.get("ticket_id"):
        result["sources"].append(
            customer_facts(db, request.get("customer_id"), request.get("ticket_id"))
        )
    try:
        identity = health_payload()
        result["sources"].append(
            {
                "source": "modstore:health",
                "observed_at": time.time(),
                "git_sha": identity.get("git_sha"),
                "release_id": identity.get("release_id"),
            }
        )
    except RECOVERABLE_ERRORS as exc:
        result["sources"].append({"source": "modstore:health", "error": type(exc).__name__})
    try:
        from modstore_server.xiaoc_cs_ssot import retrieve_knowledge_for_mode

        chunks = retrieve_knowledge_for_mode(request.get("message", ""), mode="admin", top_k=3)
        result["sources"].append(
            {
                "source": "persy",
                "observed_at": time.time(),
                "status": "found" if chunks else "no_matches",
                "references": [
                    {
                        "source": c.get("source") or c.get("document_id"),
                        "dataset_id": c.get("dataset_id"),
                        "excerpt": redact(c.get("text") or c.get("content") or ""),
                    }
                    for c in chunks
                    if isinstance(c, dict)
                ],
            }
        )
    except RECOVERABLE_ERRORS as exc:
        result["sources"].append({"source": "persy", "error": type(exc).__name__})
    return result
