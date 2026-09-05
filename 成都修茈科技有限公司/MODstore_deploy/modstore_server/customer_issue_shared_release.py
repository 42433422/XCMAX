"""Bind real repair actions to a released main host before customer confirmation."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException

from modstore_server.customer_delivery_receipts import (
    canonical_sha256,
    trusted_host_release,
)
from modstore_server.customer_issue_delivery_contract import (
    issue_resolution,
    team_succeeded,
)
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import EmployeeChangeRequest
from modstore_server.models_cs import CustomerServiceAction
from modstore_server.operational_errors import BOUNDARY_ERRORS
from modstore_server.release_convergence import _fetch_json

_API = "https://api.github.com/repos/42433422/XCMAX"


def _pulls_for_commit(head: str) -> list[dict[str, Any]]:
    token = os.environ.get("XCMAX_GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.get(f"{_API}/commits/{head}/pulls", headers=headers)
        response.raise_for_status()
        result = response.json()
    return result if isinstance(result, list) else []


def _change_request_reference(value: Any) -> int:
    if isinstance(value, dict):
        candidate = value.get("change_request_id")
        if isinstance(candidate, int) and candidate > 0:
            return candidate
        for key in ("result", "results", "outputs", "data"):
            found = _change_request_reference(value.get(key))
            if found:
                return found
    elif isinstance(value, list):
        for row in value:
            found = _change_request_reference(row)
            if found:
                return found
    return 0


def record_worker_repair(db: Any, ticket: Any, event_id: int, rows: list[dict[str, Any]]) -> None:
    """Called only by incident execution, never by a customer write endpoint."""
    if not team_succeeded(rows):
        return
    fix = next((row for row in rows if row.get("role") == "fix"), {})
    reference = _change_request_reference(fix.get("result"))
    if not reference:
        return
    cr = db.get(EmployeeChangeRequest, reference)
    if cr is None or cr.source_employee_id != fix.get("employee_id"):
        return
    key = f"issue-repair:{int(ticket.id)}:{int(event_id)}:{reference}"
    if db.query(CustomerServiceAction).filter_by(idempotency_key=key).first():
        return
    db.add(
        CustomerServiceAction(
            ticket_id=ticket.id,
            user_id=ticket.user_id,
            action_type="issue.repair.result",
            target_type="employee_change_request",
            target_id=str(reference),
            status="completed",
            idempotency_key=key,
            request_json=json_dumps(
                {"incident_event_id": int(event_id), "worker_id": fix["employee_id"]}
            ),
            result_json=json_dumps({"team_verified": True, "change_request_id": reference}),
        )
    )
    db.flush()


def _merged_repair(cr: Any, host_sha: str) -> dict[str, Any] | None:
    """GitHub, not employee output, proves merge identity and required CI."""
    head = str(cr.staged_commit_sha or "")
    if cr.status != "applied" or not re.fullmatch(r"[0-9a-f]{40}", head):
        return None
    pulls = _pulls_for_commit(head)
    if not isinstance(pulls, list):
        return None
    for hint in pulls:
        number = int(hint.get("number") or 0)
        pr = _fetch_json(f"{_API}/pulls/{number}")
        merge_sha = str(pr.get("merge_commit_sha") or "")
        if (
            not pr.get("merged")
            or (pr.get("base") or {}).get("ref") != "main"
            or ((pr.get("base") or {}).get("repo") or {}).get("full_name") != "42433422/XCMAX"
            or (pr.get("head") or {}).get("sha") != head
            or not re.fullmatch(r"[0-9a-f]{40}", merge_sha)
        ):
            continue
        protection = _fetch_json(f"{_API}/branches/main/protection/required_status_checks")
        required = set(protection.get("contexts") or []) | {
            row["context"] for row in protection.get("checks", []) if row.get("context")
        }
        checks = _fetch_json(f"{_API}/commits/{head}/check-runs?per_page=100")
        rows = checks.get("check_runs") or []
        if not required or int(checks.get("total_count") or 0) != len(rows):
            continue
        passed = {
            row.get("name")
            for row in rows
            if row.get("head_sha") == head
            and row.get("status") == "completed"
            and row.get("conclusion") == "success"
        }
        if not required.issubset(passed):
            continue
        compare = _fetch_json(f"{_API}/compare/{merge_sha}...{host_sha}")
        if (
            compare.get("status") not in {"ahead", "identical"}
            or (compare.get("merge_base_commit") or {}).get("sha") != merge_sha
        ):
            continue
        return {
            "fix_sha": merge_sha,
            "head_sha": head,
            "pull_request": pr.get("html_url"),
            "required_checks": sorted(required),
            "change_request_id": int(cr.id),
        }
    return None


def bind_shared_release(db: Any, ticket: Any, host_sha: str) -> dict[str, Any] | None:
    evidence = json_loads(ticket.evidence_json, {})
    resolution = issue_resolution(ticket, evidence)
    private_prerequisite = resolution.get("route") == "private_mod" and evidence.get(
        "shared_core_prerequisite"
    )
    if (resolution.get("route") != "shared_core" and not private_prerequisite) or resolution.get(
        "repair_verified"
    ) is not True:
        return None
    release = trusted_host_release(host_sha)
    if not release:
        return None
    existing = resolution.get("release_target") or {}
    if existing.get("host_sha") == host_sha and existing.get(
        "signed_metadata_sha256"
    ) == release.get("signed_metadata_sha256"):
        return existing
    actions = (
        db.query(CustomerServiceAction)
        .filter_by(
            ticket_id=ticket.id,
            user_id=ticket.user_id,
            action_type="issue.repair.result",
            status="completed",
        )
        .order_by(CustomerServiceAction.id.desc())
        .all()
    )
    for action in actions:
        cr = db.get(EmployeeChangeRequest, int(action.target_id))
        request = json_loads(action.request_json, {})
        if cr is None or cr.source_employee_id != request.get("worker_id"):
            continue
        try:
            repair = _merged_repair(cr, host_sha)
        except BOUNDARY_ERRORS:
            continue
        if not repair:
            continue
        target = {
            **repair,
            "host_sha": host_sha,
            "version": release["version"],
            "release_id": release["release_id"],
            "signed_metadata_sha256": release["signed_metadata_sha256"],
            "release_artifacts": release["artifacts"],
            "owner_user_id": int(ticket.user_id),
            "ticket_id": int(ticket.id),
            "action_id": int(action.id),
            "verification_mode": "customer_confirmation",
            "case_id": f"customer-confirmation:{int(ticket.id)}:{repair['fix_sha']}",
            "bound_at": datetime.now(UTC).isoformat(),
        }
        resolution.update(state="awaiting_customer_verification", release_target=target)
        evidence["resolution"] = resolution
        if private_prerequisite:
            from modstore_server.customer_issue_intake import enqueue_issue

            evidence["shared_core_prerequisite_release"] = target
            resolution["state"] = "queued_private_production"
        ticket.evidence_json = json_dumps(evidence)
        if private_prerequisite:
            enqueue_issue(db, ticket, revision=f"prerequisite-released:{target['fix_sha']}")
        db.flush()
        return target
    return None


def record_shared_runtime(
    db: Any, ticket: Any, body: dict[str, Any], owner_id: int
) -> dict[str, Any]:
    if int(ticket.user_id) != owner_id:
        raise HTTPException(403, "只有原工单账号可以提交运行回执")
    evidence = json_loads(ticket.evidence_json, {})
    if issue_resolution(ticket, evidence).get("route") != "shared_core":
        raise HTTPException(409, "本工单仍需私有产物运行验证，宿主前置修复不能完成交付")
    target = bind_shared_release(db, ticket, str(body.get("host_sha") or ""))
    if not target:
        raise HTTPException(409, "尚无包含本工单修复且通过主线发布核验的宿主")
    evidence = json_loads(ticket.evidence_json, {})
    records = evidence.get("host_receipts") or []
    digest = canonical_sha256(body)
    prior = next(
        (row for row in records if row.get("receipt_id") == body.get("receipt_id")),
        None,
    )
    if prior:
        if prior.get("request_sha256") != digest:
            raise HTTPException(409, "同一回执标识不可绑定不同内容")
        return {"replayed": True, "record": prior}
    if ticket.status in {"resolved", "closed"}:
        raise HTTPException(409, "该工单已完成，新的问题请通过原交付返工入口受理")
    if not body.get("receipt_id") or not body.get("client_instance_id"):
        raise HTTPException(409, "缺少稳定回执或客户端标识")
    if any(
        body.get(key) != target.get(key)
        for key in ("case_id", "version", "release_id", "signed_metadata_sha256")
    ):
        raise HTTPException(409, "客户端运行身份与本工单正式发布目标不匹配")
    confirmed = body.get("customer_confirmed") is True
    if confirmed and len(str(body.get("confirmation_note") or "").strip()) < 4:
        raise HTTPException(409, "请客户本人说明原问题的验证结果")
    row = {
        **body,
        "owner_user_id": owner_id,
        "ticket_id": int(ticket.id),
        "request_sha256": digest,
        "verified": confirmed,
        "received_at": datetime.now(UTC).isoformat(),
    }
    evidence["host_receipts"] = [*records, row]
    resolution = evidence["resolution"]
    if confirmed:
        ticket.status, ticket.decision_status, ticket.closed_at = (
            "resolved",
            "approved",
            datetime.now(UTC),
        )
        resolution.update(
            state="resolved",
            resolved_at=ticket.closed_at.isoformat(),
            verification_mode="customer_confirmation",
        )
    else:
        resolution["state"] = "awaiting_customer_verification"
    ticket.evidence_json = json_dumps(evidence)
    db.flush()
    return {"replayed": False, "record": row}
