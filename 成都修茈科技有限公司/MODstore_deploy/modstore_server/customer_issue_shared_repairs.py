"""Explicit public-repair reuse; customer ownership and acceptance stay independent."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db, require_admin
from modstore_server.customer_delivery_receipts import canonical_sha256
from modstore_server.customer_issue_delivery_contract import issue_resolution
from modstore_server.customer_service_tools import audit, json_dumps, json_loads
from modstore_server.models import EmployeeChangeRequest, IncidentEvent, User
from modstore_server.models_cs import CustomerServiceAction, CustomerServiceTicket

router = APIRouter()
_ACTION = "issue.repair.shared"


def _evidence(ticket: Any) -> dict[str, Any]:
    value = json_loads(ticket.evidence_json, {})
    return value if isinstance(value, dict) else {}


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return 0


def shared_repair_signature(ticket: Any) -> str:
    """Exact reported problem and source identity, never fuzzy title similarity."""
    evidence = _evidence(ticket)
    if (
        ticket.intent != "product_issue"
        or issue_resolution(ticket, evidence).get("route") != "shared_core"
        or evidence.get("target_mod_id")
        or evidence.get("delivery_managed_by")
        or ticket.subject_type not in (None, "", "host")
        or ticket.subject_id
    ):
        return ""
    sha = str(evidence.get("git_sha") or "")
    version = str(
        evidence.get("product_version") or evidence.get("installed_version") or ""
    )
    description = " ".join(str(ticket.summary or "").split())
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not version or len(description) < 4:
        return ""
    return canonical_sha256(
        {
            "git_sha": sha,
            "version": version,
            "description": description,
            "issue_domain": str(evidence.get("issue_domain") or "platform"),
        }
    )


def _source_repair(
    db: Session,
    source: CustomerServiceTicket | None,
    action: CustomerServiceAction | None,
    signature: str,
) -> EmployeeChangeRequest | None:
    if source is None or action is None or not signature:
        return None
    resolution = issue_resolution(source, _evidence(source))
    if (
        shared_repair_signature(source) != signature
        or source.status == "expired"
        or resolution.get("repair_verified") is not True
        or action.ticket_id != source.id
        or action.user_id != source.user_id
        or action.action_type != "issue.repair.result"
        or action.status != "completed"
        or action.id <= _integer(resolution.get("reopen_after_action_id"))
    ):
        return None
    result = json_loads(str(action.result_json or ""), {})
    request = json_loads(str(action.request_json or ""), {})
    if not isinstance(result, dict) or result.get("team_verified") is not True:
        return None
    if not isinstance(request, dict) or not str(action.target_id).isdigit():
        return None
    cr = db.get(EmployeeChangeRequest, int(action.target_id))
    if (
        cr is None
        or cr.source_employee_id != request.get("worker_id")
        or cr.status != "applied"
        or not re.fullmatch(r"[0-9a-f]{40}", str(cr.staged_commit_sha or ""))
    ):
        return None
    return cr


def active_shared_repair(db: Session, ticket: Any) -> dict[str, Any] | None:
    """Read the current owner-bound link; reopening or changed evidence invalidates it."""
    if ticket is None or ticket.status != "processing" or ticket.closed_at:
        return None
    evidence = _evidence(ticket)
    resolution = issue_resolution(ticket, evidence)
    action = (
        db.query(CustomerServiceAction)
        .filter_by(
            ticket_id=ticket.id,
            user_id=ticket.user_id,
            action_type=_ACTION,
            status="completed",
        )
        .filter(
            CustomerServiceAction.id
            > _integer(resolution.get("reopen_after_action_id"))
        )
        .order_by(CustomerServiceAction.id.desc())
        .first()
    )
    if action is None:
        return None
    link = json_loads(str(action.request_json or ""), {})
    if not isinstance(link, dict):
        return None
    signature = shared_repair_signature(ticket)
    if not signature or signature != link.get("match_sha256"):
        return None
    source = db.get(CustomerServiceTicket, _integer(link.get("source_ticket_id")))
    original = db.get(CustomerServiceAction, _integer(link.get("source_action_id")))
    cr = _source_repair(db, source, original, signature)
    if (
        source is None
        or original is None
        or cr is None
        or str(cr.id) != action.target_id
    ):
        return None
    return {
        "action_id": int(action.id),
        "source_action_id": int(original.id),
        "source_ticket_id": int(source.id),
        "change_request_id": int(cr.id),
        "worker_id": cr.source_employee_id,
        "match_sha256": signature,
    }


def _in_flight(db: Session, ticket: Any) -> bool:
    resolution = issue_resolution(ticket, _evidence(ticket))
    actions = (
        db.query(CustomerServiceAction)
        .filter_by(ticket_id=ticket.id, user_id=ticket.user_id)
        .filter(
            CustomerServiceAction.id
            > _integer(resolution.get("reopen_after_action_id"))
        )
        .all()
    )
    if any(
        a.action_type == "employee.dispatch"
        and a.status
        in {"pending", "running", "dispatching", "partial", "manual_review"}
        for a in actions
    ):
        return True
    events = db.query(IncidentEvent).filter(
        IncidentEvent.event_type == "ops.intake.customer_ticket",
        or_(
            IncidentEvent.payload_json.contains(f'"ticket_id":{ticket.id}'),
            IncidentEvent.payload_json.contains(f'"ticket_id": {ticket.id}'),
        ),
    )
    for event in events:
        payload = json_loads(str(event.payload_json or ""), {})
        if not isinstance(payload, dict) or payload.get("ticket_id") != ticket.id:
            continue
        original = payload.get("resolution") or {}
        if (
            payload.get("user_id") != ticket.user_id
            or not isinstance(original, dict)
            or original.get("reopened_at") != resolution.get("reopened_at")
        ):
            continue
        claim = payload.get("_team_claim") or {}
        if not isinstance(claim, dict):
            return True
        intents = claim.get("follow_up_intents") or {}
        if (
            claim.get("continuation_pending")
            or not isinstance(intents, dict)
            or any(
                not isinstance(intent, dict)
                or intent.get("state") not in {"completed", "receipt_recorded"}
                for intent in intents.values()
            )
        ):
            return True
        rows = claim.get("team") or []
        if not isinstance(rows, list):
            return True
        receipts = claim.get("escalations") or {}
        if isinstance(receipts, dict) and any(
            isinstance(receipt, dict)
            and receipt.get("state")
            in {"requested", "dispatching", "accepted", "unknown"}
            for receipt in receipts.values()
        ):
            return True
        if claim and (
            not rows
            or any(
                (
                    row.get("status")
                    not in {
                        "completed",
                        "success",
                        "succeeded",
                        "failed",
                        "skipped_fix_unfinished",
                        "verification_invalidated",
                    }
                    if isinstance(row, dict)
                    else True
                )
                for row in rows
            )
        ):
            return True
    return False


class SharedRepairBody(BaseModel, extra="forbid"):
    source_ticket_id: int = Field(gt=0)
    source_action_id: int = Field(gt=0)
    match_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_same_root_cause: Literal[True]
    note: str = Field(min_length=8, max_length=2000)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/issues/{ticket_id}/shared-repair-candidates")
def shared_repair_candidates(
    ticket_id: int, db: Session = Depends(get_db), _user: User = Depends(require_admin)
) -> dict[str, Any]:
    target = db.get(CustomerServiceTicket, ticket_id)
    if target is None:
        raise HTTPException(404, "原工单不存在")
    signature = shared_repair_signature(target)
    if not signature or target.status != "processing" or target.closed_at:
        return {
            "items": [],
            "match_sha256": signature,
            "reason": "no_exact_public_match",
        }
    actions = (
        db.query(CustomerServiceAction)
        .filter_by(action_type="issue.repair.result", status="completed")
        .order_by(CustomerServiceAction.id.desc())
        .limit(200)
        .all()
    )
    items = []
    for action in actions:
        if action.ticket_id == target.id:
            continue
        source = db.get(CustomerServiceTicket, action.ticket_id)
        cr = _source_repair(db, source, action, signature)
        if source is not None and cr is not None:
            items.append(
                {
                    "source_ticket_id": source.id,
                    "source_action_id": action.id,
                    "ticket_no": source.ticket_no,
                    "change_request_id": cr.id,
                    "repair_head_sha": cr.staged_commit_sha,
                }
            )
    return {"items": items, "match_sha256": signature, "requires_confirmation": True}


@router.post("/issues/{ticket_id}/shared-repair")
def link_shared_repair(
    ticket_id: int,
    body: SharedRepairBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    target = db.get(CustomerServiceTicket, ticket_id, with_for_update=True)
    if target is None:
        raise HTTPException(404, "原工单不存在")
    key = f"shared-repair:{ticket_id}:{body.request_id}"
    request = body.model_dump()
    prior = db.query(CustomerServiceAction).filter_by(idempotency_key=key).first()
    if prior is not None:
        if json_loads(str(prior.request_json or ""), {}).get("confirmation") != request:
            raise HTTPException(409, "同一关联请求标识不能用于不同内容")
        return {
            "success": True,
            "replayed": True,
            "link": active_shared_repair(db, target),
        }
    signature = shared_repair_signature(target)
    if (
        not signature
        or signature != body.match_sha256
        or target.id == body.source_ticket_id
        or target.status != "processing"
        or target.closed_at
    ):
        raise HTTPException(409, "当前原工单与待复用公共修复不匹配")
    source = db.get(CustomerServiceTicket, body.source_ticket_id)
    original = db.get(CustomerServiceAction, body.source_action_id)
    cr = _source_repair(db, source, original, signature)
    if source is None or original is None or cr is None or len(body.note.strip()) < 8:
        raise HTTPException(409, "原修复、当前源版本或同根因确认不可核验")
    if _in_flight(db, target):
        raise HTTPException(409, "原工单仍有执行或待对账任务，不能并行关联另一修复")
    before = target.evidence_json
    evidence = _evidence(target)
    resolution = issue_resolution(target, evidence)
    now = datetime.now(UTC)
    link = {
        "source_ticket_id": source.id,
        "source_action_id": original.id,
        "change_request_id": cr.id,
        "worker_id": cr.source_employee_id,
        "match_sha256": signature,
        "confirmation": request,
    }
    action = CustomerServiceAction(
        ticket_id=target.id,
        user_id=target.user_id,
        action_type=_ACTION,
        target_type="employee_change_request",
        target_id=str(cr.id),
        status="completed",
        idempotency_key=key,
        request_json=json_dumps(link),
        result_json=json_dumps(
            {"source_repair_verified": True, "customer_accepted": False}
        ),
    )
    db.add(action)
    db.flush()
    resolution.pop("release_target", None)
    resolution.update(
        state="awaiting_delivery",
        repair_verified=True,
        repair_verified_by="shared_core_repair",
        repair_verified_at=now.isoformat(),
        shared_repair_action_id=action.id,
        updated_at=now.isoformat(),
    )
    evidence["resolution"] = resolution
    changed = (
        db.query(CustomerServiceTicket)
        .filter(
            CustomerServiceTicket.id == target.id,
            CustomerServiceTicket.evidence_json == before,
            CustomerServiceTicket.status == "processing",
            CustomerServiceTicket.closed_at.is_(None),
        )
        .update(
            {"evidence_json": json_dumps(evidence), "updated_at": now},
            synchronize_session=False,
        )
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "原工单已变化，请刷新后重新核对")
    audit(
        db,
        event_type="shared_repair_linked",
        actor=user,
        actor_type="admin",
        ticket_id=int(target.id),
        session_id=int(target.session_id),
        detail={
            "source_action_id": original.id,
            "action_id": action.id,
            "match_sha256": signature,
            "note": body.note.strip(),
        },
    )
    db.commit()
    db.refresh(target)
    return {
        "success": True,
        "replayed": False,
        "link": active_shared_repair(db, target),
    }
