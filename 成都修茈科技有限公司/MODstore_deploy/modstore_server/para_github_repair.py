"""Connect an authorized PR incident to the existing hosted Para worker."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import and_, func, or_

from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_store import TERMINAL, acquire, encoded, event, transition
from modstore_server.mac_control_transport import ParaClient, ParaUnavailable
from modstore_server.para_github_runner import WORKFLOW, _claim_worker_slot, device_matches

REPAIR_KIND = "original_pr_repair"
REPAIR_ACTOR = "service:para-github-repair"
SCHEMA = "strategic-pr-repair/v1"
CI_PENDING = "original_pr_ci_pending"
CANCEL_PENDING = "original_pr_cancel_pending"
_SOURCE_FIELDS = (
    "repository",
    "github_issue",
    "pull_request",
    "source_sha",
    "source_run_id",
    "source_run_attempt",
)


def original(session, request, *, active=False):
    from modstore_server.strategic_portfolio import PortfolioError, digest

    row = session.get(MacControlTask, uuid.UUID(request["original_request_id"]).hex)
    source = json.loads(row.request_json) if row is not None else {}
    if (
        row is None
        or row.actor != REPAIR_ACTOR
        or row.request_digest != digest(source)
        or row.request_digest != request.get("original_request_sha256")
        or any(source.get(key) != request.get(key) for key in _SOURCE_FIELDS)
        or (active and row.state in TERMINAL | {"cancel_requested"})
    ):
        raise PortfolioError("original PR request or source identity changed")
    return row, source, json.loads(row.snapshot_json)


def authorized(row, proposal, state, saved, request, session, *, publication=False):
    from modstore_server.strategic_company_resources import require_company_authorization
    from modstore_server.strategic_portfolio import PortfolioError, _date, require_authorization

    authority = state
    if (
        publication
        and state.get("stop_reason") == "upstream_usage_unknown"
        and all(
            call.get("status") == "settled"
            for item in state.get("tasks", {}).values()
            for call in item.get("calls", {}).values()
        )
    ):
        # This checks the already-approved publisher only. It neither renews
        # model authority nor erases the persisted original accounting hold.
        authority = {**state, "halted": False, "stop_reason": ""}
    require_authorization(row, proposal, authority, session=session)
    if not proposal["limits"].get("company_budget_id"):
        raise PortfolioError("original PR requires its approved company budget")
    require_company_authorization(proposal, session)
    spec = next(
        item["input_data"]["remote_execution"]
        for item in proposal["opportunities"]
        if item["opportunity_id"] == request["binding"]["opportunity_id"]
    )
    if (
        any(request.get(key) != value for key, value in spec.items())
        or saved.get("worker_binding") != request["binding"]
        or saved.get("lease_token") != request["binding"]["lease_token"]
        or saved.get("status")
        not in ({"running", "waiting", "completed"} if publication else {"running", "waiting"})
        or _date(request["deadline"]) <= datetime.now(UTC)
    ):
        raise PortfolioError("original PR budget no longer owns this approved execution")
    original(session, request, active=not publication)


def verify_allocation(request, effects):
    from modstore_server.para_execution_isolation import feedback_allocation_isolated
    from modstore_server.strategic_portfolio import PortfolioError

    allocation = effects.get("model_allocation") or {}
    if not feedback_allocation_isolated(allocation) or any(
        allocation.get(key) != request.get(key) for key in ("provider", "model")
    ):
        raise PortfolioError("original PR requires its approved isolated model route")


def attach_workspace(task: dict[str, Any]) -> dict[str, Any]:
    from modstore_server import strategic_remote_bridge as remote
    from modstore_server.customer_ticket_github import github
    from modstore_server.para_execution_isolation import feedback_executor_configured
    from modstore_server.strategic_company_resources import require_company_authorization
    from modstore_server.strategic_execution_contract import freeze_execution
    from modstore_server.strategic_portfolio import PortfolioError

    if not feedback_executor_configured():
        raise PortfolioError("original PR requires the configured isolated OpenCode worker")
    freeze_execution(task["owner_user_id"], task)
    spec = task.get("input_data", {}).get("remote_execution")
    fields = {
        *_SOURCE_FIELDS,
        "kind",
        "original_request_id",
        "original_request_sha256",
        "controller_sha",
        "provider",
        "model",
    }
    if not isinstance(spec, dict) or spec.keys() != fields or spec.get("kind") != REPAIR_KIND:
        raise PortfolioError("original PR requires its complete frozen approval contract")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", str(spec["controller_sha"]))
        or not re.fullmatch(r"[0-9a-f]{64}", str(spec["original_request_sha256"]))
        or type(spec["source_run_attempt"]) is not int
        or spec["source_run_attempt"] < 1
    ):
        raise PortfolioError("invalid original PR source or controller identity")
    request_id = str(uuid.UUID(spec["original_request_id"]))
    if request_id != spec["original_request_id"]:
        raise PortfolioError("original PR requires its canonical request identity")
    remote.contract(
        {
            "input_data": {
                "remote_execution": {
                    **{key: spec[key] for key in ("repository", "source_sha", "provider", "model")},
                    "kind": remote.KIND,
                }
            }
        }
    )
    if (
        not _current_source(github, spec)
        or github("GET", f"/repos/{spec['repository']}/commits/main").get("sha")
        != spec["controller_sha"]
    ):
        raise PortfolioError("original PR source or approved main controller changed")

    def validate(session, proposal):
        require_company_authorization(proposal, session)
        if not proposal["limits"].get("company_budget_id"):
            raise PortfolioError("original PR requires its approved company budget")
        row, _, snapshot = original(session, spec, active=True)
        if (
            snapshot.get("runner_intent")
            or snapshot.get("run_id")
            or row.attempt_id
            or row.para_task_id
        ):
            raise PortfolioError("an already dispatched PR cannot acquire a retrospective budget")

    remote.prepare_request(
        task, spec, request_id, actor=REPAIR_ACTOR, validate=validate, reuse_original=True
    )
    return {
        "ok": True,
        "accepted": True,
        "completed": False,
        "status": "queued",
        "worker_receipt_id": request_id,
        "executor": REPAIR_KIND,
    }


def current_attempt(session, request, effects, _event_id, identity):
    from modstore_server.strategic_portfolio import PortfolioError

    row, _, _ = original(session, request)
    if (
        row.state in {"cancel_requested", "cancelled", "failed"}
        or not row.attempt_id
        or row.attempt_id != identity.get("attempt_id")
        or row.device_id != identity.get("device_id")
        or effects.get("run_id") != identity.get("run_id")
        or identity.get("phase") != "execute"
    ):
        raise PortfolioError("original PR Para attempt is no longer current")
    if not row.para_task_id and row.state == "dispatching":
        raise PortfolioError("workspace original task receipt is pending")
    if row.para_task_id != identity.get("task_id"):
        raise PortfolioError("original PR Para task receipt identity mismatch")
    return {"role": "fix"}


def require_current_source(request):
    from modstore_server.customer_ticket_github import github
    from modstore_server.strategic_portfolio import PortfolioError

    if not _current_source(github, request):
        raise PortfolioError("original PR source or CI attempt is no longer current")


def ready(request_id):
    from modstore_server import strategic_remote_bridge as remote
    from modstore_server.strategic_portfolio import PortfolioError

    try:
        request, _, _ = remote.read_request(request_id)

        def check(row, proposal, state, saved, _record, _snapshot, session):
            authorized(row, proposal, state, saved, request, session)
            return True

        return remote.authorized_mutate(request_id, check)
    except PortfolioError:
        return False


def publication_authorization(request_id):
    """Read original approval and measured calls; worker manifests grant nothing."""
    from modstore_server import strategic_remote_bridge as remote
    from modstore_server.customer_ticket_github import github
    from modstore_server.para_execution_isolation import HEADER_ONLY_PLATFORM_PROFILE
    from modstore_server.strategic_portfolio import PortfolioError, _row, digest

    gate = {}
    try:
        with remote.get_session_factory()() as session:
            record = remote._row(session, request_id)
            request = remote._request(record)
            if request["kind"] != REPAIR_KIND:
                return {}
            binding = request["binding"]
            row, proposal, state = _row(session, binding["decision_id"], binding["owner_user_id"])
            saved = state["tasks"][binding["opportunity_id"]]
            snapshot = remote._snapshot(record, saved)
            candidate = snapshot.get("candidate") or {}
            matches = [
                grant
                for grant in snapshot.get("task_grants", [])
                if grant.get("role") == "fix"
                and grant.get("phase") == "execute"
                and all(
                    grant.get(key) == candidate.get(key)
                    for key in ("task_id", "subtask_id", "attempt_id")
                )
            ]
            calls = list(saved.get("calls", {}).values())
            usage_complete = bool(calls) and all(
                call.get("status") == "settled" and type(call.get("actual_tokens")) is int
                for call in calls
            )
            gate = {
                "schema": "strategic-pr-publication/v1",
                "authorized": False,
                "request_id": request_id,
                "binding_id": binding["binding_id"],
                "decision_id": binding["decision_id"],
                "opportunity_id": binding["opportunity_id"],
                "proposal_sha256": binding["proposal_sha256"],
                "original_request_sha256": request["original_request_sha256"],
                "repository": request["repository"],
                "pull_request": request["pull_request"],
                "issue_number": request["github_issue"],
                "source_sha": request["source_sha"],
                "controller_sha": request["controller_sha"],
                "source_run_id": request["source_run_id"],
                "source_run_attempt": request["source_run_attempt"],
                "run_id": snapshot.get("run_id"),
                "run_attempt": 1,
                "task_id": candidate.get("task_id"),
                "subtask_id": candidate.get("subtask_id"),
                "attempt_id": candidate.get("attempt_id"),
                "candidate_sha256": digest(candidate),
                "candidate_commit_sha": candidate.get("commit_sha"),
                "candidate_branch": candidate.get("branch"),
                "usage_complete": usage_complete,
                "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
                "expires_at": request["deadline"],
            }
            authorized(row, proposal, state, saved, request, session, publication=True)
            verify_allocation(request, snapshot)
            if (
                not usage_complete
                or len(matches) != 1
                or not any(
                    (call.get("caller_binding") or {}).get("grant_id") == matches[0]["grant_id"]
                    for call in calls
                )
            ):
                return gate
            current_attempt(session, request, snapshot, None, matches[0])
            if (
                candidate.get("base_sha") != request["source_sha"]
                or candidate.get("request_id") != request_id
                or str(candidate.get("run_id")) != str(snapshot.get("run_id"))
                or candidate.get("repository") != request["repository"]
            ):
                return gate
        run = remote.native_run(request, gate["run_id"])
        gate["authorized"] = bool(
            _current_source(github, request)
            and run.get("status") in {"in_progress", "completed"}
            and (run.get("status") != "completed" or run.get("conclusion") == "success")
        )
    except (PortfolioError, HTTPException, ValueError, KeyError, TypeError):
        pass
    return gate


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
        or bool(label_names.intersection({"hold-merge", "needs-human"}))
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
        and (
            request.get("source_run_attempt") is None
            or run.get("run_attempt") == request["source_run_attempt"]
        )
        and (run.get("head_repository") or {}).get("full_name") == repo
        and f"- Self-Heal-Run: `{request['source_run_id']}/{run.get('run_attempt')}`"
        in incident_header
    )


def _runs(github, repo, workflow):
    """Require the complete unique workflow inventory before recovering an effect."""
    found, total, page = {}, None, 1
    while True:
        response = github(
            "GET",
            f"/repos/{repo}/actions/workflows/{workflow}/runs?per_page=100&page={page}",
        )
        if not isinstance(response, dict):
            return None
        rows, count = response.get("workflow_runs"), response.get("total_count")
        if (
            not isinstance(rows, list)
            or len(rows) > 100
            or type(count) is not int
            or count < 0
            or (total is not None and total != count)
        ):
            return None
        total = count
        for row in rows:
            if (
                not isinstance(row, dict)
                or type(row.get("id")) is not int
                or row["id"] < 1
                or row["id"] in found
            ):
                return None
            found[row["id"]] = row
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
        or run.get("run_attempt") != 1
        or (run.get("repository") or {}).get("full_name") != repo
        or run.get("display_title") != f"para-workspace-{request_id}"
    ):
        raise HTTPException(409, "Para 云端运行身份不一致")
    return run


def _publish_readback(db, task, request, state, run, github):
    if state.get("strategic_request"):
        from modstore_server.strategic_workspace_receipts import reconcile_request

        reconcile_request(_request_id(task))
        return
    if task.state == "cancel_requested":
        transition(db, task, "cancelled", snapshot=state)
        return
    candidate = state.get("candidate")
    if not candidate or run.get("conclusion") != "success":
        transition(db, task, "failed", "github_worker_unfinished", snapshot=state)
        return
    repo = request["repository"]
    inventory = github(
        "GET", f"/repos/{repo}/actions/runs/{run['id']}/attempts/1/jobs?per_page=100"
    )
    jobs = inventory.get("jobs")
    selected = (
        [job for job in jobs if isinstance(job, dict) and job.get("name") == "publish-candidate"]
        if isinstance(jobs, list)
        else []
    )
    if (
        not isinstance(jobs, list)
        or type(inventory.get("total_count")) is not int
        or inventory["total_count"] != len(jobs)
        or len(selected) != 1
        or type(selected[0].get("id")) is not int
        or selected[0]["id"] < 1
        or selected[0].get("status") != "completed"
        or selected[0].get("conclusion") != "success"
        or selected[0].get("run_id") != run["id"]
        or selected[0].get("run_attempt") != 1
        or selected[0].get("head_sha") != run.get("head_sha")
        or not run.get("head_sha")
        or candidate.get("request_id") != _request_id(task)
        or str(candidate.get("run_id")) != str(run["id"])
        or candidate.get("repository") != repo
        or candidate.get("base_sha") != request["source_sha"]
        or candidate.get("task_id") != task.para_task_id
        or candidate.get("attempt_id") != task.attempt_id
    ):
        transition(db, task, "reconciling", "publication_readback_unconfirmed", snapshot=state)
        return
    branch = candidate["branch"]
    ref = github("GET", f"/repos/{repo}/git/ref/heads/{quote(branch, safe='/')}")
    if (ref.get("object") or {}).get("sha") != candidate["commit_sha"]:
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


def _persist_intent(db, task, expected, snapshot, state, reason, **identity):
    """An expired scheduler cannot overwrite another owner before an external effect."""
    now = time.time()
    if state == "dispatching" and expected["state"] in TERMINAL | {"cancel_requested"}:
        return None
    with db.no_autoflush:
        changed = (
            db.query(MacControlTask)
            .filter(
                MacControlTask.id == task.id,
                MacControlTask.actor == REPAIR_ACTOR,
                MacControlTask.lease_until > now,
                *(getattr(MacControlTask, key) == value for key, value in expected.items()),
            )
            .update(
                {
                    "state": state,
                    "reason": reason,
                    "snapshot_json": encoded(snapshot),
                    "updated_at": now,
                    **identity,
                },
                synchronize_session=False,
            )
        )
        if changed != 1:
            db.rollback()
            return None
        db.expire(task)
        event(
            db,
            task,
            state,
            {"reason": reason, "para_task_id": task.para_task_id, "snapshot": snapshot},
        )
        db.commit()
    return {
        **expected,
        "state": state,
        "reason": reason,
        "snapshot_json": encoded(snapshot),
        **identity,
    }


def _dispatch_para(db, task, request, state, request_id, client, github, expected):
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
    submitted = _persist_intent(
        db,
        task,
        expected,
        state,
        "dispatching",
        "para_dispatch_intent_recorded",
        device_id=devices[0]["id"],
        attempt_id=uuid.uuid4().hex,
    )
    if not submitted:
        return
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
    _persist_intent(db, task, submitted, state, "running", "", para_task_id=raw["id"])


def _process(db, task, github):
    request, state = json.loads(task.request_json), json.loads(task.snapshot_json)
    expected = {
        key: getattr(task, key)
        for key in (
            "state",
            "reason",
            "snapshot_json",
            "request_digest",
            "request_json",
            "lease_until",
            "attempt_id",
            "para_task_id",
            "device_id",
        )
    }
    repo, request_id = request["repository"], _request_id(task)
    if task.state in TERMINAL and state.get("strategic_request"):
        from modstore_server.strategic_workspace_receipts import reconcile_request

        if task.state == "cancelled" and state.get("runner_intent") and not state.get("run_id"):
            run_id = _find_run(github, repo, f"para-workspace-{request_id}")
            if not run_id:
                return
            state["run_id"] = run_id
            if not _persist_intent(db, task, expected, state, "cancelled", CANCEL_PENDING):
                return
        reconcile_request(request_id)
        return
    if not state.get("runner_intent"):
        if task.state == "cancel_requested":
            if not state.get("strategic_request"):
                transition(db, task, "cancelled", "original_request_cancelled")
            elif _persist_intent(db, task, expected, state, "cancelled", CANCEL_PENDING):
                from modstore_server.strategic_workspace_receipts import reconcile_request

                reconcile_request(request_id)
            return
        if not state.get("strategic_request") or not ready(request_id):
            transition(db, task, "awaiting_approval", "original_pr_company_budget_required")
            return
        if not _current_source(github, request):
            state["cancellation_reason"] = "no_current_authorized_pr_failure"
            if _persist_intent(db, task, expected, state, "cancelled", CANCEL_PENDING):
                from modstore_server.strategic_workspace_receipts import reconcile_request

                reconcile_request(request_id)
            return
        approved = state["strategic_request"]
        if github("GET", f"/repos/{repo}/commits/main").get("sha") != approved["controller_sha"]:
            transition(db, task, "awaiting_approval", "original_pr_controller_changed")
            return
        from modstore_server.para_execution_isolation import (
            HEADER_ONLY_PLATFORM_PROFILE,
            feedback_executor_configured,
        )
        from modstore_server.para_model_admission import platform_model_admission

        allocation = platform_model_admission()
        state["model_allocation"] = allocation
        if (
            not feedback_executor_configured()
            or not allocation
            or allocation.get("status") != "admitted"
            or any(allocation.get(key) != approved[key] for key in ("provider", "model"))
            or allocation.get("agent_plan_first")
        ):
            transition(db, task, "waiting_device", "platform_model_capacity", snapshot=state)
            return
        state["model_allocation"] = {
            **allocation,
            "approved_models": [approved["model"]],
            "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
        }
        if not _claim_worker_slot(db, task, owner_key=f"repair:{task.id}"):
            return
        state["runner_intent"] = True
        submitted = _persist_intent(
            db, task, expected, state, "dispatching", "github_dispatch_intent_recorded"
        )
        if not submitted:
            return
        result = github(
            "POST",
            f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
            {"ref": "main", "inputs": {"request_id": request_id}, "return_run_details": True},
        )
        if type(result.get("workflow_run_id")) is int:
            state["run_id"] = result["workflow_run_id"]
            _persist_intent(db, task, submitted, state, "waiting_device", "github_worker_requested")
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
    if state.get("strategic_request") and not _current_source(github, request):
        transition(db, task, "cancel_requested", "original_ci_failure_changed", snapshot=state)
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
        elif state.get("strategic_request") and ready(request_id):
            _dispatch_para(db, task, request, state, request_id, client, github, expected)
    finally:
        client.close()


def sync(factory):
    """Rotate original requests under their existing lease, including pending PR CI."""
    from modstore_server.customer_ticket_github import github
    from modstore_server.strategic_portfolio import PortfolioError

    with factory() as db:
        now = time.time()
        pending = or_(
            and_(
                MacControlTask.state == "execution_completed", MacControlTask.reason == CI_PENDING
            ),
            and_(
                MacControlTask.state == "cancelled",
                MacControlTask.reason.in_({CANCEL_PENDING, "cancelled_before_dispatch"}),
                MacControlTask.snapshot_json.contains('"strategic_request"'),
            ),
        )
        row = (
            db.query(MacControlTask)
            .filter(
                MacControlTask.actor == REPAIR_ACTOR,
                or_(MacControlTask.state.notin_(TERMINAL), pending),
                MacControlTask.lease_until < now,
            )
            .order_by(MacControlTask.updated_at, MacControlTask.created_at, MacControlTask.id)
            .first()
        )
        if row is not None and row.state in TERMINAL:
            # The generic transport lease excludes terminal Mac tasks. This
            # published original still owes its company task a read-only CI result.
            changed = (
                db.query(MacControlTask)
                .filter(
                    MacControlTask.id == row.id,
                    MacControlTask.actor == REPAIR_ACTOR,
                    pending,
                    MacControlTask.lease_until < now,
                )
                .update({"lease_until": now + 120}, synchronize_session=False)
            )
            db.commit()
            db.expire_all()
            task = db.get(MacControlTask, row.id) if changed else None
        else:
            task = acquire(db, row.id, now=now) if row else None
        if task is None:
            return
        failure = ""
        try:
            _process(db, task, github)
        except (ParaUnavailable, HTTPException, PortfolioError, ValueError) as exc:
            # Neither an uncertain dispatch nor a failed observation authorizes a retry.
            failure = f"cloud_receipt_pending:{type(exc).__name__}"
        finally:
            db.refresh(task)
            if failure and task.reason not in {
                CI_PENDING,
                CANCEL_PENDING,
                "cancelled_before_dispatch",
            }:
                task.reason = failure
            latest = (
                db.query(func.max(MacControlTask.updated_at))
                .filter(MacControlTask.actor == REPAIR_ACTOR)
                .scalar()
            )
            task.updated_at = math.nextafter(max(time.time(), latest or 0), math.inf)
            task.lease_until = 0
            db.commit()


def run_status(task):
    request, state = json.loads(task.request_json), json.loads(task.snapshot_json)
    approved = state.get("strategic_request")
    descriptor = {}
    if approved:
        from modstore_server.strategic_workspace_bridge import descriptor as budget_descriptor

        descriptor = budget_descriptor(_request_id(task))
    return {
        "kind": REPAIR_KIND,
        "request_id": _request_id(task),
        "repository": request["repository"],
        "issue_number": request["github_issue"],
        "pull_request": request["pull_request"],
        "source_run_id": request["source_run_id"],
        "source_run_attempt": request.get("source_run_attempt"),
        "source_sha": request["source_sha"],
        "controller_sha": (approved or {}).get("controller_sha"),
        "run_id": state.get("run_id"),
        "status": task.state,
        "finished": task.state in TERMINAL or task.state == "cancel_requested",
        "conclusion": "success" if task.state == "execution_completed" else "unknown",
        "publication_candidate": state.get("candidate"),
        "model_allocation": state.get("model_allocation"),
        "strategic_budget": descriptor,
        "publication_authorization": (
            publication_authorization(_request_id(task)) if approved else {}
        ),
    }
