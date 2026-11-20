"""Start a GitHub-hosted Para worker; keep the existing employee and Para engines."""

from __future__ import annotations

import os
import re
import time
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.mac_control_transport import age_seconds
from modstore_server.models_cs import CustomerServiceAction

WORKFLOW = "fhd-para-github-worker.yml"


def publisher_capability():
    # The installed workflow uses fresh hosted VMs and an immutable Git bundle handoff.
    # No flag enables the old shared-identity worker, which remains unconditionally blocked.
    return {
        "available": True,
        "status": "isolated_jobs",
        "protocol": "para-github-candidate/v1",
    }


def authorized_dispatch(runtime, employee_id):
    from modstore_server.models import IncidentEvent, get_session_factory

    if runtime.get("_trusted_incident_team_execution") is not True:
        return False
    with get_session_factory()() as db:
        event = db.get(IncidentEvent, runtime.get("event_id"))
        payload = json_loads(event.payload_json, {}) if event else {}
        if (payload.get("github_workspace") or {}).get("retort_run_id"):
            from modstore_server.retort_github_workspace import authorized_incident
        else:
            from modstore_server.customer_ticket_github import authorized_incident
        return bool(
            event
            and authorized_incident(db, payload, event.id)
            and payload.get("github_workspace") == runtime.get("github_workspace")
            and any(
                r.get("employee_id") == employee_id
                and r.get("role") == runtime.get("role")
                and r.get("attempt_id") == runtime.get("attempt_id")
                and r.get("status") == "dispatching"
                for r in payload.get("_team_claim", {}).get("team", [])
            )
        )


def api_base():
    base = os.environ.get("MODSTORE_PARA_GITHUB_API_BASE", "").rstrip("/")
    url = urlparse(base)
    if (
        not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path
        or (
            url.scheme != "https"
            and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"})
        )
    ):
        raise ValueError("GitHub Para 协调服务地址无效")
    return base


def auth_headers() -> dict[str, str]:
    from modstore_server.cred_vault import get_credential

    token = get_credential(
        "MODSTORE_PARA_GITHUB_AUTH_TOKEN",
        task_id="github-worker",
        purpose="para_github_dispatch",
    )
    if not token:
        raise ValueError("GitHub Para 专用服务身份尚未配置")
    return {"Authorization": "Bearer " + token}


def device_matches(device, workspace):
    caps = device.get("capabilities") or {}
    return bool(
        device.get("id") == os.environ.get("MODSTORE_PARA_GITHUB_DEVICE_ID")
        and device.get("status") == "online"
        and age_seconds(device.get("lastSeen", ""), time.time()) <= 90
        and caps.get("github_actions") is True
        and caps.get("github_request_id") == workspace.get("request_id")
        and str(caps.get("github_run_id")) == str(workspace.get("run_id"))
        and str(caps.get("github_run_attempt")) == "1"
        and (not workspace.get("stage") or caps.get("github_stage") == workspace["stage"])
        and not caps.get("server_bridge")
        and any(
            t.get("toolName") == "codex" and t.get("status") in {"idle", "running"}
            for t in device.get("tools", [])
        )
    )


def resume_worker_ready(workspace):
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        response = client.get(api_base() + "/api/devices", headers=auth_headers())
        response.raise_for_status()
        return any(
            device_matches(device, {**workspace, "stage": "resume"})
            for device in response.json().get("devices", [])
        )


def _save(db, row, status, **result):
    db.refresh(row, with_for_update=True)
    if row.status in {"blocked", "runner_stopped"} and status != row.status:
        db.rollback()
        return False
    row.status = status
    row.result_json = json_dumps({**json_loads(row.result_json, {}), **result})
    db.commit()
    return True


def _find_runner_id(github, repo, request_id):
    matches = []
    for page in range(1, 4):
        runs = github(
            "GET",
            f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs"
            f"?event=workflow_dispatch&per_page=100&page={page}",
        ).get("workflow_runs", [])
        matches.extend(
            r
            for r in runs
            if r.get("display_title") == f"para-workspace-{request_id}"
            and r.get("head_branch") == "main"
        )
        if len(runs) < 100:
            break
    if len(matches) != 1:
        return None
    run_id = matches[0].get("id")
    return run_id if type(run_id) is int and run_id > 0 else None


def _was_ticket_stopped(db, action):
    from modstore_server.customer_ticket_github import RUN_ACTION
    from modstore_server.models_cs import CustomerServiceTicket

    if action.action_type != RUN_ACTION or action.target_type != "github":
        return False
    ticket = db.get(CustomerServiceTicket, action.ticket_id)
    if ticket is None or ticket.user_id != action.user_id:
        return False
    evidence = json_loads(ticket.evidence_json, {})
    return isinstance(evidence, dict) and bool(
        evidence.get("dispatch_revocation") or evidence.get("admin_disposition")
    )


def _recover_stopped_runner_id(db, action, github, repo):
    request_id = json_loads(action.request_json, {}).get("request_id")
    if not request_id or action.status not in {"dispatching", "requested", "unknown", "running"}:
        return None
    run_id = _find_runner_id(github, repo, request_id)
    if run_id is None:
        return None
    db.refresh(action, with_for_update=True)
    receipt = json_loads(action.result_json, {})
    if receipt.get("run_id") not in (None, run_id):
        return None
    # Keep the old action and its original outbox receipt. This is observation of
    # an existing workflow, not authorization to start work on the stopped ticket.
    action.result_json = json_dumps(
        {**receipt, "run_id": run_id, "url": f"https://github.com/{repo}/actions/runs/{run_id}"}
    )
    db.commit()
    return run_id


def _stopped_runner_has_unsettled_attempts(db, action):
    from modstore_server.customer_ticket_github import _inbox
    from modstore_server.models import IncidentClaim, IncidentEvent

    inbox = _inbox(db, action)
    if not inbox:
        return False  # Para execution first requires the original incident.
    event = db.get(IncidentEvent, inbox.incident_event_id)
    if event is None:
        return True
    payload = json_loads(event.payload_json, {})
    workspace = payload.get("github_workspace") or {}
    if (
        payload.get("ticket_id") != action.ticket_id
        or payload.get("user_id") != action.user_id
        or workspace.get("action_id") != action.id
    ):
        return True
    claim = payload.get("_team_claim") or {}
    if event.dispatched_count and not claim:
        return True
    incident_lease = db.get(IncidentClaim, event.id)
    if incident_lease is not None and incident_lease.dispatch_state in {"dispatching", "unknown"}:
        return True
    if any(
        intent.get("state") in {"dispatching", "unknown"}
        for intent in (claim.get("follow_up_intents") or {}).values()
    ):
        return True
    if any(
        receipt.get("requires_reconciliation")
        or receipt.get("state") not in {"requested", "completed", "failed", "cancelled"}
        for receipt in (claim.get("escalations") or {}).values()
    ):
        return True
    settled = {"completed", "failed", "cancelled", "rejected", "ticket_dispatch_blocked"}
    return any(
        row.get("attempt_id")
        and (row.get("outcome") == "unknown" or row.get("status") not in settled)
        for row in claim.get("team", [])
    )


def _runner_settlement(db, action, *, stopped):
    from modstore_server.customer_ticket_github import _execution, github

    request = json_loads(action.request_json, {})
    repo = request.get("repository") if isinstance(request, dict) else None
    if not repo:
        return None
    receipt, _ = _execution(db, action)
    run_id = receipt.get("run_id")
    if not run_id and stopped:
        run_id = _recover_stopped_runner_id(db, action, github, repo)
        receipt, _ = _execution(db, action)
    terminal_states = {"completed", "failed", "cancelled"}
    if stopped:
        terminal_states.update(("rejected", "ticket_dispatch_blocked"))
    if (
        not run_id
        or (stopped and _stopped_runner_has_unsettled_attempts(db, action))
        or any(
            r.get("requires_reconciliation") or r.get("state") not in terminal_states
            for r in receipt.get("receipts", [])
        )
    ):
        return None
    run = github("GET", f"/repos/{repo}/actions/runs/{run_id}")
    if run.get("status") != "completed" or (
        stopped and (run.get("id") != run_id or run.get("run_attempt") != 1)
    ):
        return None
    return run


def _claim_worker_slot(db, row, *, owner_key=None):
    from modstore_server.db.mac_control import MacControlSyncLease

    slot = db.get(MacControlSyncLease, "github-worker")
    if slot is None:
        try:
            db.add(MacControlSyncLease(id="github-worker", owner="", until=0))
            db.commit()
        except IntegrityError:
            db.rollback()
        slot = db.get(MacControlSyncLease, "github-worker")
    owner = slot.owner
    requested_owner = owner_key or str(row.id)
    if owner == requested_owner:
        return True
    if owner.startswith("repair:"):
        from modstore_server.customer_ticket_github import github
        from modstore_server.db.mac_control import MacControlTask
        from modstore_server.mac_control_store import TERMINAL

        repair = db.get(MacControlTask, owner.removeprefix("repair:"))
        if not repair or repair.state not in TERMINAL:
            return False
        snapshot = json_loads(repair.snapshot_json, {})
        if snapshot.get("runner_intent"):
            repo = json_loads(repair.request_json, {})["repository"]
            run_id = snapshot.get("run_id")
            if (
                not run_id
                or github("GET", f"/repos/{repo}/actions/runs/{run_id}").get("status")
                != "completed"
            ):
                return False
    elif owner.startswith("retort:"):
        from modstore_server.retort_github_workspace import slot_finished

        if not slot_finished(owner.removeprefix("retort:")):
            return False
    elif owner:
        previous = db.get(CustomerServiceAction, int(owner))
        if not previous:
            return False
        if _runner_settlement(db, previous, stopped=_was_ticket_stopped(db, previous)) is None:
            return False
        previous.status = "runner_stopped"
    changed = (
        db.query(MacControlSyncLease)
        .filter_by(id="github-worker", owner=owner)
        .update({"owner": requested_owner}, synchronize_session=False)
    )
    db.commit()
    return bool(changed)


def stop_queued_ticket_runner(db, ticket, *, reason):
    from modstore_server.customer_ticket_github import RUN_ACTION

    blocked, unresolved = [], []
    rows = (
        db.query(CustomerServiceAction)
        .filter_by(
            ticket_id=ticket.id, user_id=ticket.user_id, action_type=RUN_ACTION, status="queued"
        )
        .with_for_update()
        .all()
    )
    for row in rows:
        receipt = json_loads(row.result_json, {})
        if receipt.get("run_id"):
            unresolved.append(row.id)
            continue
        row.status = "blocked"
        row.result_json = json_dumps({**receipt, "reason": reason})
        _release_worker_slot(db, row.id)
        blocked.append(row.id)
    return blocked, unresolved


def _release_worker_slot(db, action_id):
    from modstore_server.db.mac_control import MacControlSyncLease

    db.query(MacControlSyncLease).filter_by(id="github-worker", owner=str(action_id)).update(
        {"owner": ""}, synchronize_session=False
    )


def ensure_runner(db, payload):
    try:
        return _ensure_runner(db, payload)
    except (HTTPException, httpx.HTTPError):
        row = db.get(CustomerServiceAction, payload["github_workspace"].get("action_id"))
        if row:
            row.error = "GitHub 或 Para 状态暂未取得，保留原派工等待核对"
            db.commit()
        return False


def _owned_workspace_action(db, payload):
    from modstore_server.customer_ticket_github import RUN_ACTION

    workspace = payload["github_workspace"]
    row = db.get(CustomerServiceAction, workspace.get("action_id"))
    if (
        not row
        or row.action_type != RUN_ACTION
        or row.ticket_id != payload.get("ticket_id")
        or row.user_id != payload.get("user_id")
        or json_loads(row.request_json, {})
        != {k: workspace.get(k) for k in ("issue_number", "request_id", "repository")}
    ):
        raise ValueError("GitHub 派工记录不匹配")
    return row


def reconcile_stopped_ticket_runner(db, payload):
    """Read existing work only; leave queued or unconfirmed work out of dispatch."""
    action = _owned_workspace_action(db, payload)
    if not _was_ticket_stopped(db, action):
        return True
    if action.status in {"queued", "blocked"} and not json_loads(action.result_json, {}).get(
        "run_id"
    ):
        return True
    try:
        run = _runner_settlement(db, action, stopped=True)
    except (HTTPException, httpx.HTTPError):
        return False
    if run is None:
        return False
    db.refresh(action, with_for_update=True)
    _release_worker_slot(db, action.id)
    _save(db, action, "runner_stopped", conclusion=run.get("conclusion") or "unknown")
    return True


def _record_runner_submission(db, action, status):
    db.query(CustomerServiceAction).filter_by(id=action.id, status="dispatching").update(
        {"status": status}, synchronize_session=False
    )
    db.commit()


def _ensure_runner(db, payload):
    from modstore_server.customer_ticket_github import ISSUE_ACTION, github

    workspace = payload["github_workspace"]
    row = _owned_workspace_action(db, payload)
    repo, request_id = workspace["repository"], workspace["request_id"]
    if row.status in {"runner_stopped", "blocked"}:
        return None
    if row.status == "queued":
        capability = publisher_capability()
        if not capability["available"]:
            _save(db, row, "blocked", reason=capability["reason"])
            return None
        from modstore_server.para_model_admission import platform_model_admission

        allocation = platform_model_admission()
        if allocation:
            result = {
                "result_json": json_dumps(
                    {
                        **json_loads(row.result_json, {}),
                        "model_allocation": allocation,
                    }
                )
            }
        else:
            saved = json_loads(row.result_json, {})
            saved.pop("model_allocation", None)
            result = {"result_json": json_dumps(saved)}
        pending = db.query(CustomerServiceAction).filter_by(id=row.id, status="queued")
        if allocation and allocation["status"] != "admitted":
            pending.update(result, synchronize_session=False)
            db.commit()
            return False
        if not _claim_worker_slot(db, row):
            return False
        from modstore_server.customer_service_tools import begin_immediate_write
        from modstore_server.customer_ticket_intake_review import intake_dispatch_block_reason
        from modstore_server.models_cs import CustomerServiceTicket

        # Slot acquisition commits separately. Recheck the original ticket under its
        # write fence before making a new durable downstream dispatch claim.
        ticket_id = row.ticket_id
        db.rollback()
        begin_immediate_write(db)
        ticket = db.get(CustomerServiceTicket, ticket_id, with_for_update=True)
        db.refresh(row, with_for_update=True)
        if row.status == "blocked":
            _release_worker_slot(db, row.id)
            db.commit()
            return None
        if row.status != "queued":
            return False
        blocked = (
            intake_dispatch_block_reason(ticket)
            if ticket and ticket.user_id == row.user_id
            else "ticket_owner_mismatch"
        )
        if blocked:
            _release_worker_slot(db, row.id)
            _save(db, row, "blocked", reason=blocked)
            return None
        claimed = (
            db.query(CustomerServiceAction)
            .filter_by(id=row.id, status="queued")
            .update({**result, "status": "dispatching"}, synchronize_session=False)
        )
        db.commit()  # Persist uncertainty before an external workflow dispatch.
        if claimed:
            try:
                github(
                    "POST",
                    f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
                    {"ref": "main", "inputs": {"request_id": request_id}},
                )
                _record_runner_submission(db, row, "requested")
            except HTTPException:
                _record_runner_submission(db, row, "unknown")
        return False
    receipt = json_loads(row.result_json, {})
    run_id = receipt.get("run_id")
    if not run_id:
        run_id = _find_runner_id(github, repo, request_id)
        if run_id is None:
            return False  # Missing/ambiguous acknowledgement never resubmits.
        if not _save(
            db,
            row,
            "requested",
            run_id=run_id,
            url=f"https://github.com/{repo}/actions/runs/{run_id}",
        ):
            return None
    run = github("GET", f"/repos/{repo}/actions/runs/{run_id}")
    if run.get("run_attempt") != 1 or run.get("status") == "completed":
        _save(db, row, "runner_stopped", conclusion=run.get("conclusion") or "unknown")
        return None
    if run.get("status") != "in_progress":
        return False
    workspace["run_id"] = run_id
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        response = client.get(api_base() + "/api/devices", headers=auth_headers())
        response.raise_for_status()
        ready = any(device_matches(d, workspace) for d in response.json().get("devices", []))
    if ready:
        if not _save(db, row, "running"):
            return None
        issue = (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=row.ticket_id, action_type=ISSUE_ACTION)
            .one()
        )
        public = json_loads(issue.request_json, {})
        workspace["public_title"], workspace["public_summary"] = (
            public["title"],
            public["body"],
        )
    return ready


def run_status(db, request_id):
    from modstore_server.customer_ticket_github import RUN_ACTION, _execution, _inbox
    from modstore_server.db.mac_control import MacControlTask
    from modstore_server.models import IncidentEvent
    from modstore_server.para_github_publication import publication_candidate
    from modstore_server.para_github_repair import REPAIR_ACTOR
    from modstore_server.para_github_repair import run_status as repair_status

    repair = db.get(MacControlTask, UUID(str(request_id)).hex)
    if repair and repair.actor == REPAIR_ACTOR:
        return repair_status(repair)

    # The service sees only the opaque dispatch and execution state, never customer facts.
    rows = (
        db.query(CustomerServiceAction)
        .filter_by(action_type=RUN_ACTION)
        .filter(CustomerServiceAction.request_json.contains(str(request_id)))
        .all()
    )
    row = next(
        (r for r in rows if json_loads(r.request_json, {}).get("request_id") == str(request_id)),
        None,
    )
    if row is None:
        from modstore_server.models import RetortEvolutionRun
        from modstore_server.retort_github_workspace import worker_status

        if db.get(RetortEvolutionRun, str(request_id)) is not None:
            return worker_status(str(request_id))
        raise HTTPException(404, "派工记录不存在")
    execution, jobs = _execution(db, row)
    finished = execution.get("execution_status") == "completed"
    request = json_loads(row.request_json, {})
    inbox = _inbox(db, row)
    event = db.get(IncidentEvent, inbox.incident_event_id) if inbox else None
    return {
        "request_id": str(request_id),
        "repository": request["repository"],
        "issue_number": request["issue_number"],
        "run_id": execution.get("run_id"),
        "finished": finished or execution.get("status") == "blocked",
        "status": execution.get("status"),
        "reason": execution.get("reason"),
        "conclusion": execution.get("conclusion") or "unknown",
        "jobs": jobs,
        "receipts": execution.get("receipts", []),
        "publication_candidate": publication_candidate(db, event),
        "model_allocation": json_loads(row.result_json, {}).get("model_allocation"),
    }


def verified_code_identity(snapshot, *, workspace=None, attempt_id=""):
    from modstore_server.customer_ticket_github import configuration, github

    branches = {s.get("branch") for s in snapshot.get("subtasks", [])}
    staged = None
    if workspace:
        from modstore_server.para_github_publication import candidate_receipt

        staged = candidate_receipt(snapshot, workspace, attempt_id)
    for log in reversed(snapshot.get("logs_tail", [])):
        value = json_loads(log.get("content", ""), {})
        if (
            not isinstance(value, dict)
            or value.get("source") != "executor_git_readback"
            or (value.get("pushed") is not True and not staged)
            or value.get("branch") not in branches
            or not re.fullmatch(r"[0-9a-f]{40}", str(value.get("commit_sha") or ""))
            or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("archive_sha256") or ""))
        ):
            continue
        repo = configuration()["repository"]
        try:
            ref = github("GET", f"/repos/{repo}/git/ref/heads/{quote(value['branch'], safe='/')}")
        except HTTPException as exc:
            raise ValueError("GitHub 提交回执暂未取得") from exc
        if ref.get("object", {}).get("sha") != value["commit_sha"]:
            raise ValueError("修复分支与 Para 提交回执不一致")
        if staged:
            if any(value.get(k) != staged.get(k) for k in value):
                raise ValueError("隔离发布候选回执不一致")
            run = github("GET", f"/repos/{repo}/actions/runs/{workspace['run_id']}")
            if run.get("head_sha") != staged["base_sha"] or run.get("run_attempt") != 1:
                raise ValueError("隔离发布基线不一致")
            pulls = github("GET", f"/repos/{repo}/commits/{value['commit_sha']}/pulls")
            matches = [
                p
                for p in pulls
                if p.get("head", {}).get("sha") == value["commit_sha"]
                and p.get("head", {}).get("ref") == value["branch"]
                and p.get("base", {}).get("ref") == "main"
                and p.get("base", {}).get("repo", {}).get("full_name") == repo
                and re.search(rf"(?m)^Refs #{workspace['issue_number']}\s*$", p.get("body", ""))
            ]
            if len(matches) != 1:
                raise ValueError("隔离发布 PR 回执尚未确认")
            # The publisher VM has no Para device. Do not dispatch a verification
            # attempt into that gap and strand its already persisted intent.
            if not resume_worker_ready(workspace):
                raise ValueError("awaiting_isolated_verification_worker")
        return {key: value[key] for key in ("branch", "commit_sha", "archive_sha256")}
    raise ValueError("缺少 Para 代码提交与推送回执")
