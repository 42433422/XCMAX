"""Start a GitHub-hosted Para worker; keep the existing employee and Para engines."""

from __future__ import annotations

import os
import re
import time
from urllib.parse import quote, urlparse

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
    row.status = status
    row.result_json = json_dumps({**json_loads(row.result_json, {}), **result})
    db.commit()


def _claim_worker_slot(db, row, *, owner_key=None):
    from modstore_server.customer_ticket_github import _execution, github
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
    if owner.startswith("retort:"):
        from modstore_server.retort_github_workspace import slot_finished

        if not slot_finished(owner.removeprefix("retort:")):
            return False
    elif owner:
        previous = db.get(CustomerServiceAction, int(owner))
        if not previous:
            return False
        receipt, _ = _execution(db, previous)
        if not receipt.get("run_id") or any(
            r.get("requires_reconciliation")
            or r.get("state") not in {"completed", "failed", "cancelled"}
            for r in receipt.get("receipts", [])
        ):
            return False
        repo = json_loads(previous.request_json, {})["repository"]
        if (
            github("GET", f"/repos/{repo}/actions/runs/{receipt['run_id']}").get("status")
            != "completed"
        ):
            return False
        previous.status = "runner_stopped"
    changed = (
        db.query(MacControlSyncLease)
        .filter_by(id="github-worker", owner=owner)
        .update({"owner": requested_owner}, synchronize_session=False)
    )
    db.commit()
    return bool(changed)


def ensure_runner(db, payload):
    try:
        return _ensure_runner(db, payload)
    except (HTTPException, httpx.HTTPError):
        row = db.get(CustomerServiceAction, payload["github_workspace"].get("action_id"))
        if row:
            row.error = "GitHub 或 Para 状态暂未取得，保留原派工等待核对"
            db.commit()
        return False


def _ensure_runner(db, payload):
    from modstore_server.customer_ticket_github import ISSUE_ACTION, RUN_ACTION, github

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
    repo, request_id = workspace["repository"], workspace["request_id"]
    if row.status in {"runner_stopped", "blocked"}:
        return None
    if row.status == "queued":
        capability = publisher_capability()
        if not capability["available"]:
            _save(db, row, "blocked", reason=capability["reason"])
            return None
        if not _claim_worker_slot(db, row):
            return False
        claimed = (
            db.query(CustomerServiceAction)
            .filter_by(id=row.id, status="queued")
            .update({"status": "dispatching"}, synchronize_session=False)
        )
        db.commit()  # Persist uncertainty before an external workflow dispatch.
        if claimed:
            try:
                github(
                    "POST",
                    f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
                    {"ref": "main", "inputs": {"request_id": request_id}},
                )
                _save(db, row, "requested")
            except HTTPException:
                _save(db, row, "unknown")
        return False
    receipt = json_loads(row.result_json, {})
    run_id = receipt.get("run_id")
    if not run_id:
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
            return False  # Missing/ambiguous acknowledgement never resubmits.
        run_id = matches[0]["id"]
        _save(
            db,
            row,
            "requested",
            run_id=run_id,
            url=f"https://github.com/{repo}/actions/runs/{run_id}",
        )
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
        _save(db, row, "running")
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
    from modstore_server.models import IncidentEvent
    from modstore_server.para_github_publication import publication_candidate

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
