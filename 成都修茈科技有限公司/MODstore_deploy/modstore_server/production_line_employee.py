"""Bind production dispatch to the existing brief queue, duty graph and effect records."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin, urlparse

import httpx
from cryptography.exceptions import InvalidSignature
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from modstore_server.customer_ticket_github import configuration, github
from modstore_server.models import (
    DutyGraphRun,
    DutyGraphRunNode,
    EmployeeChangeRequest,
    OpsActionAuditLog,
    PendingBriefTask,
    User,
    get_session_factory,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.production_line_sources import _require, _source_file, observe_source_step
from modstore_server.strategic_execution_receipts import evaluate_execution_receipt


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _claim(step: str, employee: str, task: str, context: dict) -> tuple[int, dict, bool]:
    from modstore_server.employee_orchestrator import _resolve_uid

    uid = _resolve_uid(int(context.get("created_by_user_id") or 0))
    _require(uid > 0, "production_actor_missing")
    payload = {
        key: value
        for key, value in context.items()
        if key
        not in {
            "step",
            "result",
            "context",
            "craft_results",
            "fhd_core",
            "pending_brief_task_id",
            "_production_read_only",
        }
    }
    payload["created_by_user_id"] = uid
    payload["production_step_id"] = step
    fingerprint = hashlib.sha256(
        _json(["production_line", employee, task, payload]).encode()
    ).hexdigest()
    with get_session_factory()() as db:
        actor = db.get(User, uid)
        _require(
            actor is not None
            and actor.is_admin
            and not actor.deleted_at
            and actor.account_state not in {"disabled", "deleted", "suspended", "blocked"},
            "production_admin_actor_required",
        )
        row = db.scalar(select(PendingBriefTask).where(PendingBriefTask.fingerprint == fingerprint))
        created = row is None
        if row is None:
            _require(
                not context.get("_production_read_only"), "approval_cannot_create_a_new_dispatch"
            )
            baseline = {
                "change_request_id": db.scalar(select(func.max(EmployeeChangeRequest.id))) or 0,
                "audit_id": db.scalar(select(func.max(OpsActionAuditLog.id))) or 0,
            }
            row = PendingBriefTask(
                owner_employee_id=employee,
                source_kind="production_line",
                source_ref=f"{step}:{context['source_sha']}",
                task_brief=task,
                payload_json=_json({"input": payload, "baseline": baseline}),
                fingerprint=fingerprint,
                status="running",
                dispatched_at=datetime.now(UTC),
            )
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = db.scalar(
                    select(PendingBriefTask).where(PendingBriefTask.fingerprint == fingerprint)
                )
                created = False
        _require(
            row is not None
            and row.source_kind == "production_line"
            and row.owner_employee_id == employee
            and row.task_brief == task,
            "production_dispatch_binding_mismatch",
        )
        assert row is not None
        stored = json.loads(str(row.payload_json))
        _require(stored["input"] == payload, "production_input_changed")
        task_id = int(cast(Any, row).id)
        return task_id, {**payload, "pending_brief_task_id": task_id}, created


def _graph(db, queue, expected):
    query = select(DutyGraphRun).where(
        DutyGraphRun.created_by_user_id == expected["created_by_user_id"],
        DutyGraphRun.target_employee_id == queue.owner_employee_id,
        DutyGraphRun.task == queue.task_brief,
        DutyGraphRun.created_at >= queue.created_at,
    )
    if queue.dispatched_run_id:
        query = query.where(DutyGraphRun.id == int(queue.dispatched_run_id))
    candidates = db.scalars(query.order_by(DutyGraphRun.id.desc()).limit(1001)).all()
    _require(len(candidates) <= 1000, "production_graph_recovery_incomplete")
    matches = [row for row in candidates if json.loads(row.input_data_json) == expected]
    _require(len(matches) == 1, "original_duty_graph_missing_or_ambiguous")
    run = matches[0]
    _require(run.status not in {"failed", "cancelled", "blocked"}, "original_duty_graph_failed")
    nodes = db.scalars(select(DutyGraphRunNode).where(DutyGraphRunNode.run_id == run.id)).all()
    _require(
        run.status == "completed"
        and run.completed_at is not None
        and run.total_nodes == len(nodes)
        and run.success_count == len(nodes)
        and run.failed_count == run.skipped_count == 0
        and nodes,
        "original_duty_graph_not_completed",
    )
    _require(
        any(node.employee_id == queue.owner_employee_id for node in nodes),
        "original_target_node_missing",
    )
    for node in nodes:
        _require(
            node.status == "success" and node.completed_at is not None and not node.error,
            "original_node_not_completed",
        )
        result = json.loads(node.result_json)
        receipt = evaluate_execution_receipt(result)
        _require(receipt.status == "completed", receipt.reason)
        inner = result.get("result", result)
        _require(
            isinstance(inner, dict) and isinstance(inner.get("outputs"), list),
            "native_verified_node_outputs_required",
        )
    return run, nodes


def _change_artifacts(db, run, nodes, baseline, context):
    from modstore_server.employee_change_request_verification import _guard_under_workspace
    from modstore_server.integrations.ops_action_handlers import repo_root

    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    ).resolve()
    repo = configuration()["repository"]
    artifacts = []
    for node in nodes:
        result = json.loads(node.result_json)
        for output in result.get("result", result)["outputs"]:
            for cid in output.get("change_request_ids") or []:
                _require(
                    type(cid) is int and cid > baseline["change_request_id"],
                    "change_request_not_created_by_execution",
                )
                row = db.get(EmployeeChangeRequest, cid)
                _require(
                    row is not None
                    and row.source_employee_id == node.employee_id
                    and row.created_at >= run.created_at
                    and row.status not in {"failed", "rejected", "cancelled"}
                    and not row.error
                    and row.base_commit_sha == context["source_sha"]
                    and re.fullmatch(r"[0-9a-f]{40}", row.staged_commit_sha or ""),
                    "original_change_request_identity_mismatch",
                )
                change = json.loads(row.diff_blob)
                _require(
                    _json(change.get("source_execution"))
                    == _json(
                        {
                            "duty_graph_run_id": int(run.id),
                            "duty_graph_node_id": int(node.id),
                            "employee_id": node.employee_id,
                            "user_id": int(run.created_by_user_id),
                        }
                    ),
                    "change_request_execution_mismatch",
                )
                path = _guard_under_workspace(
                    row.workspace_root_hint, str(change.get("path") or "")
                )
                _require(
                    path and Path(path).is_relative_to(root), "change_artifact_outside_repository"
                )
                relative = Path(path).relative_to(root).as_posix()
                _require(
                    json.loads(row.target_paths_json) == [change.get("path")],
                    "change_target_mismatch",
                )
                content = str(change.get("content") or "").encode()
                staged = subprocess.run(
                    ["git", "show", f"{row.staged_commit_sha}:{relative}"],
                    cwd=root,
                    capture_output=True,
                    timeout=10,
                    check=True,
                ).stdout
                _require(staged == content, "original_staged_artifact_changed")
                parents = subprocess.run(
                    ["git", "rev-list", "--parents", "-n", "1", row.staged_commit_sha],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                ).stdout.split()
                _require(
                    parents == [row.staged_commit_sha, context["source_sha"]],
                    "staged_change_source_parent_mismatch",
                )
                pulls = github("GET", f"/repos/{repo}/commits/{row.staged_commit_sha}/pulls")
                matches = [
                    pr
                    for pr in pulls
                    if pr.get("merged_at")
                    and (pr.get("head") or {}).get("sha") == row.staged_commit_sha
                    and (pr.get("head") or {}).get("ref") == row.git_branch
                    and ((pr.get("head") or {}).get("repo") or {}).get("full_name") == repo
                    and (pr.get("base") or {}).get("ref") == "main"
                    and ((pr.get("base") or {}).get("repo") or {}).get("full_name") == repo
                    and re.fullmatch(r"[0-9a-f]{40}", str(pr.get("merge_commit_sha") or ""))
                ]
                _require(len(matches) == 1, "original_change_not_merged_to_main")
                pr = matches[0]
                artifacts.append(
                    {
                        "change_request_id": cid,
                        "path": relative,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "merge_sha": pr["merge_commit_sha"],
                        "pull_number": pr["number"],
                        "merged_at": pr["merged_at"],
                    }
                )
    _require(artifacts, "original_change_artifacts_missing")
    target = max(artifacts, key=lambda row: row["merged_at"])["merge_sha"]
    for artifact in artifacts:
        actual, blob = _source_file(repo, target, artifact["path"])
        _require(
            hashlib.sha256(actual).hexdigest() == artifact["sha256"],
            "merged_change_artifact_mismatch",
        )
        artifact["source_blob"] = blob
    return {"source_sha": target, "artifacts": artifacts, "publication_verified": False}


def _audit_effects(db, run, nodes, baseline):
    audits = []
    for node in nodes:
        result = json.loads(node.result_json)
        for output in result.get("result", result)["outputs"]:
            aid = output.get("audit_log_id")
            if aid is None:
                continue
            _require(
                type(aid) is int and aid > baseline["audit_id"],
                "operation_audit_not_created_by_execution",
            )
            row = db.get(OpsActionAuditLog, aid)
            _require(
                row is not None
                and row.employee_id == node.employee_id
                and row.user_id == run.created_by_user_id
                and row.created_at >= run.created_at
                and row.command_id == output.get("command_id")
                and row.handler == output.get("handler")
                and row.exit_code == 0
                and not row.error
                and row.dry_run is False
                and row.approval_required is False,
                "original_operation_not_verified",
            )
            audits.append(
                {
                    "audit_log_id": aid,
                    "command_id": row.command_id,
                    "stdout_sha256": hashlib.sha256(
                        (row.stdout_excerpt or "").encode()
                    ).hexdigest(),
                }
            )
    _require(audits, "original_operation_audit_missing")
    return audits


def _deployment(context):
    from modstore_server.integrations.ops_action_handlers import repo_root
    from modstore_server.self_maintenance_deploy_receipts import (
        correlated_verified_deploys,
        verify_deployed_identity,
    )
    from modstore_server.self_maintenance_gh_gateway import GhActionsDeploymentGateway

    gateway = GhActionsDeploymentGateway(
        repo_root=repo_root(),
        repository=configuration()["repository"],
        ref="main",
        workflow="fhd-deploy.yml",
    )
    sha = context["source_sha"]
    run_id = str(context.get("self_maintenance_run_id") or "")
    if not run_id:
        # Daily production already freezes the exact source. Resolve its one original
        # release action instead of requiring the caller to invent a second run id.
        originals = {
            str(row.get("run_id") or "")
            for row in correlated_verified_deploys(gateway._ledger_rows())
            if row.get("merge_sha") == sha
            and row.get("environment") == "production"
            and row.get("action_id") == f"release:{sha}"
        }
        _require(
            len(originals) == 1 and "" not in originals,
            "original_deployment_run_missing_or_ambiguous",
        )
        run_id = originals.pop()
    _require(run_id, "original_deployment_run_required")
    recorded = gateway.recover_verified_deployment(
        run_id=run_id, merge_sha=sha, environment="production", action_id=f"release:{sha}"
    )
    _require(recorded is not None, "original_verified_deployment_missing")
    identity = verify_deployed_identity(
        merge_sha=sha,
        release=gateway.fetch_release_identity("production"),
        health=gateway.fetch_health_identity("production"),
    )
    _require(
        recorded.get("artifact_sha256") == identity.get("artifact_sha256")
        and recorded.get("image_digest", "") == identity.get("image_digest", ""),
        "running_release_differs_from_original_deployment",
    )
    return {
        **identity,
        "deployment_run_id": run_id,
        "workflow_run_id": recorded["workflow_run_id"],
        "publication_verified": True,
    }


def _updates(context):
    from modstore_server import customer_issue_release_provenance as provenance

    releases = []
    for url in provenance._FEEDS:
        # Deliberately read the active feed; historical cached releases are not current publication.
        release = provenance._signed_release(
            provenance._fetch_text(url), context["source_sha"], url
        )
        _require(release is not None, "current_signed_update_feed_missing")
        for artifact in release["artifacts"]:
            address = urljoin(url, artifact["file"])
            parsed = urlparse(address)
            _require(
                parsed.scheme == "https"
                and parsed.netloc == urlparse(url).netloc
                and not parsed.username
                and not parsed.password
                and 0 < artifact["size"] <= 1024**3,
                "signed_update_artifact_origin_or_size_invalid",
            )
            digest, size = hashlib.sha512(), 0
            with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                with client.stream("GET", address) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        _require(size <= artifact["size"], "published_update_size_mismatch")
                        digest.update(chunk)
            _require(
                size == artifact["size"]
                and base64.b64encode(digest.digest()).decode() == artifact["sha512"],
                "published_update_digest_mismatch",
            )
            artifact["verified_url"] = address
        releases.append(release)
    _require(len({row["version"] for row in releases}) == 1, "published_platform_versions_disagree")
    return {
        "source_sha": context["source_sha"],
        "signed_feeds": releases,
        "publication_verified": True,
        "customer_installation_verified": False,
    }


def observe_published_step(step: str, context: dict) -> dict:
    """Existing publishers may finish after a dispatch has paused; observe before retrying."""
    from modstore_server.production_line_sources import _scope

    try:
        _scope(context)
        effect = _deployment(context) if step == "P5" else _updates(context)
        return {
            "step": step,
            "result": {
                "ok": True,
                "status": "completed",
                "evidence": {"source": "original_release_publisher", **effect},
            },
        }
    except RECOVERABLE_ERRORS + (HTTPException, InvalidSignature) as exc:
        return {
            "step": step,
            "result": {
                "ok": False,
                "status": "waiting_evidence",
                "reason": str(getattr(exc, "detail", None) or exc),
            },
        }


def _readback(queue_id, expected, step):
    with get_session_factory()() as db:
        queue = db.get(PendingBriefTask, queue_id)
        stored = json.loads(queue.payload_json)
        run, nodes = _graph(db, queue, expected)
        baseline = stored["baseline"]
        if step in {"P1", "P2"}:
            effect = _change_artifacts(db, run, nodes, baseline, expected)
        elif step == "P3":
            result = observe_source_step("P3", expected)["result"]
            _require(result["status"] == "completed", result.get("reason", "source_ci_pending"))
            effect = result["evidence"]
        elif step == "P5":
            effect = _deployment(expected)
        elif step == "P6":
            effect = _updates(expected)
        elif step == "P7":
            audits = _audit_effects(db, run, nodes, baseline)
            _require(
                any(
                    row["command_id"]
                    in {
                        "read-pytest-lastfailed",
                        "coverage-report",
                        "grep-cursor-logs",
                        "tail-nginx-error-log",
                    }
                    for row in audits
                ),
                "original_monitoring_observation_missing",
            )
            effect = {"source_sha": expected["source_sha"], "operation_audits": audits}
        elif step == "P8":
            from modstore_server.production_line_sources import _ci, _job, _scope

            effect = _change_artifacts(db, run, nodes, baseline, expected)
            target = {**expected, "source_sha": effect["source_sha"]}
            target.pop("ci_run_id", None)
            repo, sha = _scope(target)
            ci, jobs = _ci(repo, sha, target)
            effect["security_job_ids"] = [
                _job(jobs, name)["id"] for name in ("security-scan", "container-scan")
            ]
            effect["ci_run_id"] = ci["id"]
        else:
            raise ValueError("production_effect_observer_not_registered")
        evidence = {
            "source": "original_duty_graph_and_effect",
            "pending_brief_task_id": queue_id,
            "duty_graph_run_id": run.id,
            "node_ids": [node.id for node in nodes],
            **effect,
        }
        queue.dispatched_run_id = str(run.id)
        queue.status = "done"
        queue.completed_at = datetime.now(UTC)
        queue.dispatched_result_json = _json(evidence)
        db.commit()
    return {
        "step": step,
        "source_sha": effect.get("source_sha", expected["source_sha"]),
        "ci_run_id": (
            effect.get("ci_run_id")
            if effect.get("source_sha") != expected["source_sha"]
            else expected.get("ci_run_id")
        ),
        "result": {"ok": True, "status": "completed", "evidence": evidence},
    }


def dispatch_employee_step(step: str, employee: str, task: str, context: dict) -> dict:
    queue_id = None
    try:
        _require(
            re.fullmatch(r"[0-9a-f]{40}", str(context.get("source_sha") or "")),
            "exact_source_sha_required",
        )
        queue_id, expected, created = _claim(step, employee, task, context)
        if created:
            from modstore_server.employee_orchestrator import plan_and_dispatch

            result = plan_and_dispatch(
                task,
                expected,
                target_employee_id=employee,
                created_by_user_id=expected["created_by_user_id"],
                include_dependencies=True,
            )
            # A native run id is only a locator. The fresh graph and its actual effect decide completion.
            run_id = result.get("id") if isinstance(result, dict) else None
            if type(run_id) is int and run_id > 0:
                with get_session_factory()() as db:
                    row = db.get(PendingBriefTask, queue_id)
                    assert row is not None
                    cast(Any, row).dispatched_run_id = str(run_id)
                    db.commit()
        return cast(dict[str, Any], _readback(queue_id, expected, step))
    except RECOVERABLE_ERRORS + (HTTPException, InvalidSignature) as exc:
        return {
            "step": step,
            "result": {
                "ok": False,
                "status": (
                    "failed" if str(exc) == "original_duty_graph_failed" else "waiting_evidence"
                ),
                "reason": str(getattr(exc, "detail", None) or exc),
                "pending_brief_task_id": queue_id,
            },
        }
