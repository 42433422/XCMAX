"""Connect an authorized PR incident to the existing hosted Para worker."""

from __future__ import annotations

import hashlib
import json
import uuid
from urllib.parse import quote

from fastapi import HTTPException

from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_store import TERMINAL, acquire, transition
from modstore_server.mac_control_transport import ParaClient, ParaUnavailable, execution_tool
from modstore_server.para_github_runner import WORKFLOW, _claim_worker_slot, device_matches

REPAIR_KIND = "original_pr_repair"
REPAIR_ACTOR = "service:para-github-repair"


def _request_id(task):
    return str(uuid.UUID(hex=task.id))


def _current_source(github, request):
    repo = request["repository"]
    issue = github("GET", f"/repos/{repo}/issues/{request['github_issue']}")
    label_names = {row.get("name") for row in issue.get("labels", [])}
    author = issue.get("user") or {}
    if (
        issue.get("state") != "open"
        or author.get("login") != "github-actions[bot]"
        or author.get("type") != "Bot"
        or not {"auto-incident", "ai-implement"} <= label_names
    ):
        return False
    pr = github("GET", f"/repos/{repo}/pulls/{request['pull_request']}")
    head, base = pr.get("head") or {}, pr.get("base") or {}
    run = github("GET", f"/repos/{repo}/actions/runs/{request['source_run_id']}")
    labels = {x.get("name") for x in pr.get("labels", [])}
    incident_header = str(issue.get("body") or "").split("\n###", 1)[0].splitlines()
    return (
        pr.get("state") == "open"
        and pr.get("draft") is False
        and not labels.intersection({"hold-merge", "needs-human"})
        and head.get("sha") == request["source_sha"] == run.get("head_sha")
        and head.get("ref") == run.get("head_branch")
        and (head.get("repo") or {}).get("full_name") == repo
        and (base.get("repo") or {}).get("full_name") == repo
        and base.get("ref") == "main"
        and run.get("status") == "completed"
        and run.get("conclusion") == "failure"
        and (run.get("head_repository") or {}).get("full_name") == repo
        and f"- Self-Heal-Run: `{request['source_run_id']}/{run.get('run_attempt')}`"
        in incident_header
    )


def _find_run(github, repo, title):
    matches = []
    for page in range(1, 4):
        rows = github(
            "GET",
            f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs"
            f"?event=workflow_dispatch&branch=main&per_page=100&page={page}",
        )["workflow_runs"]
        matches.extend(row for row in rows if row.get("display_title") == title)
        if len(rows) < 100:
            return matches[0]["id"] if len(matches) == 1 else None
    return None


def _worker_run(github, repo, run_id, request_id):
    run = github("GET", f"/repos/{repo}/actions/runs/{run_id}")
    if (
        run.get("path") != f".github/workflows/{WORKFLOW}"
        or run.get("id") != run_id
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("run_attempt") != 1
        or (run.get("repository") or {}).get("full_name") != repo
        or run.get("display_title") != f"para-workspace-{request_id}"
    ):
        raise HTTPException(409, "Para 云端运行身份不一致")
    return run


def _publish_readback(db, task, request, state, run, github):
    if task.state == "cancel_requested":
        transition(db, task, "cancelled", snapshot=state)
        return
    candidate = state.get("candidate")
    if not candidate or run.get("conclusion") != "success":
        transition(db, task, "failed", "github_worker_unfinished", snapshot=state)
        return
    repo = request["repository"]
    jobs = github("GET", f"/repos/{repo}/actions/runs/{run['id']}/jobs")["jobs"]
    branch = candidate["branch"]
    ref = github("GET", f"/repos/{repo}/git/ref/heads/{quote(branch, safe='/')}")
    if (
        len(
            [
                job
                for job in jobs
                if job.get("name") == "publish-candidate" and job.get("conclusion") == "success"
            ]
        )
        != 1
        or (ref.get("object") or {}).get("sha") != candidate["commit_sha"]
    ):
        transition(db, task, "reconciling", "publication_readback_unconfirmed", snapshot=state)
        return
    transition(
        db,
        task,
        "execution_completed",
        snapshot={
            **state,
            "id": task.para_task_id,
            "subtasks": [{"branch_name": branch}],
            "reports": [
                {
                    "report": {
                        "source": "github_isolated_publisher",
                        "pushed": True,
                        "branch": branch,
                        "commit_sha": candidate["commit_sha"],
                        "github_run_id": run["id"],
                    }
                },
            ],
        },
    )


def _observe_para(db, task, request, state, request_id, client):
    from modstore_server.customer_issue_delivery_contract import para_task_succeeded
    from modstore_server.para_delegate_handler import _task_result_snapshot
    from modstore_server.para_github_publication import candidate_receipt

    marker = _marker(request_id, task.attempt_id)
    if not task.para_task_id:
        matches = [row for row in client.tasks() if str(row.get("title", "")).startswith(marker)]
        if len(matches) != 1:
            return
        task.para_task_id = matches[0]["id"]
        db.commit()
    raw = client.task(task.para_task_id)
    if (
        not str(raw.get("title", "")).startswith(marker)
        or raw.get("repo_url") != f"https://github.com/{request['repository']}.git"
    ):
        raise HTTPException(409, "Para 原任务回执身份不一致")
    if not para_task_succeeded(raw, task.para_task_id, planned_devices=[task.device_id]):
        return
    workspace = {**request, "request_id": request_id, "run_id": state["run_id"]}
    candidate = candidate_receipt(_task_result_snapshot({"task": raw}), workspace, task.attempt_id)
    if candidate:
        transition(
            db,
            task,
            "running",
            "awaiting_isolated_publication",
            snapshot={
                **state,
                "candidate": candidate,
            },
        )


def _marker(request_id, attempt_id):
    key = hashlib.sha256(request_id.encode()).hexdigest()[:32]
    return f"[xcmax:{key}:{attempt_id}] "


def _dispatch_para(db, task, request, state, request_id, client, github):
    workspace = {"request_id": request_id, "run_id": state["run_id"], "stage": "execute"}
    devices = [
        device
        for device in client.devices()
        if device_matches(device, workspace)
        and device.get("capabilities", {}).get("supports_exact_commit") is True
    ]
    if len(devices) != 1:
        return
    if not _current_source(github, request):
        transition(db, task, "cancel_requested", "original_ci_failure_changed", snapshot=state)
        return
    task.device_id, task.attempt_id = devices[0]["id"], uuid.uuid4().hex
    transition(db, task, "dispatching", "para_dispatch_intent_recorded", snapshot=state)
    raw = client.submit(
        {
            "device_id": task.device_id,
            "tool_name": execution_tool(),
            "title": _marker(request_id, task.attempt_id) + f"Repair PR #{request['pull_request']}",
            "prompt": request["message"],
            "repo_url": f"https://github.com/{request['repository']}.git",
            "branch": request["source_sha"],
            "max_attempts": 1,
            "report_only": False,
            "auto_merge": False,
        }
    )
    if not raw.get("id"):
        raise ParaUnavailable("dispatch_response_missing_id")
    task.para_task_id = raw["id"]
    transition(db, task, "running", snapshot=state)


def _process(db, task, github):
    request, state = json.loads(task.request_json), json.loads(task.snapshot_json)
    repo, request_id = request["repository"], _request_id(task)
    if not state.get("runner_intent"):
        if task.state == "cancel_requested" or not _current_source(github, request):
            transition(db, task, "cancelled", "no_current_authorized_pr_failure")
            return
        from modstore_server.para_model_admission import platform_model_admission

        allocation = platform_model_admission()
        state["model_allocation"] = allocation
        if allocation and allocation.get("status") != "admitted":
            transition(db, task, "waiting_device", "platform_model_capacity", snapshot=state)
            return
        if not _claim_worker_slot(db, task, owner_key=f"repair:{task.id}"):
            return
        state["runner_intent"] = True
        transition(db, task, "dispatching", "github_dispatch_intent_recorded", snapshot=state)
        result = github(
            "POST",
            f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
            {"ref": "main", "inputs": {"request_id": request_id}, "return_run_details": True},
        )
        if type(result.get("workflow_run_id")) is int:
            state["run_id"] = result["workflow_run_id"]
            transition(db, task, "waiting_device", "github_worker_requested", snapshot=state)
        return
    if not state.get("run_id"):
        run_id = _find_run(github, repo, f"para-workspace-{request_id}")
        if not run_id:
            return
        state["run_id"] = run_id
        transition(db, task, task.state, "github_worker_observed", snapshot=state)
    run = _worker_run(github, repo, state["run_id"], request_id)
    if run.get("status") == "completed":
        _publish_readback(db, task, request, state, run, github)
        return
    if (
        run.get("status") != "in_progress"
        or task.state == "cancel_requested"
        or state.get("candidate")
    ):
        return
    client = ParaClient(github_worker=True)
    try:
        if task.attempt_id:
            _observe_para(db, task, request, state, request_id, client)
        else:
            _dispatch_para(db, task, request, state, request_id, client, github)
    finally:
        client.close()


def sync(factory):
    """Observe the oldest cloud request under the normal Mac control scheduler lease."""
    from modstore_server.customer_ticket_github import github

    with factory() as db:
        row = (
            db.query(MacControlTask)
            .filter(MacControlTask.actor == REPAIR_ACTOR, MacControlTask.state.notin_(TERMINAL))
            .order_by(MacControlTask.created_at)
            .first()
        )
        task = acquire(db, row.id) if row else None
        if task is None:
            return
        try:
            _process(db, task, github)
        except (ParaUnavailable, HTTPException, ValueError) as exc:
            # Neither an uncertain dispatch nor a failed observation authorizes a retry.
            task.reason = f"cloud_receipt_pending:{type(exc).__name__}"
        finally:
            task.lease_until = 0
            db.commit()


def run_status(task):
    request, state = json.loads(task.request_json), json.loads(task.snapshot_json)
    return {
        "kind": REPAIR_KIND,
        "request_id": _request_id(task),
        "repository": request["repository"],
        "issue_number": request["github_issue"],
        "pull_request": request["pull_request"],
        "source_run_id": request["source_run_id"],
        "source_sha": request["source_sha"],
        "run_id": state.get("run_id"),
        "status": task.state,
        "finished": task.state in TERMINAL or task.state == "cancel_requested",
        "conclusion": "success" if task.state == "execution_completed" else "unknown",
        "publication_candidate": state.get("candidate"),
        "model_allocation": state.get("model_allocation"),
    }
