"""Finish budgets from original Retort delivery or original-PR repair CI receipts."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from modstore_server import strategic_remote_bridge as remote
from modstore_server import strategic_workspace_bridge as bridge
from modstore_server.strategic_portfolio import PortfolioError, _date, digest, portfolio_status


def _evidence(row: Any) -> dict[str, Any]:
    return {
        "status": row.status,
        "snapshot": json.loads(row.snapshot_json),
        "effects": json.loads(row.effects_json),
        "event_id": row.event_id,
    }


def _terminal(request: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any] | None:
    status, state, effects = evidence["status"], evidence["snapshot"], evidence["effects"]
    if status not in {"completed", "failed", "cancelled", "rejected", "customer_impact_rejected"}:
        return None
    if state.get("status") != status:
        return None  # The LangGraph checkpoint has not projected its final state.
    verification, delivery = state.get("verification", {}), state.get("delivery", {})
    if status == "completed":
        from modstore_server.integrations.repository_packages import load_repository_module

        contract = load_repository_module("retort_engine.evolution_contract")
        approval = state.get("approval") or {}
        if (
            verification.get("status") != "checks_passed"
            or verification.get("request_id") != request["original_request_id"]
            or verification.get("protocol_digest") != request["protocol_digest"]
            or verification.get("run_id") != str(effects.get("run_id"))
            or verification != effects.get("verification")
            or not verification.get("evidence_archive")
            or approval.get("approved") is not True
            or approval.get("digest") != contract.digest(verification)
            or delivery.get("status") != "deployment_verified"
            or delivery.get("candidate_sha") != verification.get("target_sha")
            or not delivery.get("receipt")
            or delivery.get("release_sha") != (delivery.get("identity") or {}).get("git_sha")
            or not (delivery.get("identity") or {}).get("artifact_sha256")
            or (
                state.get("has_customer_feedback")
                and (state.get("impact") or {}).get("status") != "customer_impact_verified"
            )
        ):
            raise PortfolioError(
                "original benchmark, acceptance and delivery receipts are incomplete"
            )
    if (
        status == "customer_impact_rejected"
        and state.get("recovery", {}).get("status") != "rollback_verified"
    ):
        return None
    completed = status == "completed"
    return {
        "ok": completed,
        "completed": True,
        "status": "completed" if completed else "failed",
        "executor": bridge.KIND,
        "error": "" if completed else f"original_work_order_{status}",
        **(
            {
                "artifact_id": f"retort:{request['original_request_id']}:{delivery['release_sha']}",
                "artifact_sha256": delivery["identity"]["artifact_sha256"],
            }
            if completed
            else {}
        ),
        "remote_receipt": {
            "schema": bridge.SCHEMA,
            "request_id": request["original_request_id"],
            "protocol_digest": request["protocol_digest"],
            "original_sha256": digest(evidence),
            "verification": verification,
            "delivery": delivery,
            "impact": state.get("impact"),
            "recovery": state.get("recovery"),
        },
    }


def validate_terminal(session: Any, request: dict[str, Any], result: dict[str, Any]) -> None:
    if request["kind"] == "original_pr_repair":
        from modstore_server.db.mac_control import MacControlTask
        from modstore_server.para_github_repair import SCHEMA, original

        row, _, snapshot = original(session, request)
        candidate = snapshot.get("candidate") or {}
        proof = result.get("remote_receipt") or {}
        identity = {
            "schema": SCHEMA,
            "request_id": request["original_request_id"],
            "run_id": snapshot.get("run_id"),
            "controller_sha": request["controller_sha"],
            "source_sha": request["source_sha"],
            "source_run_id": request["source_run_id"],
            "source_run_attempt": request["source_run_attempt"],
            "candidate_sha256": digest(candidate),
        }
        if (
            any(proof.get(key) != value for key, value in identity.items())
            or (result.get("ok") is True and not candidate)
            or proof.get("stage")
            not in {"publication", "original_ci", "worker_failed", "not_dispatched"}
            or (proof["stage"] == "original_ci" and row.state != "execution_completed")
        ):
            raise PortfolioError("original PR changed during native receipt readback")
        if proof["stage"] == "not_dispatched":
            if (
                row.state != "cancelled"
                or row.attempt_id
                or row.para_task_id
                or row.device_id
                or any(snapshot.get(key) for key in ("runner_intent", "run_id", "candidate"))
            ):
                raise PortfolioError("original PR submission outcome is not empty")
            # Lock the same Mac facts inside the portfolio CAS. A concurrent
            # native intent must conflict before this zero-call settlement commits.
            changed = (
                session.query(MacControlTask)
                .filter(
                    MacControlTask.id == row.id,
                    MacControlTask.snapshot_json == row.snapshot_json,
                    MacControlTask.request_digest == request["original_request_sha256"],
                    MacControlTask.state == "cancelled",
                    MacControlTask.reason == row.reason,
                    MacControlTask.lease_until == row.lease_until,
                    MacControlTask.attempt_id == "",
                    MacControlTask.para_task_id == "",
                    MacControlTask.device_id == "",
                )
                .update({"reason": row.reason}, synchronize_session=False)
            )
            if changed != 1:
                raise PortfolioError("original PR changed during undispatched cancellation")
        return
    row, _, _ = bridge.original(session, request)
    original_result = {
        **result,
        "remote_receipt": {
            key: value for key, value in result["remote_receipt"].items() if key != "native_compute"
        },
    }
    if _terminal(request, _evidence(row)) != original_result:
        raise PortfolioError("original work order changed during terminal receipt readback")


def _jobs(request: dict[str, Any], run_id: int) -> dict[str, Any]:
    from modstore_server.customer_ticket_github import github

    response = github(
        "GET", f"/repos/{request['repository']}/actions/runs/{run_id}/attempts/1/jobs?per_page=100"
    )
    rows = response.get("jobs")
    if (
        not isinstance(rows, list)
        or type(response.get("total_count")) is not int
        or response["total_count"] != len(rows)
    ):
        raise PortfolioError("workspace native job inventory is incomplete")
    found: dict[str, Any] = {}
    names, ids = set(), set()
    original_pr = request["kind"] == "original_pr_repair"
    for row in rows:
        if not isinstance(row, dict):
            raise PortfolioError("workspace native compute job identity is ambiguous")
        if original_pr:
            if (
                type(row.get("id")) is not int
                or row["id"] < 1
                or row["id"] in ids
                or row.get("run_id") != run_id
                or row.get("run_attempt") != 1
                or row.get("head_sha") != request["controller_sha"]
            ):
                raise PortfolioError("original PR native job identity is ambiguous")
            ids.add(row["id"])
        name = row.get("name")
        if name not in {
            "employee-workspace",
            "publish-candidate",
            "resume-verification",
            "independent-verification",
        }:
            continue
        if name in names or row.get("run_id") != run_id:
            raise PortfolioError("workspace native compute job identity is ambiguous")
        names.add(name)
        if original_pr and row.get("status") != "completed":
            raise PortfolioError("original PR native compute job is still pending")
        if row.get("status") != "completed" or row.get("conclusion") == "skipped":
            continue
        started, completed = _date(str(row.get("started_at") or "")), _date(
            str(row.get("completed_at") or "")
        )
        if not started <= completed <= datetime.now(UTC):
            raise PortfolioError("workspace native compute duration is unconfirmed")
        found[name] = {
            "job_id": row["id"],
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "compute_seconds": max(1, math.ceil((completed - started).total_seconds())),
            **({"conclusion": row.get("conclusion")} if original_pr else {}),
        }
    return found


def project_pr_receipt(record: Any, saved: dict[str, Any], result: dict[str, Any]) -> None:
    """Close model authority and project publication, separately from original PR CI."""
    from modstore_server.para_github_repair import CI_PENDING
    from modstore_server.strategic_portfolio import _json

    proof = result["remote_receipt"]
    state = json.loads(record.snapshot_json)
    remote_state = saved.get("remote_state", {})
    remote_state.pop("model_grant", None)
    for phase in remote_state.get("phases", {}).values():
        phase.pop("bootstrap_sha256", None)
        phase["status"] = "closed"
    for grant in remote_state.get("task_grants", []):
        grant["status"] = "closed"
    job = proof["native_compute"]["jobs"].get("employee-workspace")
    repo = json.loads(record.request_json)["repository"]
    saved["worker_capacity"] = {
        "state": "idle",
        "phase_receipt_id": (
            f"github:{repo}:run:{proof['run_id']}:job:{job['job_id']}" if job else ""
        ),
    }
    if proof["stage"] == "publication":
        candidate = state["candidate"]
        state.update(
            id=record.para_task_id,
            subtasks=[{"id": candidate["subtask_id"], "branch_name": candidate["branch"]}],
            reports=[
                {
                    "report": {
                        "source": "github_isolated_publisher",
                        "pushed": True,
                        "branch": candidate["branch"],
                        "commit_sha": candidate["commit_sha"],
                        "github_run_id": state["run_id"],
                        "source_sha": proof["source_sha"],
                        "controller_sha": proof["controller_sha"],
                        "publisher_job_id": proof["native_compute"]["jobs"]["publish-candidate"][
                            "job_id"
                        ],
                    }
                }
            ],
        )
        record.snapshot_json = _json(state)
        record.state, record.reason = "execution_completed", CI_PENDING
    elif proof["stage"] == "original_ci":
        record.state = "execution_completed"
        record.reason = f"original_pr_ci_{saved['status']}"
    elif proof["stage"] == "not_dispatched":
        record.state, record.reason = "cancelled", "original_pr_cancelled_before_dispatch"
    else:
        record.state, record.reason = "failed", "original_pr_worker_unfinished"


def _pr_ci(request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Read the same PR's actual candidate CI even after write authority is revoked."""
    from modstore_server.customer_ticket_github import github
    from modstore_server.para_github_repair import _runs

    repo = request["repository"]
    pr = github("GET", f"/repos/{repo}/pulls/{request['pull_request']}")
    source = github(
        "GET",
        f"/repos/{repo}/actions/runs/{request['source_run_id']}"
        f"/attempts/{request['source_run_attempt']}",
    )
    head, base = pr.get("head") or {}, pr.get("base") or {}
    workflow = source.get("workflow_id")
    if (
        not (pr.get("state") == "open" or pr.get("merged") is True)
        or head.get("sha") != candidate["commit_sha"]
        or head.get("ref") != source.get("head_branch")
        or (head.get("repo") or {}).get("full_name") != repo
        or (base.get("repo") or {}).get("full_name") != repo
        or base.get("ref") != "main"
        or source.get("id") != request["source_run_id"]
        or source.get("run_attempt") != request["source_run_attempt"]
        or source.get("head_sha") != request["source_sha"]
        or source.get("event") != "pull_request"
        or (source.get("head_repository") or {}).get("full_name") != repo
        or type(workflow) is not int
        or workflow < 1
    ):
        return None
    inventory = _runs(github, repo, workflow)
    if inventory is None:
        return None
    matches = [
        run
        for run in inventory
        if run.get("head_sha") == candidate["commit_sha"]
        and run.get("head_branch") == head["ref"]
        and run.get("workflow_id") == workflow
        and run.get("event") == "pull_request"
        and (run.get("repository") or {}).get("full_name") == repo
        and isinstance(run.get("pull_requests"), list)
        and (
            not run["pull_requests"]
            or any(
                isinstance(item, dict) and item.get("number") == request["pull_request"]
                for item in run["pull_requests"]
            )
        )
    ]
    if not matches:
        return None
    latest = max(matches, key=lambda run: run["id"])
    if (
        latest.get("status") != "completed"
        or type(latest.get("run_attempt")) is not int
        or latest["run_attempt"] < 1
        or latest.get("conclusion")
        not in {
            "success",
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
            "startup_failure",
            "neutral",
            "skipped",
            "stale",
        }
    ):
        return None
    return {
        "run_id": latest["id"],
        "run_attempt": latest["run_attempt"],
        "workflow_id": workflow,
        "head_sha": latest["head_sha"],
        "status": "checks_passed" if latest["conclusion"] == "success" else "checks_failed",
        "conclusion": latest["conclusion"],
    }


def _reconcile_pr(
    request_id: str, request: dict[str, Any], snapshot: dict[str, Any], state: str
) -> bool:
    from modstore_server.customer_ticket_github import github
    from modstore_server.para_github_repair import REPAIR_KIND, SCHEMA, original
    from modstore_server.strategic_portfolio_runtime import _finish

    binding = request["binding"]
    portfolio = portfolio_status(binding["decision_id"], owner_user_id=binding["owner_user_id"])
    saved = portfolio["tasks"][binding["opportunity_id"]]
    if saved["status"] not in {"running", "waiting"}:
        return False
    with remote.get_session_factory()() as session:
        row, _, _ = original(session, request)
        original_task, original_attempt, original_device = (
            row.para_task_id,
            row.attempt_id,
            row.device_id,
        )
    run_id = snapshot.get("run_id")
    not_dispatched = run_id is None
    if not_dispatched:
        if (
            state != "cancelled"
            or original_task
            or original_attempt
            or original_device
            or saved["calls"]
            or any(
                snapshot.get(key)
                for key in (
                    "runner_intent",
                    "candidate",
                    "phases",
                    "phase",
                    "task_grants",
                    "model_grant",
                )
            )
        ):
            return False
        run, jobs = {"id": None, "conclusion": "cancelled"}, {}
    else:
        if type(run_id) is not int or run_id < 1:
            raise PortfolioError("remote report requires its native GitHub run")
        run = remote.native_run(request, run_id)
        if run.get("status") != "completed":
            return False
        jobs = _jobs(request, run_id)
    candidate = snapshot.get("candidate") or {}
    published = state == "execution_completed"
    success = bool(
        candidate
        and run.get("conclusion") == "success"
        and state not in {"cancel_requested", "cancelled"}
    )
    verification = None
    if success:
        phase = snapshot.get("phases", {}).get("execute", {})
        if (
            candidate.get("request_id") != request_id
            or str(candidate.get("run_id")) != str(run["id"])
            or candidate.get("repository") != request["repository"]
            or candidate.get("base_sha") != request["source_sha"]
            or candidate.get("task_id") != original_task
            or candidate.get("attempt_id") != original_attempt
            or any(
                jobs.get(name, {}).get("conclusion") != "success"
                for name in ("employee-workspace", "publish-candidate")
            )
            or jobs["employee-workspace"]["job_id"] != phase.get("native_job", {}).get("job_id")
        ):
            raise PortfolioError("original PR native publication is not confirmed")
        grants = [
            grant
            for grant in snapshot.get("task_grants", [])
            if grant.get("role") == "fix"
            and grant.get("phase") == "execute"
            and all(
                grant.get(key) == candidate.get(key)
                for key in ("task_id", "subtask_id", "attempt_id")
            )
        ]
        if len(grants) != 1 or not any(
            (call.get("caller_binding") or {}).get("grant_id") == grants[0]["grant_id"]
            for call in saved["calls"].values()
        ):
            raise PortfolioError(
                "original PR publication has no server-observed original task calls"
            )
        if published:
            verification = _pr_ci(request, candidate)
            if verification is None:
                return False
            success = verification["status"] == "checks_passed"
        elif (
            github(
                "GET",
                f"/repos/{request['repository']}/git/ref/heads/{quote(candidate['branch'], safe='/')}",
            )
            .get("object", {})
            .get("sha")
            != candidate["commit_sha"]
        ):
            raise PortfolioError("original PR candidate publication ref is not confirmed")
    elif published:
        raise PortfolioError("published original PR lost its native worker proof")
    pending = success and not published
    elapsed = max(
        saved.get("compute_seconds", 0),
        snapshot.get("phases", {}).get("execute", {}).get("compute_before", 0)
        + sum(job["compute_seconds"] for job in jobs.values()),
    )
    result = {
        "ok": success,
        "completed": not pending,
        "status": "waiting_original_ci" if pending else "completed" if success else "failed",
        "executor": REPAIR_KIND,
        "error": (
            ""
            if success
            else "original_pr_ci_failed" if published else "original_pr_worker_unfinished"
        ),
        **({"accepted": True, "worker_receipt_id": request_id} if pending else {}),
        **(
            {
                "artifact_id": f"github:{request['repository']}:{candidate['commit_sha']}",
                "artifact_sha256": candidate["archive_sha256"],
            }
            if success
            else {}
        ),
        "remote_receipt": {
            "schema": SCHEMA,
            "request_id": request_id,
            "run_id": run["id"],
            "source_sha": request["source_sha"],
            "controller_sha": request["controller_sha"],
            "source_run_id": request["source_run_id"],
            "source_run_attempt": request["source_run_attempt"],
            "candidate_sha256": digest(candidate),
            "stage": (
                "not_dispatched"
                if not_dispatched
                else "original_ci" if published else "publication" if success else "worker_failed"
            ),
            "verification": verification,
            "delivery": {"status": "not_verified"},
            "native_compute": {"jobs": jobs, "compute_seconds": elapsed},
        },
    }
    opportunity = next(
        item
        for item in portfolio["opportunities"]
        if item["opportunity_id"] == binding["opportunity_id"]
    )
    _finish(
        {**opportunity, **binding}, result, elapsed, remote_receipt=(request_id, digest(snapshot))
    )
    if not_dispatched:
        return bool(
            portfolio_status(binding["decision_id"], owner_user_id=binding["owner_user_id"])[
                "tasks"
            ][binding["opportunity_id"]]["status"]
            == "failed"
        )
    return remote.read_request(request_id)[2] in {"execution_completed", "failed"}


def _idle_phase(
    request_id: str,
    request: dict[str, Any],
    snapshot: dict[str, Any],
    run: dict[str, Any],
    jobs: dict[str, Any],
) -> bool:
    phase = snapshot.get("phase")
    name = "employee-workspace" if phase == "execute" else "resume-verification"
    if not phase or name not in jobs or (phase == "resume" and run.get("status") != "completed"):
        return False
    proof = jobs[name]
    receipt_id = f"github:{request['repository']}:run:{run['id']}:job:{proof['job_id']}"

    def apply(_row, _proposal, _state, saved, record, current, _session):
        if digest(current) != digest(snapshot) or saved["status"] not in {"running", "waiting"}:
            return False
        if any(call.get("status") != "settled" for call in saved["calls"].values()):
            return False
        if saved.get("worker_capacity") == {"state": "idle", "phase_receipt_id": receipt_id}:
            return False
        current.pop("model_grant", None)
        current["phases"][phase].pop("bootstrap_sha256", None)
        current["phases"][phase].update(status="closed", native_job=proof)
        for grant in current.get("task_grants", []):
            if grant["status"] == "active":
                grant["status"] = "closed"
        elapsed = current["phases"]["execute"]["compute_before"] + sum(
            job["compute_seconds"] for job in jobs.values()
        )
        saved.update(
            status="waiting",
            compute_seconds=max(saved.get("compute_seconds", 0), elapsed),
            worker_capacity={"state": "idle", "phase_receipt_id": receipt_id},
        )
        record.state = "waiting_phase"
        return True

    return bool(remote._mutate(request_id, apply))


def reconcile_request(request_id: str) -> bool:
    from modstore_server.strategic_portfolio_runtime import _finish

    request, snapshot, state = remote.read_request(request_id)
    if request["kind"] == "original_pr_repair":
        return _reconcile_pr(request_id, request, snapshot, state)
    if state in {"execution_completed", "failed"}:
        return False
    with remote.get_session_factory()() as session:
        row, _, effects = bridge.original(session, request)
        result = _terminal(request, _evidence(row))
    run_id = effects.get("run_id") or snapshot.get("run_id")
    jobs, idle = {}, False
    if effects.get("runner_intent") or run_id:
        if not run_id:
            return False  # Unknown original submission remains reserved.
        run = remote.native_run(request, run_id)
        jobs = _jobs(request, run_id)
        idle = _idle_phase(request_id, request, snapshot, run, jobs)
        if idle:
            request, snapshot, _ = remote.read_request(request_id)
        if run.get("status") != "completed":
            return idle
        if result and result["ok"] and run.get("conclusion") != "success":
            raise PortfolioError("successful original delivery lacks its native engineering run")
    if result is None:
        return idle
    binding = request["binding"]
    portfolio = portfolio_status(binding["decision_id"], owner_user_id=binding["owner_user_id"])
    saved = portfolio["tasks"][binding["opportunity_id"]]
    if result["ok"] and (not saved["calls"] or not snapshot.get("task_grants")):
        raise PortfolioError("engineering delivery has no server-observed original task calls")
    opportunity = next(
        item
        for item in portfolio["opportunities"]
        if item["opportunity_id"] == binding["opportunity_id"]
    )
    task = {
        **opportunity,
        **binding,
        "deadline": saved["deadline"],
        "started_at": saved["started_at"],
    }
    offset = snapshot.get("phases", {}).get("execute", {}).get("compute_before", 0)
    elapsed = max(
        saved.get("compute_seconds", 0),
        offset + sum(job["compute_seconds"] for job in jobs.values()),
    )
    result["remote_receipt"]["native_compute"] = {"jobs": jobs, "compute_seconds": elapsed}
    _finish(task, result, elapsed, remote_receipt=(request_id, digest(snapshot)))
    return idle or remote.read_request(request_id)[2] in {"execution_completed", "failed"}
