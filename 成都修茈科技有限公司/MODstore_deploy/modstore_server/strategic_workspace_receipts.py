"""Finish budgets from original Retort delivery or original-PR repair CI receipts."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

from modstore_server import strategic_remote_bridge as remote
from modstore_server import strategic_workspace_bridge as bridge
from modstore_server.strategic_portfolio import PortfolioError, _date, digest, portfolio_status


def _evidence(row: Any) -> dict[str, Any]:
    from modstore_server.db.mac_control import MacControlTask

    if isinstance(row, MacControlTask):
        snapshot = json.loads(row.snapshot_json)
        return {
            "status": row.state,
            "snapshot": snapshot,
            "effects": snapshot,
            "control_task_id": row.id,
            "request": json.loads(row.request_json),
        }
    return {
        "status": row.status,
        "snapshot": json.loads(row.snapshot_json),
        "effects": json.loads(row.effects_json),
        "event_id": row.event_id,
    }


def _terminal(request: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any] | None:
    if request.get("original_request_kind") == "original_pr_repair":
        from modstore_server.para_github_repair import budget_terminal

        return budget_terminal(request, evidence)
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
    if not isinstance(rows, list) or response.get("total_count") != len(rows):
        raise PortfolioError("workspace native job inventory is incomplete")
    found = {}
    for row in rows:
        name = row.get("name")
        if name not in {
            "employee-workspace",
            "publish-candidate",
            "resume-verification",
            "independent-verification",
        }:
            continue
        if name in found or row.get("run_id") != run_id:
            raise PortfolioError("workspace native compute job identity is ambiguous")
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
        }
    return found


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
