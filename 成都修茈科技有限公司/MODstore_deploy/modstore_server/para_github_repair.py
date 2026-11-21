"""Connect an authorized PR incident to the existing hosted Para worker."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from urllib.parse import quote

from fastapi import HTTPException

from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_store import TERMINAL, acquire, transition
from modstore_server.mac_control_transport import ParaClient, ParaUnavailable
from modstore_server.para_github_runner import WORKFLOW, _claim_worker_slot, device_matches

REPAIR_KIND = "original_pr_repair"
REPAIR_ACTOR = "service:para-github-repair"


def budget_request_id(request_id):
    """A separate budget record never rewrites the original dispatch identity."""
    original = str(uuid.UUID(request_id))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"xcmax:original-pr-budget:{original}"))


def budget_original(session, request, *, active=False):
    from modstore_server.mac_control_store import digest
    from modstore_server.strategic_portfolio import PortfolioError

    row = session.get(MacControlTask, uuid.UUID(request["original_request_id"]).hex)
    if row is None or row.actor != REPAIR_ACTOR:
        raise PortfolioError("workspace original PR request changed")
    source, effects = json.loads(row.request_json), json.loads(row.snapshot_json)
    if (
        digest(source) != row.request_digest
        or request.get("approval_digest") != row.request_digest
        or source.get("source") != REPAIR_KIND
        or source.get("repository") != request["repository"]
        or (active and row.state in TERMINAL | {"cancel_requested"})
    ):
        raise PortfolioError("workspace original PR approval or frozen request changed")
    return row, source, effects


def budget_attempt(session, request, effects, identity, *, allow_published=False):
    from modstore_server.customer_ticket_github import github
    from modstore_server.strategic_portfolio import PortfolioError

    row, source, _ = budget_original(session, request, active=not allow_published)
    if (
        not row.para_task_id
        and row.state == "dispatching"
        and row.attempt_id == identity.get("attempt_id")
        and row.device_id == identity.get("device_id")
    ):
        raise PortfolioError("workspace original task receipt is pending")
    if (
        identity.get("phase") != "execute"
        or effects.get("run_id") != identity.get("run_id")
        or row.para_task_id != identity.get("task_id")
        or row.attempt_id != identity.get("attempt_id")
        or row.device_id != identity.get("device_id")
        or row.state
        not in ({"execution_completed"} if allow_published else {"running", "reconciling"})
        or (identity.get("grant_id") and identity.get("control_task_id") != row.id)
        or not _current_source(github, source)
    ):
        raise PortfolioError("workspace original PR task receipt is pending or changed")
    return {"role": "fix", "control_task_id": row.id}


def budget_terminal(request, evidence):
    """Candidate publication is pending until the same original PR's CI recovers."""
    from modstore_server.customer_ticket_github import github
    from modstore_server.strategic_portfolio import digest

    status, snapshot = evidence["status"], evidence["snapshot"]
    if status not in TERMINAL:
        return None
    completed = status == "execution_completed"
    receipt = {
        "schema": "strategic-workspace/v1",
        "request_id": request["original_request_id"],
        "control_task_id": evidence["control_task_id"],
        "original_sha256": digest(evidence),
        "delivery": {"status": "not_verified"},
    }
    if completed:
        candidate = snapshot.get("candidate") or {}
        source = evidence["request"]
        repo, target = source["repository"], candidate.get("commit_sha")
        pr = github("GET", f"/repos/{repo}/pulls/{source['pull_request']}")
        prior = github("GET", f"/repos/{repo}/actions/runs/{source['source_run_id']}")
        head, base = pr.get("head") or {}, pr.get("base") or {}
        workflow_id = prior.get("workflow_id")
        if (
            not target
            or head.get("sha") != target
            or head.get("ref") != prior.get("head_branch")
            or (head.get("repo") or {}).get("full_name") != repo
            or (base.get("repo") or {}).get("full_name") != repo
            or base.get("ref") != "main"
            or (pr.get("state") != "open" and pr.get("merged") is not True)
            or prior.get("head_sha") != source["source_sha"]
            or type(workflow_id) is not int
            or workflow_id < 1
        ):
            return None
        runs = _runs(github, repo, workflow_id)
        if not runs:
            return None
        matches = [
            run
            for run in runs
            if run.get("head_sha") == target
            and run.get("head_branch") == head["ref"]
            and run.get("workflow_id") == workflow_id
            and run.get("event") == "pull_request"
            and (run.get("repository") or {}).get("full_name") == repo
            and (
                not run.get("pull_requests")
                or any(
                    pull.get("number") == source["pull_request"] for pull in run["pull_requests"]
                )
            )
        ]
        if not matches or any(type(run.get("id")) is not int for run in matches):
            return None
        current = max(matches, key=lambda run: run["id"])
        if (
            current.get("status") != "completed"
            or type(current.get("run_attempt")) is not int
            or current["run_attempt"] < 1
        ):
            return None
        conclusion = current.get("conclusion")
        if conclusion not in {
            "success",
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
            "startup_failure",
            "neutral",
            "skipped",
            "stale",
        }:
            return None
        completed = conclusion == "success"
        receipt.update(
            candidate=candidate,
            pull_request=source["pull_request"],
            verification={
                "run_id": current["id"],
                "run_attempt": current.get("run_attempt"),
                "workflow_id": workflow_id,
                "head_sha": target,
                "status": "checks_passed" if completed else "checks_failed",
                "conclusion": conclusion,
            },
        )
    return {
        "ok": completed,
        "completed": True,
        "status": "completed" if completed else "failed",
        "executor": "github_opencode_workspace",
        "error": (
            ""
            if completed
            else f"original_pr_{receipt.get('verification', {}).get('conclusion', status)}"
        ),
        "remote_receipt": receipt,
    }


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


def _runs(github, repo, workflow):
    """Unfiltered pagination avoids GitHub's filtered-run result limit."""
    found, total, page = {}, None, 1
    while True:
        response = github(
            "GET",
            f"/repos/{repo}/actions/workflows/{workflow}/runs?per_page=100&page={page}",
        )
        rows, count = response.get("workflow_runs"), response.get("total_count")
        if (
            not isinstance(rows, list)
            or type(count) is not int
            or count < 0
            or (total is not None and total != count)
            or len(rows) > 100
        ):
            return None
        total = count
        for row in rows:
            key = row.get("id") if isinstance(row, dict) else None
            if type(key) is not int or key < 1 or key in found:
                return None
            found[key] = row
        if len(found) == total:
            return list(found.values())
        if len(rows) < 100 or len(found) > total:
            return None
        page += 1


def _find_run(github, repo, title):
    rows = _runs(github, repo, WORKFLOW)
    matches = [row for row in rows or [] if row.get("display_title") == title]
    return matches[0]["id"] if len(matches) == 1 else None


def _worker_run(github, repo, run_id, request_id):
    run = github("GET", f"/repos/{repo}/actions/runs/{run_id}")
    if (
        run.get("path") != f".github/workflows/{WORKFLOW}"
        or run.get("id") != run_id
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or not re.fullmatch(r"[0-9a-f]{40}", str(run.get("head_sha") or ""))
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
    if any(
        candidate.get(key) != value
        for key, value in {
            "request_id": _request_id(task),
            "run_id": str(run["id"]),
            "repository": request["repository"],
            "base_sha": request["source_sha"],
            "task_id": task.para_task_id,
            "attempt_id": task.attempt_id,
        }.items()
    ):
        transition(
            db, task, "reconciling", "publication_candidate_identity_mismatch", snapshot=state
        )
        return
    repo = request["repository"]
    response = github("GET", f"/repos/{repo}/actions/runs/{run['id']}/attempts/1/jobs?per_page=100")
    jobs = response.get("jobs")
    publishers = (
        [job for job in jobs if isinstance(job, dict) and job.get("name") == "publish-candidate"]
        if isinstance(jobs, list)
        else []
    )
    branch = candidate["branch"]
    ref = github("GET", f"/repos/{repo}/git/ref/heads/{quote(branch, safe='/')}")
    if (
        not isinstance(jobs, list)
        or response.get("total_count") != len(jobs)
        or len(publishers) != 1
        or type(publishers[0].get("id")) is not int
        or publishers[0]["id"] < 1
        or any(
            publishers[0].get(key) != value
            for key, value in {
                "conclusion": "success",
                "status": "completed",
                "run_id": run["id"],
                "run_attempt": 1,
                "head_sha": run.get("head_sha"),
            }.items()
        )
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
                        "request_id": _request_id(task),
                        "source_sha": request["source_sha"],
                        "controller_sha": run["head_sha"],
                        "publication_job_id": publishers[0]["id"],
                        "budget_request_id": budget_request_id(_request_id(task)),
                        "execution_isolation": state["model_allocation"]["execution_isolation"],
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
        or raw.get("branch") != request["source_sha"]
        or raw.get("description") != request["message"]
    ):
        raise HTTPException(409, "Para 原任务回执身份不一致")
    if task.state == "dispatching":
        transition(db, task, "running", "para_dispatch_receipt_observed", snapshot=state)
    if not para_task_succeeded(raw, task.para_task_id, planned_devices=[task.device_id]):
        return
    workspace = {**request, "request_id": request_id, "run_id": state["run_id"]}
    candidate = candidate_receipt(_task_result_snapshot({"task": raw}), workspace, task.attempt_id)
    if candidate:
        from modstore_server.strategic_workspace_bridge import candidate_metered

        if not candidate_metered(budget_request_id(request_id), candidate):
            return
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
            "tool_name": "opencode",
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
        from modstore_server import strategic_workspace_bridge as strategic
        from modstore_server.para_execution_isolation import (
            HEADER_ONLY_PLATFORM_PROFILE,
            feedback_executor_configured,
        )
        from modstore_server.para_model_admission import platform_model_admission

        budget_id = budget_request_id(request_id)
        if not feedback_executor_configured() or not strategic.ready(budget_id):
            transition(db, task, "waiting_device", "original_pr_isolated_budget_required")
            return

        allocation = platform_model_admission()
        if allocation:
            allocation = {**allocation, "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE}
        state["model_allocation"] = allocation
        if not allocation or allocation.get("status") != "admitted":
            transition(db, task, "waiting_device", "platform_model_capacity", snapshot=state)
            return
        budget, _, _ = strategic.remote.read_request(budget_id)
        strategic.verify_allocation(budget, state)
        if github("GET", f"/repos/{repo}/commits/main").get("sha") != budget["source_sha"]:
            transition(
                db, task, "waiting_device", "original_pr_controller_source_changed", snapshot=state
            )
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
            .order_by(MacControlTask.updated_at, MacControlTask.created_at)
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
            task.updated_at = time.time()
            db.commit()


def run_status(task):
    from modstore_server.strategic_workspace_bridge import candidate_metered, descriptor

    request, state = json.loads(task.request_json), json.loads(task.snapshot_json)
    budget_id = budget_request_id(_request_id(task))
    budget = descriptor(budget_id)
    candidate = state.get("candidate")
    if (
        candidate
        and task.state not in TERMINAL
        and (not budget or not candidate_metered(budget_id, candidate))
    ):
        candidate = None
    return {
        "kind": REPAIR_KIND,
        "request_id": _request_id(task),
        "repository": request["repository"],
        "issue_number": request["github_issue"],
        "pull_request": request["pull_request"],
        "source_run_id": request["source_run_id"],
        "source_sha": request["source_sha"],
        "original_request_digest": task.request_digest,
        "run_id": state.get("run_id"),
        "status": task.state,
        "finished": task.state in TERMINAL or task.state == "cancel_requested",
        "conclusion": "success" if task.state == "execution_completed" else "unknown",
        "publication_candidate": candidate,
        "model_allocation": state.get("model_allocation"),
        "strategic_budget": budget,
        "publication_authorized": bool(
            task.state == "execution_completed"
            and budget
            and candidate
            and candidate_metered(budget_id, candidate, allow_published=True)
        ),
    }
