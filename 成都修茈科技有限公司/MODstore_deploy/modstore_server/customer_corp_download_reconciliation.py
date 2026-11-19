# mypy: disable-error-code="arg-type, assignment"
"""Reconcile an approved website repair into the original customer's ticket."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func
from sqlalchemy.orm import Session

from modstore_server.corp_download_deployment import (
    CorpDownloadDeployment,
    read_corp_download_deployment,
)
from modstore_server.customer_corp_download_case import read_corp_download_case
from modstore_server.customer_issue_delivery_contract import issue_resolution, repair_verification
from modstore_server.customer_issue_shared_release import _merged_repair, _ReleaseProofBatch
from modstore_server.customer_service_api_helpers import append_original_assistant_message
from modstore_server.customer_service_tools import (
    audit,
    begin_immediate_write,
    json_dumps,
    json_loads,
)
from modstore_server.models import EmployeeChangeRequest, get_session_factory
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceMessage,
    CustomerServiceTicket,
)
from modstore_server.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)
_ACTIVE = ("open", "processing", "awaiting_customer")
_RECEIPT_ACTION = "issue.repair.corp_download"


@dataclass(frozen=True)
class _RepairCase:
    ticket_id: int
    owner_id: int
    session_id: int
    ticket_status: str
    ticket_lock_version: int
    source_message_id: int
    report_sha256: str
    latest_owner_message_id: int
    action_id: int
    event_id: int
    scope_started_at: datetime
    employee_id: str
    change_request_id: int
    staged_commit_sha: str
    status: str

    @property
    def id(self) -> int:
        """The existing merge verifier reads change-request identity."""
        return self.change_request_id


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _latest_signed_fault_at(evidence: dict[str, Any]) -> datetime | None:
    diagnoses = evidence.get("diagnoses", [])
    result = evidence.get("handling_result")
    if not isinstance(diagnoses, list) or (result is not None and not isinstance(result, dict)):
        return None
    records = diagnoses[-1:]
    if result and result.get("fault_remains") is True:
        records.append(result)
    times = []
    for record in records:
        if (
            not isinstance(record, dict)
            or type(record.get("operator_id")) is not int
            or record["operator_id"] <= 0
        ):
            return None
        try:
            recorded_at = datetime.fromisoformat(record["at"])
        except (KeyError, TypeError, ValueError):
            return None
        if recorded_at.utcoffset() is None:
            return None
        times.append(recorded_at)
    return max(times, default=None)


def _repair_case(db: Session, ticket: CustomerServiceTicket) -> _RepairCase | None:
    evidence = json_loads(ticket.evidence_json, {})
    if not isinstance(evidence, dict) or (
        ticket.closed_at
        or ticket.status not in _ACTIVE
        or evidence.get("dispatch_revocation")
        or evidence.get("admin_disposition")
        or evidence.get("assistant_disposition")
    ):
        return None
    resolution = issue_resolution(ticket, evidence)
    action_id = evidence.get("corp_download_repair_action_id")
    if (
        resolution.get("route") != "shared_core"
        or resolution.get("repair_verified") is not True
        or type(action_id) is not int
        or action_id <= int(resolution.get("reopen_after_action_id") or 0)
    ):
        return None
    target = resolution.get("release_target") or {}
    if isinstance(target, dict) and (
        target.get("surface") == "corp_download" and target.get("repair_action_id") == action_id
    ):
        return None
    case = read_corp_download_case(db, ticket, evidence)
    if not case:
        return None
    latest_owner_message_id = (
        db.query(func.max(CustomerServiceMessage.id))
        .filter(
            CustomerServiceMessage.ticket_id == ticket.id,
            CustomerServiceMessage.session_id == ticket.session_id,
            CustomerServiceMessage.user_id == ticket.user_id,
            CustomerServiceMessage.role == "user",
        )
        .scalar()
    )
    action = (
        db.query(CustomerServiceAction)
        .filter_by(id=action_id, ticket_id=ticket.id, user_id=ticket.user_id, status="completed")
        .filter(CustomerServiceAction.action_type == "issue.repair.result")
        .first()
    )
    if action is None or action.target_type != "employee_change_request":
        return None
    request = json_loads(action.request_json, {})
    result = json_loads(action.result_json, {})
    if not isinstance(request, dict) or not isinstance(result, dict):
        return None
    event_id = request.get("incident_event_id")
    if (
        type(event_id) is not int
        or event_id <= 0
        or event_id != resolution.get("incident_event_id")
        or result.get("team_verified") is not True
        or not str(action.target_id).isdigit()
    ):
        return None
    change = db.get(EmployeeChangeRequest, int(action.target_id))
    if (
        change is None
        or change.status != "applied"
        or not change.source_employee_id
        or change.source_employee_id != request.get("worker_id")
        or not change.staged_commit_sha
    ):
        return None
    reopened_at = resolution.get("reopened_at")
    try:
        scope_start = (
            _aware(datetime.fromisoformat(reopened_at))
            if reopened_at
            else _aware(ticket.created_at)
        )
    except (TypeError, ValueError, AttributeError):
        return None
    return _RepairCase(
        ticket_id=int(ticket.id),
        owner_id=int(ticket.user_id),
        session_id=int(ticket.session_id),
        ticket_status=str(ticket.status),
        ticket_lock_version=int(ticket.lock_version),
        source_message_id=case["source_message_id"],
        report_sha256=case["report_sha256"],
        latest_owner_message_id=int(latest_owner_message_id or 0),
        action_id=action_id,
        event_id=event_id,
        scope_started_at=scope_start,
        employee_id=str(change.source_employee_id),
        change_request_id=int(change.id),
        staged_commit_sha=str(change.staged_commit_sha),
        status=str(change.status),
    )


def _write_verified_repair(
    db: Session, case: _RepairCase, deployment: CorpDownloadDeployment, repair: dict[str, Any]
) -> bool:
    begin_immediate_write(db)
    ticket = (
        db.query(CustomerServiceTicket)
        .filter_by(id=case.ticket_id, user_id=case.owner_id, session_id=case.session_id)
        .with_for_update()
        .first()
    )
    if ticket is None or _repair_case(db, ticket) != case:
        return False
    if deployment.verified_at < case.scope_started_at:
        return False
    evidence = json_loads(ticket.evidence_json, {})
    if evidence.get("fault_remains") is True:
        fault_at = _latest_signed_fault_at(evidence)
        if fault_at is None or deployment.verified_at <= fault_at:
            return False
    key = f"corp-download:{case.ticket_id}:{case.action_id}:{deployment.workflow_run_id}:{deployment.run_attempt}"
    if db.query(CustomerServiceAction.id).filter_by(idempotency_key=key).first():
        return False
    now = datetime.now(UTC)
    receipt = {
        "surface": "corp_download",
        "workflow_run_id": deployment.workflow_run_id,
        "run_attempt": deployment.run_attempt,
        "deployed_sha": deployment.deployed_sha,
        "deployed_verified_at": deployment.verified_at.isoformat(),
        "repair_action_id": case.action_id,
        "incident_event_id": case.event_id,
        "employee_id": case.employee_id,
        "source_message_id": case.source_message_id,
        "report_sha256": case.report_sha256,
        "fix_sha": repair["fix_sha"],
        "pull_request": repair["pull_request"],
        "original_path": "/download/",
        "recorded_at": now.isoformat(),
    }
    resolution = issue_resolution(ticket, evidence)
    resolution.update(
        state="awaiting_customer_verification",
        release_target=receipt,
        **repair_verification("corp_download_deployment"),
    )
    evidence.pop("fault_remains", None)
    evidence["resolution"] = resolution
    ticket.evidence_json = json_dumps(evidence)
    ticket.status = "awaiting_customer"
    ticket.updated_at = now
    ticket.lock_version += 1
    note = "官网带末尾斜杠的下载链接已通过正式环境复测，在两个官网域名都能进入下载页。请你在原工单复验并确认。"
    append_original_assistant_message(
        db, ticket, note, now=now, origin="corp_download_verification", actor={}
    )
    db.add(
        CustomerServiceAction(
            ticket_id=case.ticket_id,
            user_id=case.owner_id,
            action_type=_RECEIPT_ACTION,
            target_type="github_workflow_run",
            target_id=str(deployment.workflow_run_id),
            status="completed",
            idempotency_key=key,
            request_json=json_dumps({"repair_action_id": case.action_id}),
            result_json=json_dumps(receipt),
        )
    )
    audit(
        db,
        event_type="corp_download_verified",
        ticket_id=case.ticket_id,
        session_id=case.session_id,
        actor_type="system",
        detail=receipt,
    )
    return True


def reconcile_corp_download_tickets() -> int:
    """Use a single deployment proof per batch, and hold no DB lock during reads."""
    factory = get_session_factory()
    with factory() as db:
        tickets = (
            db.query(CustomerServiceTicket)
            .filter(
                CustomerServiceTicket.status.in_(_ACTIVE),
                CustomerServiceTicket.intent == "product_issue",
                CustomerServiceTicket.evidence_json.like('%"corp_download_repair_action_id"%'),
            )
            .order_by(CustomerServiceTicket.id)
            .yield_per(25)
        )
        cases = [case for ticket in tickets if (case := _repair_case(db, ticket))]
    if not cases or (deployment := read_corp_download_deployment()) is None:
        return 0
    shared_proofs = _ReleaseProofBatch()
    count = 0
    for case in cases:
        try:
            repair = _merged_repair(case, deployment.deployed_sha, proofs=shared_proofs)
        except BOUNDARY_ERRORS:
            logger.info("Corp download repair provenance unavailable for ticket %s", case.ticket_id)
            continue
        if repair:
            with factory() as db:
                if _write_verified_repair(db, case, deployment, repair):
                    db.commit()
                    count += 1
    return count


def register_corp_download_job(
    scheduler: Any, *, track_job: Callable[[str, Callable[[], Any]], Any]
) -> None:
    job_id = "customer_corp_download_reconciliation"
    scheduler.add_job(
        lambda: track_job(job_id, reconcile_corp_download_tickets),
        IntervalTrigger(minutes=5),
        id=job_id,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
