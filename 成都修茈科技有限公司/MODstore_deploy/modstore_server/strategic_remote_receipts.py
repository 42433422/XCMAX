"""Read immutable native GitHub artifacts before finishing a strategic report."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update

from modstore_server import strategic_remote_bridge as bridge
from modstore_server.db.mac_control import MacControlTask
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.strategic_portfolio import (
    PortfolioError,
    _date,
    digest,
    portfolio_status,
)

_READBACK_ERRORS = RECOVERABLE_ERRORS + (HTTPException,)


def _artifact(request: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.customer_ticket_github import github
    from modstore_server.retort_github_workspace import _download_artifact

    repo, run_id = request["repository"], snapshot["run_id"]
    response = github("GET", f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")
    rows = response.get("artifacts", [])
    if type(response.get("total_count")) is not int or response["total_count"] != len(rows):
        raise PortfolioError("remote artifact inventory is incomplete")
    name = "para-strategic-report-" + request["binding"]["receipt_id"]
    matches = [row for row in rows if row.get("name") == name and not row.get("expired")]
    if len(matches) != 1:
        raise PortfolioError("remote report artifact is missing or ambiguous")
    artifact = matches[0]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact.get("digest", ""))):
        raise PortfolioError("native remote artifact digest is missing")
    workflow = artifact.get("workflow_run") or {}
    if workflow.get("id") != run_id or workflow.get("head_sha") != request["source_sha"]:
        raise PortfolioError("remote artifact belongs to another controller execution")
    with TemporaryDirectory(prefix="strategy-report-") as temporary:
        root = Path(temporary)
        _download_artifact(repo, artifact["id"], root, artifact["digest"])
        if sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()) != [
            "execution.json",
            "report.md",
        ]:
            raise PortfolioError("remote report artifact has an unexpected file contract")
        if (root / "execution.json").stat().st_size > 16000 or (
            root / "report.md"
        ).stat().st_size > 500000:
            raise PortfolioError("remote report artifact exceeds the approved transport size")
        receipt = json.loads((root / "execution.json").read_text(encoding="utf-8"))
        data = (root / "report.md").read_bytes()
        if (
            receipt != snapshot.get("controller_receipt")
            or receipt.get("status") != "completed"
            or hashlib.sha256(data).hexdigest() != receipt.get("report_sha256")
            or not data.strip()
        ):
            raise PortfolioError(
                "remote report artifact differs from its original controller receipt"
            )
        report = data.decode("utf-8")
    return {
        "ok": True,
        "completed": True,
        "status": "completed",
        "executor": bridge.KIND,
        "output": report if len(data) <= 40000 else report[:8000],
        "output_truncated": len(data) > 40000,
        "report_bytes": len(data),
        "artifact_id": f"github:{repo}:artifact:{artifact['id']}:report.md",
        "artifact_sha256": receipt["report_sha256"],
        "artifact_url": f"https://github.com/{repo}/actions/runs/{run_id}/artifacts/{artifact['id']}",
        "remote_receipt": {
            **receipt,
            "archive_digest": artifact["digest"],
            "artifact_id": artifact["id"],
        },
    }


def reconcile_request(request_id: str) -> bool:
    from modstore_server.customer_ticket_github import github
    from modstore_server.para_github_repair import _find_run
    from modstore_server.strategic_portfolio_runtime import _finish

    request, snapshot, state = bridge.read_request(request_id)
    if request["kind"] == "github_opencode_workspace":
        from modstore_server.strategic_workspace_receipts import reconcile_request as workspace

        return workspace(request_id)
    if state in {"execution_completed", "failed"}:
        return False
    run_id = snapshot.get("run_id") or _find_run(
        github, request["repository"], "para-workspace-" + request_id
    )
    if run_id is None:
        return False  # Unknown dispatch is never reissued.
    run = bridge.native_run(request, run_id)
    if run.get("status") != "completed":
        return False
    result: dict[str, Any]
    if run.get("conclusion") != "success" or state != "reported":
        result = {
            "ok": False,
            "status": "failed",
            "error": "remote_worker_did_not_complete",
        }
    else:
        jobs = github(
            "GET",
            f"/repos/{request['repository']}/actions/runs/{run_id}/jobs?per_page=100",
        )
        matches = [job for job in jobs.get("jobs", []) if job.get("name") == "employee-workspace"]
        if (
            len(matches) != 1
            or matches[0].get("conclusion") != "success"
            or matches[0].get("run_id") != run_id
        ):
            raise PortfolioError("native report execution job is not successful")
        result = _artifact(request, snapshot)

    binding = request["binding"]

    portfolio = portfolio_status(binding["decision_id"], owner_user_id=binding["owner_user_id"])
    saved = portfolio["tasks"][binding["opportunity_id"]]
    if result.get("ok") is True and not saved["calls"]:
        raise PortfolioError("remote report has no server-observed model calls")
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
    completed = _date(
        snapshot.get("reported_at") or run.get("updated_at") or datetime.now(UTC).isoformat()
    )
    elapsed = max(1, math.ceil((completed - _date(task["started_at"])).total_seconds()))
    _finish(task, result, elapsed, remote_receipt=(request_id, digest(snapshot)))
    return True


def reconcile_portfolio(decision_id: str, *, owner_user_id: int | None = None) -> None:
    status = portfolio_status(decision_id, owner_user_id=owner_user_id)
    for saved in status.get("tasks", {}).values():
        binding = saved.get("worker_binding") or {}
        if binding.get("adapter") in {bridge.KIND, "github_opencode_workspace"} and saved[
            "status"
        ] in {
            "waiting",
            "running",
        }:
            reconcile_request(binding["receipt_id"])


def reconcile_pending_reports(*, limit: int = 10) -> dict[str, Any]:
    """Read back already-issued jobs even after their original mandate is stopped."""
    pending = {
        "dispatching",
        "requested",
        "unknown",
        "claimed",
        "reported",
        "bootstrapped",
        "waiting_phase",
    }
    with bridge.get_session_factory()() as session:
        ids = session.scalars(
            select(MacControlTask.id)
            .where(
                MacControlTask.actor.in_({bridge.ACTOR, "service:strategy-workspace"}),
                MacControlTask.state.in_(pending),
            )
            .order_by(MacControlTask.updated_at)
            .limit(max(1, min(limit, 100)))
        ).all()
    results = []
    for task_id in ids:
        request_id = str(uuid.UUID(hex=task_id))
        try:
            results.append({"request_id": request_id, "reconciled": reconcile_request(request_id)})
        except _READBACK_ERRORS as exc:
            results.append(
                {
                    "request_id": request_id,
                    "status": "pending_readback",
                    "reason": type(exc).__name__,
                }
            )
        finally:
            # Rotate live requests through the bounded read queue. Finished rows
            # are excluded, and neither this touch nor reconciliation can dispatch.
            with bridge.get_session_factory()() as session:
                session.execute(
                    update(MacControlTask)
                    .where(MacControlTask.id == task_id, MacControlTask.state.in_(pending))
                    .values(updated_at=time.time())
                )
                session.commit()
    return {"checked": len(ids), "results": results}
