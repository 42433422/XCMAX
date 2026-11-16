"""GitHub adapter for customer repairs; ticket ownership and acceptance stay here."""

from __future__ import annotations

import hashlib
import os
import re
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db, require_admin
from modstore_server.customer_service_tools import (
    audit,
    build_action,
    json_dumps,
    json_loads,
)
from modstore_server.models import User
from modstore_server.models_cs import CustomerServiceAction, CustomerServiceTicket

router = APIRouter()
ISSUE_ACTION = "github.issue"
RUN_ACTION = "github.run"


def public_incident(payload):
    workspace = payload["github_workspace"]
    return {
        **{
            key: payload.get(key)
            for key in ("scope", "issue_domain", "intent", "source")
        },
        "title": workspace["public_title"],
        "summary": workspace["public_summary"],
    }


def configuration():
    repo = os.environ.get("MODSTORE_GITHUB_REPOSITORY", "42433422/XCMAX").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise HTTPException(503, "GitHub 仓库配置无效")
    return {
        "repository": repo,
        "url": f"https://github.com/{repo}",
        "configured": bool(os.environ.get("MODSTORE_GITHUB_TOKEN", "").strip()),
        "executor": "现有 AI 员工 → Para · GitHub Actions",
        "para_configured": all(
            os.environ.get(key, "").strip()
            for key in (
                "MODSTORE_PARA_GITHUB_DEVICE_ID",
                "MODSTORE_PARA_GITHUB_API_BASE",
                "MODSTORE_PARA_GITHUB_AUTH_TOKEN",
            )
        ),
    }


def github(method, path, body=None):
    token = os.environ.get("MODSTORE_GITHUB_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "尚未配置服务端 GitHub 连接")
    try:
        response = httpx.request(
            method,
            "https://api.github.com" + path,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=25,
            follow_redirects=False,
        )
        response.raise_for_status()
        return response.json() if response.content else {}
    except (httpx.HTTPError, ValueError) as exc:
        # Never return upstream bodies, request headers, or customer data in errors.
        code = getattr(getattr(exc, "response", None), "status_code", None)
        raise HTTPException(
            502, f"GitHub 请求未确认（{code or '连接中断'}），请查询回执"
        ) from exc


def _ticket(db, ticket_id, *, mutable=False):
    ticket = db.get(CustomerServiceTicket, ticket_id)
    if not ticket:
        raise HTTPException(404, "工单不存在")
    if ticket.intent != "product_issue":
        raise HTTPException(409, "仅产品问题进入共享仓库修复")
    from modstore_server.customer_issue_delivery_contract import issue_resolution

    if (
        issue_resolution(ticket, json_loads(ticket.evidence_json, {}))["route"]
        != "shared_core"
    ):
        raise HTTPException(409, "客户专属 Mod 保留在原交付流程")
    if mutable and ticket.status not in {"open", "processing"}:
        raise HTTPException(409, "已结束工单不能发起修复")
    return ticket


def _actions(db, ticket_id, kind=ISSUE_ACTION):
    return db.query(CustomerServiceAction).filter_by(
        ticket_id=ticket_id, action_type=kind
    )


def _receipt(row):
    return (
        {"status": row.status, **json_loads(row.result_json, {}), "error": row.error}
        if row
        else None
    )


def _claim(db, ticket, kind, target, request, owner_row=None):
    try:
        if owner_row is not None:
            updated = (
                db.query(CustomerServiceAction)
                .filter_by(id=owner_row.id, lock_version=owner_row.lock_version)
                .update(
                    {"lock_version": owner_row.lock_version + 1},
                    synchronize_session=False,
                )
            )
            if not updated:
                db.rollback()
                raise HTTPException(409, "另一请求正在派工，请刷新回执")
        row = build_action(
            db,
            ticket_id=ticket.id,
            user_id=ticket.user_id,
            action_type=kind,
            target_type="github",
            target_id=target,
            request=request,
        )
        if owner_row is None:
            db.commit()
    except IntegrityError:
        db.rollback()
        row = _actions(db, ticket.id, kind).filter_by(target_id=target).one()
    if json_loads(row.request_json, {}) != request:
        raise HTTPException(409, "已有提交内容，请先查询原回执")
    claimed = (
        db.query(CustomerServiceAction)
        .filter_by(id=row.id, status="pending")
        .update({"status": "dispatching"}, synchronize_session=False)
    )
    if owner_row is None:
        db.commit()
    db.refresh(row)
    return row, bool(claimed)


def _record(db, row, user, result, status="completed", error=""):
    row.status, row.result_json, row.error = status, json_dumps(result), error
    audit(
        db,
        event_type=row.action_type,
        detail={"status": status, **result},
        actor=user,
        actor_type="admin",
        ticket_id=row.ticket_id,
    )
    db.commit()
    return _receipt(row)


def _marker(ticket):
    digest = hashlib.sha256(
        f"{configuration()['repository']}:{ticket.ticket_no}".encode()
    ).hexdigest()
    return f"<!-- xcmax-repair:{digest} -->"


def _link(db, ticket, row, user, issue):
    repo = json_loads(row.request_json, {})["repository"]
    number = int(issue["number"])
    result = {"number": number, "url": f"https://github.com/{repo}/issues/{number}"}
    from modstore_server.db.work_orders import WorkOrderEvent
    from modstore_server.work_order_api import _customer_view

    wo_id = json_loads(ticket.evidence_json, {}).get("work_order_id", "")
    owner = db.get(User, ticket.user_id)
    view = _customer_view(db, wo_id, owner) if wo_id and owner else None
    if view and not view.get("issue_number"):
        db.add(
            WorkOrderEvent(
                wo_id=wo_id,
                event="github_linked",
                source="ticket_github",
                ref=json_dumps({"issue_number": number, "issue_url": result["url"]}),
            )
        )
    return _record(db, row, user, result)


def _legacy_guard(db, ticket):
    from modstore_server.customer_ticket_execution import _current_claim, _receipts

    evidence = json_loads(ticket.evidence_json, {})
    _, claim = _current_claim(db, ticket, evidence.get("resolution") or {})
    if claim and (
        claim.get("continuation_pending")
        or not claim.get("ok")
        or any(
            r.get("requires_reconciliation") or not r.get("completed")
            for r in _receipts(claim)
        )
    ):
        raise HTTPException(409, "原执行任务尚未核销，请先查询原任务，避免重复修复")


class PublicIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=5, max_length=180)
    body: str = Field(min_length=30, max_length=10000)
    confirm_public: bool = False


class StartRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID


@router.get("/github/workspace")
def workspace(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = (
        db.query(CustomerServiceAction, CustomerServiceTicket)
        .join(
            CustomerServiceTicket,
            CustomerServiceTicket.id == CustomerServiceAction.ticket_id,
        )
        .filter(CustomerServiceAction.action_type == ISSUE_ACTION)
        .order_by(CustomerServiceAction.id.desc())
        .limit(100)
        .all()
    )
    config = configuration()
    return {
        **config,
        "items": [
            {
                "ticket_id": t.id,
                "title": t.title,
                "ticket_status": t.status,
                "issue": _receipt(a),
            }
            for a, t in rows
        ],
    }


@router.post("/tickets/{ticket_id}/github")
def publish(
    ticket_id: int,
    body: PublicIssue,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    ticket = _ticket(db, ticket_id, mutable=True)
    if not body.confirm_public:
        raise HTTPException(422, "请确认公开技术摘要，不包含客户身份、凭据或附件")
    config = configuration()
    if not config["configured"]:
        raise HTTPException(503, "尚未配置服务端 GitHub 连接")
    request = {
        "repository": config["repository"],
        "title": body.title,
        "body": body.body + "\n\n" + _marker(ticket),
    }
    # One durable issue receipt per original ticket, including uncertain POST outcomes.
    existing = _actions(db, ticket.id).first()
    if existing:
        return _receipt(existing)
    row, claimed = _claim(db, ticket, ISSUE_ACTION, "issue", request)
    if not claimed:
        return _receipt(row)
    try:
        issue = github(
            "POST",
            f"/repos/{config['repository']}/issues",
            {"title": request["title"], "body": request["body"]},
        )
        return _link(db, ticket, row, user, issue)
    except HTTPException:
        _record(
            db, row, user, {}, "unknown", "提交结果未确认，请查询回执；不会自动重复创建"
        )
        raise


@router.post("/tickets/{ticket_id}/github/reconcile")
def reconcile(
    ticket_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    ticket = _ticket(db, ticket_id)
    row = _actions(db, ticket.id).first()
    if not row:
        raise HTTPException(409, "尚无提交回执")
    request = json_loads(row.request_json, {})
    repo = request["repository"]
    if row.status != "completed":
        marker = request["body"].splitlines()[-1]
        found = []
        for page in range(1, 11):
            issues = github(
                "GET",
                f"/repos/{repo}/issues?state=all&sort=created&direction=desc&per_page=100&page={page}",
            )
            found.extend(
                i
                for i in issues
                if not i.get("pull_request") and marker in (i.get("body") or "")
            )
            if len(issues) < 100:
                break
        if len(found) != 1:
            raise HTTPException(409, "未找到唯一 Issue 回执，保留原记录等待核对")
        _link(db, ticket, row, user, found[0])
    return detail(ticket_id, db, user)


def _inbox(db, run):
    from modstore_server.models import IncidentInbox

    event_key = json_loads(run.result_json, {}).get("event_key", "") if run else ""
    key = hashlib.sha256(
        f"ops.intake.customer_ticket:customer-issue-intake:{event_key}".encode()
    ).hexdigest()
    return db.get(IncidentInbox, key) if event_key else None


def _execution(db, run):
    from modstore_server.customer_issue_delivery_contract import role_progress_state
    from modstore_server.customer_ticket_execution import _receipts
    from modstore_server.models import IncidentEvent

    result = _receipt(run)
    if not run:
        return None, []
    inbox = _inbox(db, run)
    event = db.get(IncidentEvent, inbox.incident_event_id) if inbox else None
    claim = json_loads(event.payload_json, {}).get("_team_claim", {}) if event else {}
    jobs = [
        {
            "name": r.get("role"),
            "employee_id": r.get("employee_id"),
            "status": role_progress_state(r),
            "conclusion": "success" if r.get("ok") else None,
        }
        for r in claim.get("team", [])
    ]
    if jobs:
        failed = any(j["status"] in {"failed", "cancelled", "rejected"} for j in jobs)
        result.update(
            execution_status="completed"
            if claim.get("ok") or failed
            else "in_progress",
            conclusion="success" if claim.get("ok") else "failure" if failed else None,
            event_id=event.id,
            receipts=_receipts(claim),
        )
    return result, jobs


@router.get("/tickets/{ticket_id}/github")
def detail(
    ticket_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    ticket = _ticket(db, ticket_id)
    row = _actions(db, ticket.id).first()
    run = (
        _actions(db, ticket.id, RUN_ACTION)
        .order_by(CustomerServiceAction.id.desc())
        .first()
    )
    execution, jobs = _execution(db, run)
    result = {
        **configuration(),
        "issue": _receipt(row),
        "run": execution,
        "jobs": jobs,
        "pulls": [],
    }
    if row and row.status == "completed":
        repo = json_loads(row.request_json, {})["repository"]
        number = json_loads(row.result_json, {})["number"]
        result.update(repository=repo, url=f"https://github.com/{repo}")
        try:
            if execution and execution.get("run_id"):
                worker = github(
                    "GET", f"/repos/{repo}/actions/runs/{execution['run_id']}"
                )
                if (
                    worker.get("status") == "completed"
                    and execution.get("execution_status") != "completed"
                ):
                    execution.update(
                        execution_status="unknown",
                        error="GitHub 执行器已结束，原任务回执待核对",
                    )
            issue = github("GET", f"/repos/{repo}/issues/{number}")
            result["issue"]["state"] = issue["state"]
            timeline = github(
                "GET", f"/repos/{repo}/issues/{number}/timeline?per_page=100"
            )
            if not isinstance(timeline, list) or any(
                not isinstance(item, dict) for item in timeline
            ):
                raise HTTPException(502, "GitHub 关联记录尚未取得，请稍后刷新")
            numbers = {
                i.get("source", {}).get("issue", {}).get("number")
                for i in timeline
                if i.get("event") == "cross-referenced"
                and i.get("source", {})
                .get("issue", {})
                .get("html_url", "")
                .startswith(f"https://github.com/{repo}/pull/")
            }
            for pr_number in sorted(n for n in numbers if isinstance(n, int)):
                pr = github("GET", f"/repos/{repo}/pulls/{pr_number}")
                result["pulls"].append(
                    {
                        "number": pr_number,
                        "url": f"https://github.com/{repo}/pull/{pr_number}",
                        "state": "merged" if pr.get("merged") else pr["state"],
                        "draft": pr.get("draft", False),
                    }
                )
        except HTTPException as exc:
            result["readback_error"] = exc.detail
    return result


@router.post("/tickets/{ticket_id}/github/start")
def start(
    ticket_id: int,
    body: StartRun,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from modstore_server.customer_issue_intake import enqueue_issue

    ticket = _ticket(db, ticket_id, mutable=True)
    issue = _actions(db, ticket.id).first()
    if not issue or issue.status != "completed":
        raise HTTPException(409, "请先确认 Issue 已创建")
    previous = _actions(db, ticket.id, RUN_ACTION).first()
    if previous:
        return _receipt(previous)
    _legacy_guard(db, ticket)
    if not configuration()["para_configured"]:
        raise HTTPException(503, "尚未接通 GitHub 临时执行器")
    repo = json_loads(issue.request_json, {})["repository"]
    number = json_loads(issue.result_json, {})["number"]
    if github("GET", f"/repos/{repo}/issues/{number}").get("state") != "open":
        raise HTTPException(409, "Issue 已关闭，请核对原修复与验收记录")
    request = {
        "issue_number": number,
        "request_id": str(body.request_id),
        "repository": repo,
    }
    row, claimed = _claim(db, ticket, RUN_ACTION, str(number), request, issue)
    if not claimed:
        return _receipt(row)
    workspace = {
        **request,
        "action_id": row.id,
        "issue_url": f"https://github.com/{repo}/issues/{number}",
    }
    event_key = enqueue_issue(
        db,
        ticket,
        revision=f"github-{body.request_id}",
        support_report={"github_workspace": workspace},
    )
    # The existing durable outbox drives the existing employee team, then Para.
    # No model call or second execution engine is created by the management API.
    return _record(
        db,
        row,
        user,
        {"event_key": event_key, "request_id": str(body.request_id)},
        "queued",
    )


def authorized_incident(db, payload, event_id):
    workspace = payload.get("github_workspace") or {}
    row = db.get(CustomerServiceAction, workspace.get("action_id", 0))
    inbox = _inbox(db, row)
    return bool(
        row
        and inbox
        and inbox.incident_event_id == event_id
        and row.action_type == RUN_ACTION
        and row.status == "running"
        and row.ticket_id == payload.get("ticket_id")
        and row.user_id == payload.get("user_id")
        and json_loads(row.request_json, {})
        == {k: workspace.get(k) for k in ("issue_number", "request_id", "repository")}
    )
