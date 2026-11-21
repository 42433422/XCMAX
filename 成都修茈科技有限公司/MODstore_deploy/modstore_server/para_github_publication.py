"""Read one authorized fix's artifact identity from its original Para receipt."""

from __future__ import annotations

import hashlib
import re

from modstore_server.customer_service_tools import json_loads

SCHEMA = "para-github-candidate/v1"
RECEIPT_KEYS = {
    "source",
    "pushed",
    "publication",
    "base_sha",
    "branch",
    "task_id",
    "subtask_id",
    "attempt_id",
    "commit_sha",
    "archive_sha256",
    "bundle_sha256",
}


def candidate_receipt(snapshot, workspace, attempt_id):
    """Candidate data is never a successful execution/verification receipt."""
    children = snapshot.get("subtasks") or []
    candidates = []
    for log in snapshot.get("logs_tail", []):
        value = json_loads(log.get("content", ""), {})
        if not isinstance(value, dict) or value.get("publication") != "artifact_pending":
            continue
        if value not in candidates:
            candidates.append(value)
    if not candidates:
        return None
    if len(children) != 1:
        raise ValueError("publication_requires_one_fix_subtask")
    if len(candidates) != 1:
        raise ValueError("ambiguous_publication_candidates")
    value = candidates[0]
    if (
        set(value) != RECEIPT_KEYS
        or value.get("source") != "executor_git_readback"
        or value.get("pushed") is not False
        or value.get("task_id") != snapshot.get("task_id")
        or value.get("subtask_id") != children[0].get("id")
        or value.get("branch") != children[0].get("branch")
        or value.get("attempt_id") != attempt_id
        or not re.fullmatch(r"[0-9a-f]{32}", attempt_id)
        or not re.fullmatch(r"devfleet/[A-Za-z0-9_./-]{1,160}", value.get("branch", ""))
        or ".." in value["branch"]
        or value["branch"].endswith(".lock")
        or any(
            not re.fullmatch(r"[0-9a-f]{40}", str(value.get(k, "")))
            for k in ("base_sha", "commit_sha")
        )
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(value.get(k, "")))
            for k in ("archive_sha256", "bundle_sha256")
        )
        or value["base_sha"] == value["commit_sha"]
        or (workspace.get("source_sha") and value["base_sha"] != workspace["source_sha"])
    ):
        raise ValueError("publication_candidate_identity_mismatch")
    return {
        "schema": SCHEMA,
        "request_id": workspace["request_id"],
        "run_id": str(workspace["run_id"]),
        "repository": workspace["repository"],
        **value,
    }


def publication_candidate(db, event, *, fetcher=None):
    if event is None:
        return None
    from modstore_server.customer_issue_delivery_contract import para_task_succeeded
    from modstore_server.maintenance_loop.para_client import _fetch_para_task_state
    from modstore_server.para_delegate_handler import _task_result_snapshot
    from modstore_server.para_github_runner import api_base

    payload = json_loads(event.payload_json, {})
    workspace = payload.get("github_workspace") or {}
    if workspace.get("retort_run_id"):
        from modstore_server.retort_github_workspace import authorized_incident

        authorized = authorized_incident(db, payload, event.id, read_only=True)
    else:
        from modstore_server.customer_ticket_github import authorized_incident

        authorized = authorized_incident(db, payload, event.id)
    if not workspace or not authorized:
        return None
    rows = (payload.get("_team_claim") or {}).get("team", [])
    if any(r.get("status") in {"failed", "cancelled", "rejected", "manual_review"} for r in rows):
        return None
    fixes = [r for r in rows if r.get("role") == "fix"]
    if not fixes:
        return None
    if len(fixes) != 1:
        raise ValueError("publication_requires_one_fix_attempt")
    fix = fixes[0]
    outputs = [
        o
        for o in (fix.get("handler_outputs") or {}).get("outputs", [])
        if o.get("handler") == "para_delegate"
    ]
    if not outputs:
        return None
    if len(outputs) != 1:
        raise ValueError("publication_requires_one_para_task")
    output = outputs[0]
    required, devices = (
        output.get("required_subtask_ids") or [],
        output.get("planned_devices") or [],
    )
    if len(required) != 1 or len(devices) != 1 or output.get("partial"):
        raise ValueError("publication_requires_complete_single_task_receipt")
    task_id = str(output.get("para_task_id") or output.get("task_id") or "")
    if not task_id or output.get("executor") != "github_actions" or not output.get("accepted"):
        raise ValueError("publication_requires_original_github_receipt")
    task = (fetcher or _fetch_para_task_state)(api_base(), task_id)
    if not para_task_succeeded(task, task_id, required, devices):
        return None
    marker = hashlib.sha256(workspace["request_id"].encode()).hexdigest()[:32]
    if (
        not str(task.get("title", "")).startswith(f"[xcmax:{marker}:{fix['attempt_id']}]")
        or task.get("repo_url") != f"https://github.com/{workspace['repository']}.git"
    ):
        raise ValueError("publication_para_dispatch_mismatch")
    return candidate_receipt(_task_result_snapshot({"task": task}), workspace, fix["attempt_id"])
