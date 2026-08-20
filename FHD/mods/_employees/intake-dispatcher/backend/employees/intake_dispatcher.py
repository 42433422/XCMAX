"""Deterministic intake deduplication and routing planner.

Live ``ops.intake.customer_ticket`` runs return a ``routing_plan`` plus
``side_effects`` describing downstream employee dispatch. The MODstore
``incident_bus`` consumes that plan and executes the proposed owners.
Burn-in probes keep ``read_only=True`` / ``side_effects=[]`` for duty acceptance.
"""

from __future__ import annotations

import hashlib
from typing import Any


def _incident_blob(payload: dict[str, Any]) -> dict[str, Any]:
    incident = payload.get("incident")
    return incident if isinstance(incident, dict) else {}


def _is_burn_in(payload: dict[str, Any]) -> bool:
    return bool(payload.get("burn_in")) or bool(payload.get("burn_in_read_only"))


def _normalize_requests(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept burn-in ``requests`` or incident-bus / 客服工单 shaped payloads."""

    requests = payload.get("requests")
    if isinstance(requests, list) and requests:
        return [item if isinstance(item, dict) else {} for item in requests[:200]]

    incident = _incident_blob(payload)
    ticket_no = str(
        payload.get("ticket_no")
        or payload.get("subject_id")
        or incident.get("ticket_no")
        or incident.get("subject_id")
        or payload.get("ticket_id")
        or incident.get("ticket_id")
        or ""
    ).strip()
    summary = str(
        payload.get("summary")
        or incident.get("summary")
        or payload.get("title")
        or incident.get("title")
        or payload.get("task")
        or ""
    ).strip()
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    if not summary:
        summary = str(raw.get("body") or raw.get("title") or "").strip()
    source = str(payload.get("source") or incident.get("source") or "").strip().lower()
    event_type = str(payload.get("event_type") or "").strip()
    if (
        ticket_no
        or summary
        or source == "customer_ticket"
        or event_type.endswith("customer_ticket")
    ):
        text = summary or f"客服工单 {ticket_no or '?'} 待归一化"
        return [
            {
                "id": ticket_no or f"intake-{hashlib.sha256(text.encode()).hexdigest()[:12]}",
                "text": text[:2000],
                "route_hint": "user-customer-service-officer",
            }
        ]
    return []


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx  # host side effects are applied by incident_bus from routing_plan
    body = dict(payload or {})
    requests = _normalize_requests(body)
    if not requests:
        return _failed("requests must be a non-empty list", "missing_requests")
    planned: list[dict[str, str]] = []
    seen: set[str] = set()
    issues: list[dict[str, str]] = []
    for index, raw in enumerate(requests[:200]):
        item = raw if isinstance(raw, dict) else {}
        request_id = str(item.get("id") or "").strip()[:160]
        text = " ".join(str(item.get("text") or "").split())[:2000]
        owner = str(item.get("route_hint") or "task-router-officer").strip()[:160]
        if not request_id or not text:
            issues.append({"code": "missing_request_context", "path": f"requests[{index}]"})
            continue
        fingerprint = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()[:16]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        planned.append(
            {
                "request_id": request_id,
                "fingerprint": fingerprint,
                "proposed_owner": owner,
            }
        )

    burn_in = _is_burn_in(body)
    if burn_in:
        side_effects: list[dict[str, str]] = []
        read_only = True
        summary = (
            f"需求入口已只读核对：{len(requests[:200])} 条输入归并为 {len(planned)} 条唯一需求，"
            f"{len(issues)} 个缺口；未派发或回复。"
        )
    else:
        side_effects = [
            {
                "action": "dispatch_employee",
                "employee_id": row["proposed_owner"],
                "request_id": row["request_id"],
            }
            for row in planned
        ]
        read_only = False
        summary = (
            f"需求入口已规划派发：{len(requests[:200])} 条输入归并为 {len(planned)} 条唯一需求，"
            f"{len(issues)} 个缺口；side_effects={len(side_effects)}（由 incident_bus 执行）。"
        )

    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": summary,
        "routing_plan": planned,
        "duplicate_count": max(0, len(requests[:200]) - len(planned) - len(issues)),
        "issues": issues,
        "evidence": (
            ["input.requests"]
            if isinstance(body.get("requests"), list)
            else ["input.incident_or_customer_ticket"]
        ),
        "read_only": read_only,
        "side_effects": side_effects,
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "error": f"{code}: {message}",
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
