"""Phase and Para subtask capabilities for the existing isolated GitHub worker."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from modstore_server import strategic_remote_bridge as remote
from modstore_server import strategic_workspace_bridge as bridge
from modstore_server.models import IncidentEvent
from modstore_server.para_execution_isolation import HEADER_ONLY_PLATFORM_PROFILE
from modstore_server.strategic_portfolio import PortfolioError, _date, digest


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _phase_identity(request: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.customer_ticket_github import github

    if request["kind"] == "original_pr_repair":
        from modstore_server.para_github_repair import require_current_source

        require_current_source(request)
    run = remote.native_run(request, identity.get("run_id"))
    phase = identity.get("phase")
    expected = {
        "run_id": run["id"],
        "run_attempt": 1,
        "phase": phase,
        "repository": request["repository"],
        "source_sha": request.get("controller_sha", request["source_sha"]),
        "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
    }
    if (
        phase not in {"execute", "resume"}
        or (request["kind"] == "original_pr_repair" and phase != "execute")
        or identity != expected
        or run.get("status") != "in_progress"
    ):
        raise PortfolioError("workspace phase identity is not the approved active run")
    response = github(
        "GET",
        f"/repos/{request['repository']}/actions/runs/{run['id']}/attempts/1/jobs?per_page=100",
    )
    jobs = response.get("jobs")
    if not isinstance(jobs, list) or response.get("total_count") != len(jobs):
        raise PortfolioError("workspace native job inventory is incomplete")
    required = (
        {"employee-workspace": "in_progress"}
        if phase == "execute"
        else {
            "employee-workspace": "completed",
            "publish-candidate": "completed",
            "resume-verification": "in_progress",
        }
    )
    observed = {}
    for name, status in required.items():
        selected = [
            job for job in jobs if job.get("name") == name and job.get("run_id") == run["id"]
        ]
        if (
            len(selected) != 1
            or selected[0].get("status") != status
            or (status == "completed" and selected[0].get("conclusion") != "success")
        ):
            raise PortfolioError("workspace phase has not passed the original native job gates")
        job = selected[0]
        started = _date(str(job.get("started_at") or ""))
        if started > datetime.now(UTC):
            raise PortfolioError("workspace native job start is not confirmed")
        observed[name] = {"job_id": job["id"], "started_at": started.isoformat()}
        if status == "completed":
            ended = _date(str(job.get("completed_at") or ""))
            if not started <= ended <= datetime.now(UTC):
                raise PortfolioError("workspace native job completion time is not confirmed")
            observed[name].update(
                completed_at=ended.isoformat(),
                compute_seconds=max(1, math.ceil((ended - started).total_seconds())),
            )
    return observed


def claim_phase(request_id: str, identity: dict[str, Any]) -> dict[str, Any]:
    request, _, _ = remote.read_request(request_id)
    if request["kind"] not in {bridge.KIND, "original_pr_repair"}:
        raise PortfolioError("not an approved engineering work order")
    jobs = _phase_identity(request, identity)
    token = secrets.token_urlsafe(40)

    def claim(row, proposal, state, saved, record, snapshot, session):
        bridge.authorized(row, proposal, state, saved, request, session)
        _, _, effects = bridge.original(session, request, active=True)
        bridge.verify_allocation(request, effects)
        if effects.get("run_id") != identity["run_id"]:
            raise PortfolioError("workspace native run differs from the original request")
        history = snapshot.setdefault("phases", {})
        phase = identity["phase"]
        if (
            phase in history
            or (phase == "execute" and history)
            or (phase == "resume" and "execute" not in history)
        ):
            raise PortfolioError("workspace phase cannot be claimed or replayed")
        elapsed = (
            history["execute"]["compute_before"]
            + jobs["employee-workspace"]["compute_seconds"]
            + jobs["publish-candidate"]["compute_seconds"]
            if phase == "resume"
            else saved.get("compute_seconds", 0)
        )
        if any(call.get("status") != "settled" for call in saved["calls"].values()):
            raise PortfolioError("workspace previous model usage is not yet settled")
        if elapsed < saved.get("compute_seconds", 0):
            raise PortfolioError("workspace cumulative compute time cannot decrease")
        remaining = saved["reservation"]["compute_seconds"] - elapsed
        active_job = jobs["employee-workspace" if phase == "execute" else "resume-verification"]
        deadline = min(
            _date(active_job["started_at"]) + timedelta(seconds=remaining),
            _date(request["deadline"]),
        )
        if remaining <= 0 or deadline <= datetime.now(UTC):
            raise PortfolioError("workspace phase exhausted its remaining compute budget")
        saved.update(
            compute_seconds=elapsed,
            deadline=deadline.isoformat(),
            worker_capacity={"state": "active"},
        )
        # Native completed execute + publisher jobs authorize the existing resume
        # stage, even when the prior process lost its final acknowledgement.
        snapshot.pop("model_grant", None)
        if "execute" in history:
            history["execute"].pop("bootstrap_sha256", None)
            history["execute"].update(status="closed", native_job=jobs["employee-workspace"])
        history[phase] = {
            **identity,
            "bootstrap_sha256": _sha(token),
            "status": "active",
            "claimed_at": datetime.now(UTC).isoformat(),
            "deadline": deadline.isoformat(),
            "native_job": active_job,
            "compute_before": elapsed,
        }
        snapshot.update(phase=phase, run_id=identity["run_id"])
        saved["status"], record.state = "running", "bootstrapped"
        return {
            "schema": request["schema"],
            "kind": request["kind"],
            "request_id": request_id,
            "binding_id": request["binding"]["binding_id"],
            **identity,
            "deadline": deadline.isoformat(),
            "model": request["model"],
            "device_id": os.environ.get("MODSTORE_PARA_GITHUB_DEVICE_ID", ""),
            "gateway_url": f"{request['gateway_base']}/{request_id}/v1",
            "bootstrap_token": token,
        }

    return cast(dict[str, Any], remote.authorized_mutate(request_id, claim))


def _bootstrap(snapshot, token, phase):
    entry = snapshot.get("phases", {}).get(phase, {})
    if (
        snapshot.get("phase") != phase
        or entry.get("status") != "active"
        or not bridge.token_matches(token, entry.get("bootstrap_sha256", ""))
    ):
        raise PortfolioError("workspace bootstrap grant is invalid or no longer active")


def current_attempt(session, request, effects, event_id, identity):
    """The original incident claim remains the authority, not a worker payload."""
    if request["kind"] == "original_pr_repair":
        from modstore_server.para_github_repair import current_attempt as original_pr_attempt

        return original_pr_attempt(session, request, effects, event_id, identity)
    from modstore_server.retort_github_workspace import authorized_incident

    event = session.get(IncidentEvent, event_id) if event_id else None
    payload = json.loads(event.payload_json) if event else {}
    if event is None or not authorized_incident(session, payload, event_id):
        raise PortfolioError("workspace original event is not authorized")
    workspace = payload.get("github_workspace") or {}
    if (
        workspace.get("request_id") != request["original_request_id"]
        or workspace.get("run_id") != effects.get("run_id")
        or payload.get("user_id") != request["binding"]["owner_user_id"]
    ):
        raise PortfolioError("workspace original event identity changed")
    matches = [
        member
        for member in payload.get("_team_claim", {}).get("team", [])
        if member.get("attempt_id") == identity.get("attempt_id")
    ]
    if len(matches) != 1 or matches[0].get("status") in {
        "failed",
        "cancelled",
        "rejected",
        "manual_review",
    }:
        raise PortfolioError("workspace original attempt is no longer current")
    member = matches[0]
    roles = {"scout", "fix"} if identity["phase"] == "execute" else {"verify"}
    if member.get("role") not in roles:
        raise PortfolioError("workspace role is outside the original native phase")
    outputs = [
        out
        for out in (member.get("handler_outputs") or {}).get("outputs", [])
        if out.get("handler") == "para_delegate"
    ]
    if len(outputs) != 1:
        raise PortfolioError("workspace original task receipt is pending")
    output = outputs[0]
    if (
        str(output.get("para_task_id") or output.get("task_id") or "") != identity["task_id"]
        or output.get("executor") != "github_actions"
        or output.get("accepted") is not True
        or output.get("partial")
        or output.get("required_subtask_ids") != [identity["subtask_id"]]
        or output.get("planned_devices") != [identity["device_id"]]
    ):
        raise PortfolioError("workspace original task receipt identity mismatch")
    return member


def _native_task(request, identity):
    from modstore_server.mac_control_transport import ParaClient
    from modstore_server.para_github_runner import device_matches

    client = ParaClient(github_worker=True)
    try:
        task = client.task(identity["task_id"])
        devices = client.devices()
    finally:
        client.close()
    marker = hashlib.sha256(request["original_request_id"].encode()).hexdigest()[:32]
    subs = [sub for sub in task.get("subTasks", []) if str(sub.get("id")) == identity["subtask_id"]]
    workspace = {"request_id": request["original_request_id"], "run_id": identity["run_id"]}
    native = {
        "title": task.get("title"),
        "description": task.get("description"),
        "repo_url": task.get("repo_url"),
        "base_branch": task.get("branch"),
        "work_branch": subs[0].get("branch_name") if len(subs) == 1 else None,
    }
    if (
        len(subs) != 1
        or len(task.get("subTasks", [])) != 1
        or task.get("status") not in {"pending", "running", "assigned", "in_progress"}
        or subs[0].get("status") not in {"pending", "running", "assigned", "in_progress"}
        or str(subs[0].get("device_id")) != identity["device_id"]
        or subs[0].get("tool_name") != "opencode"
        or task.get("auto_merge") is True
        or identity.get("auto_merge") is not False
        or not str(native["title"]).startswith(f"[xcmax:{marker}:{identity['attempt_id']}]")
        or native["repo_url"] != f"https://github.com/{request['repository']}.git"
        or any(identity.get(key) != value for key, value in native.items())
        or not any(
            device_matches(device, workspace)
            and device.get("id") == identity["device_id"]
            and (device.get("capabilities") or {}).get("github_stage") == identity["phase"]
            for device in devices
        )
    ):
        raise PortfolioError("workspace native Para task or device identity mismatch")


def bind_task(request_id: str, token: str, identity: dict[str, Any]) -> dict[str, Any]:
    request, snapshot, _ = remote.read_request(request_id)
    if request["kind"] not in {bridge.KIND, "original_pr_repair"}:
        raise PortfolioError("not an approved engineering work order")
    fields = {
        "phase",
        "run_id",
        "task_id",
        "subtask_id",
        "attempt_id",
        "device_id",
        "title",
        "description",
        "repo_url",
        "base_branch",
        "work_branch",
        "auto_merge",
    }
    if identity.keys() != fields:
        raise PortfolioError("workspace task requires its complete native binding")
    _bootstrap(snapshot, token, identity["phase"])
    if request["kind"] == "original_pr_repair":
        from modstore_server.para_github_repair import require_current_source

        require_current_source(request)
    _native_task(request, identity)
    model_token = secrets.token_urlsafe(40)

    def bind(row, proposal, state, saved, record, current, session):
        bridge.authorized(row, proposal, state, saved, request, session)
        _bootstrap(current, token, identity["phase"])
        original_row, original_request, effects = bridge.original(session, request, active=True)
        if request["kind"] == "original_pr_repair" and identity[
            "description"
        ] != original_request.get("message"):
            raise PortfolioError("workspace task prompt differs from its approved original request")
        bridge.verify_allocation(request, effects)
        if identity["run_id"] != effects.get("run_id") or current.get("model_grant"):
            raise PortfolioError("workspace has another active model task")
        event_id = getattr(original_row, "event_id", None)
        member = current_attempt(session, request, effects, event_id, identity)
        source_sha = request["source_sha"]
        if member["role"] == "verify":
            event = session.get(IncidentEvent, original_row.event_id)
            team = json.loads(event.payload_json).get("_team_claim", {}).get("team", [])
            revisions = {
                output.get("commit_sha")
                for fix in team
                if fix.get("role") == "fix" and fix.get("ok") is True
                for output in (fix.get("handler_outputs") or {}).get("outputs", [])
                if output.get("handler") == "para_delegate"
            }
            if len(revisions) != 1 or not re.fullmatch(
                r"[0-9a-f]{40}", str(next(iter(revisions), ""))
            ):
                raise PortfolioError("workspace original fix revision is not confirmed")
            source_sha = next(iter(revisions))
        if identity["base_branch"] != source_sha:
            raise PortfolioError("workspace task source differs from its approved original phase")
        grants = current.setdefault("task_grants", [])
        if any(
            item["task_id"] == identity["task_id"] and item["subtask_id"] == identity["subtask_id"]
            for item in grants
        ):
            raise PortfolioError("workspace task grant cannot be replayed")
        bound_event = current.get("event_id", event_id)
        if request["kind"] != "original_pr_repair" and (not bound_event or bound_event != event_id):
            raise PortfolioError("workspace original event changed")
        grant = {
            **{
                k: identity[k]
                for k in ("phase", "run_id", "task_id", "subtask_id", "attempt_id", "device_id")
            },
            **({"event_id": bound_event} if bound_event is not None else {}),
            "role": member["role"],
            "task_sha256": digest(identity),
            "source_sha": source_sha,
            "grant_id": secrets.token_hex(16),
        }
        current["model_grant"] = {**grant, "token_sha256": _sha(model_token)}
        if bound_event is not None:
            current["event_id"] = bound_event
        grants.append({**grant, "status": "active"})
        record.state = "claimed"
        return {
            **grant,
            "schema": request["schema"],
            "kind": request["kind"],
            "request_id": request_id,
            "model_token": model_token,
            "model": request["model"],
            "deadline": current["phases"][identity["phase"]]["deadline"],
            "gateway_url": f"{request['gateway_base']}/{request_id}/v1",
        }

    return cast(dict[str, Any], remote.authorized_mutate(request_id, bind))


def close_grant(request_id: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
    """Revocation needs no fresh permission; it never settles or fabricates usage."""

    def close(_row, _proposal, _state, _saved, record, snapshot, _session):
        phase, grant_id = body.get("phase"), body.get("grant_id")
        _bootstrap(snapshot, token, phase)
        if body.keys() != ({"phase", "grant_id"} if grant_id else {"phase"}):
            raise PortfolioError("invalid workspace close receipt")
        grant = snapshot.get("model_grant") or {}
        if grant_id and grant.get("grant_id") != grant_id:
            if any(
                item.get("grant_id") == grant_id and item.get("status") == "closed"
                for item in snapshot.get("task_grants", [])
            ):
                return {"accepted": True}
            raise PortfolioError("workspace close does not own the active task")
        for item in snapshot.get("task_grants", []):
            if item.get("status") == "active":
                item["status"] = "closed"
        snapshot.pop("model_grant", None)
        if not grant_id:
            snapshot["phases"][phase].pop("bootstrap_sha256", None)
            snapshot["phases"][phase]["status"] = "closed"
            record.state = "waiting_phase"
        else:
            record.state = "bootstrapped"
        return {"accepted": True, "status": "original_work_order_pending"}

    return cast(dict[str, Any], remote._mutate(request_id, close))
