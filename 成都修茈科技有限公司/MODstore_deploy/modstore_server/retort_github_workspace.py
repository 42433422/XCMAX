"""Adapt Retort work to the existing GitHub-hosted Para employee workspace."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

import httpx
from fastapi import HTTPException

from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.customer_ticket_github import github
from modstore_server.models import (
    IncidentEvent,
    RetortEvolutionRun,
    get_session_factory,
)
from modstore_server.para_execution_isolation import (
    HEADER_ONLY_PLATFORM_PROFILE,
    feedback_allocation_isolated,
    feedback_execution_kind,
    feedback_executor_configured,
)
from modstore_server.para_github_runner import (
    WORKFLOW,
    api_base,
    auth_headers,
    device_matches,
)
from modstore_server.retort_customer_feedback import CREDENTIAL_BLOCK


def _load(request_id):
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        if row is None:
            raise ValueError("Retort 派工记录不存在")
        return json_loads(row.protocol_json, {}), json_loads(row.effects_json, {})


def _save(request_id, **updates):
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        effects = {**json_loads(row.effects_json, {}), **updates}
        row.effects_json = json_dumps(effects)
        db.commit()
    return effects


def begin_dispatch(request_id, state):
    protocol, effects = _load(request_id)
    if "plan" not in effects:
        effects = _save(
            request_id,
            plan=state["plan"],
            optimization=state["optimization"],
            authorization=state["approval"],
        )
    if feedback_execution_kind(effects) and not feedback_executor_configured():
        return {"status": "blocked", "reason": CREDENTIAL_BLOCK}
    _ensure_issue(request_id, protocol, effects)
    return {"request_id": request_id, "executor": "github_para", "status": "requested"}


def public_task_body(effects):
    body = effects["plan"]["public_body"]
    proposal = effects.get("optimization", {})
    if proposal.get("status") == "proposed":
        body += "\n\n经独立试验选出的辅助方案：\n" + str(
            proposal.get("candidate", {}).get("plan", "")
        )
    return body


def _ensure_issue(request_id, protocol, effects):
    marker = f"<!-- retort:{request_id}:{protocol['protocol_digest']} -->"
    repo = protocol["repository"]
    if effects.get("issue_number"):
        return effects
    if effects.get("issue_intent"):
        matches = []
        for page in range(1, 4):
            rows = github("GET", f"/repos/{repo}/issues?state=all&per_page=100&page={page}")
            matches.extend(
                r for r in rows if marker in str(r.get("body") or "") and not r.get("pull_request")
            )
            if len(rows) < 100:
                break
        if len(matches) == 1:
            return _save(request_id, issue_number=matches[0]["number"])
        return effects  # Unknown outcome never creates a second issue.
    _save(request_id, issue_intent=True)
    plan = effects["plan"]
    issue = github(
        "POST",
        f"/repos/{repo}/issues",
        {
            "title": plan["public_title"],
            "body": public_task_body(effects) + "\n\n" + marker,
        },
    )
    return _save(request_id, issue_number=issue["number"])


def _ensure_runner(request_id, protocol, effects):
    repo = protocol["repository"]
    from modstore_server import strategic_workspace_bridge as strategic

    budgeted = strategic.attached(request_id)
    if not effects.get("run_id"):
        if (feedback_execution_kind(effects) or budgeted) and not strategic.ready(request_id):
            return {
                **effects,
                "model_allocation": {
                    "status": "waiting",
                    "reason": "strategic_company_budget_binding_required",
                },
            }
        if not effects.get("runner_intent"):
            from modstore_server.para_github_runner import _claim_worker_slot
            from modstore_server.para_model_admission import platform_model_admission

            allocation = platform_model_admission("benchmark")
            if feedback_execution_kind(effects) or budgeted:
                if not feedback_executor_configured() or not allocation:
                    return {
                        **effects,
                        "model_allocation": {"status": "waiting", "reason": CREDENTIAL_BLOCK},
                    }
                allocation = {**allocation, "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE}
            if allocation and allocation["status"] != "admitted":
                return {**effects, "model_allocation": allocation}
            if budgeted:
                request, _, _ = strategic.remote.read_request(request_id)
                strategic.verify_allocation(request, {"model_allocation": allocation})
            with get_session_factory()() as db:
                row = db.get(RetortEvolutionRun, request_id)
                if not _claim_worker_slot(db, row, owner_key=f"retort:{request_id}"):
                    return effects
            _save(request_id, runner_intent=True, model_allocation=allocation)
            github(
                "POST",
                f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
                {"ref": "main", "inputs": {"request_id": request_id}},
            )
        matches = []
        for page in range(1, 4):
            rows = github(
                "GET",
                f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=100&page={page}",
            ).get("workflow_runs", [])
            matches.extend(
                r for r in rows if r.get("display_title") == f"para-workspace-{request_id}"
            )
            if len(rows) < 100:
                break
        if len(matches) != 1:
            return effects
        effects = _save(request_id, run_id=matches[0]["id"])
    run = github("GET", f"/repos/{repo}/actions/runs/{effects['run_id']}")
    if (
        run.get("head_branch") != "main"
        or run.get("head_sha") != protocol["source_sha"]
        or run.get("run_attempt") != 1
        or run.get("path") != f".github/workflows/{WORKFLOW}"
    ):
        raise ValueError("GitHub 执行版本已变化或运行身份不匹配，请重新冻结任务")
    return {**effects, "worker": run}


def collect_execution(request_id):
    protocol, effects = _load(request_id)
    customer_feedback = feedback_execution_kind(effects)
    blocked = {"status": "blocked", "reason": CREDENTIAL_BLOCK}
    # Retain historical readback, but never create an issue, runner, or model task
    # from a customer-controlled reproduction while credentials remain exportable.
    if (
        customer_feedback
        and not feedback_executor_configured()
        and (not effects.get("issue_number") or not effects.get("run_id"))
    ):
        return blocked
    effects = _ensure_issue(request_id, protocol, effects)
    if not effects.get("issue_number"):
        return {"status": "unknown", "reason": "issue_response_unconfirmed"}
    try:
        effects = _ensure_runner(request_id, protocol, effects)
    except ValueError:
        return {"status": "failed", "reason": "frozen_source_changed"}
    run = effects.get("worker", {})
    if not run:
        allocation = effects.get("model_allocation") or {}
        return {
            "status": "waiting",
            "reason": allocation.get("reason", "runner_response_unconfirmed"),
        }
    if run.get("status") == "completed":
        if run.get("conclusion") != "success":
            result = {
                "status": "failed",
                "reason": "github_run_failed",
                "run_id": run["id"],
            }
            if run.get("conclusion") == "failure":
                report = archive_failed_verification(request_id, protocol, effects, run)
                if report:
                    result["target_sha"] = report["target_sha"]
                    result["failed_verification_sha256"] = report["evidence_digest"]
            return result
        state = worker_status(request_id)
        if not state["finished"] or state["conclusion"] != "success" or not state.get("target_sha"):
            return {"status": "failed", "reason": "employee_receipt_incomplete"}
        pulls = github(
            "GET",
            f"/repos/{protocol['repository']}/commits/{state['target_sha']}/pulls",
        )
        issue_number = effects["issue_number"]
        issue_url = f"https://github.com/{protocol['repository']}/issues/{issue_number}"
        matching = [
            p
            for p in pulls
            if p.get("head", {}).get("sha") == state["target_sha"]
            and p.get("base", {}).get("ref") == "main"
            and p.get("base", {}).get("repo", {}).get("full_name") == protocol["repository"]
            and (
                re.search(rf"(?<!\w)#{issue_number}\b", str(p.get("body") or ""))
                or issue_url in str(p.get("body") or "")
            )
        ]
        if len(matching) != 1:
            if customer_feedback:
                return blocked
            return {
                "status": "waiting",
                "reason": "awaiting_pull_request",
                "run_id": str(run["id"]),
            }
        _save(request_id, pull_request_number=matching[0]["number"])
        return {
            "status": "completed",
            "run_id": str(run["id"]),
            "target_sha": state["target_sha"],
            "issue_number": effects["issue_number"],
            "url": run["html_url"],
            "pull_request_number": matching[0]["number"],
        }
    if customer_feedback:
        from modstore_server.strategic_workspace_bridge import ready

        if not feedback_allocation_isolated(effects.get("model_allocation")) or not ready(
            request_id
        ):
            return blocked
    workspace = {
        "request_id": request_id,
        "run_id": run["id"],
        "repository": protocol["repository"],
        "issue_number": effects["issue_number"],
        "retort_run_id": request_id,
        "source_sha": protocol["source_sha"],
        "issue_url": f"https://github.com/{protocol['repository']}/issues/{effects['issue_number']}",
        "public_title": effects["plan"]["public_title"],
        "public_summary": public_task_body(effects),
    }
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        response = client.get(api_base() + "/api/devices", headers=auth_headers())
        response.raise_for_status()
        if not any(
            device_matches(device, workspace) for device in response.json().get("devices", [])
        ):
            return {"status": "waiting", "reason": "waiting_cloud_device"}
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        if row.event_id is None:
            event = IncidentEvent(
                event_type="ops.retort.evolution",
                source="retort",
                fingerprint=f"retort:{request_id}",
                payload_json=json_dumps(
                    {
                        "retort_run_id": request_id,
                        "github_workspace": workspace,
                        "user_id": row.user_id,
                        "scope": "shared_core",
                        "title": protocol["title"],
                        "summary": protocol["goal"],
                        "issue_domain": protocol["criteria"][0]["domain_id"],
                    }
                ),
            )
            db.add(event)
            db.flush()
            row.event_id = event.id
            db.commit()
        event_id = row.event_id
    from modstore_server.incident_team_dispatch import dispatch_incident_team

    dispatch_incident_team(event_id)
    return {"status": "waiting", "run_id": str(run["id"]), "event_id": event_id}


def authorized_incident(db, payload, event_id, *, read_only=False):
    workspace = payload.get("github_workspace") or {}
    request_id = workspace.get("retort_run_id")
    row = db.get(RetortEvolutionRun, request_id) if request_id else None
    statuses = (
        {"waiting_execution", "waiting_credential_isolation"}
        if read_only
        else {"waiting_execution"}
    )
    if row is None or row.event_id != event_id or row.status not in statuses:
        return False
    protocol, effects = (
        json_loads(row.protocol_json, {}),
        json_loads(row.effects_json, {}),
    )
    if (
        feedback_execution_kind(effects)
        and not read_only
        and not feedback_allocation_isolated(effects.get("model_allocation"))
    ):
        return False
    return bool(
        effects.get("authorization", {}).get("approved") is True
        and payload.get("retort_run_id") == row.id
        and payload.get("user_id") == row.user_id
        and workspace.get("request_id") == row.id
        and workspace.get("repository") == protocol["repository"]
        and workspace.get("source_sha") == protocol["source_sha"]
        and workspace.get("run_id") == effects.get("run_id")
        and workspace.get("issue_number") == effects.get("issue_number")
    )


def worker_status(request_id):
    from modstore_server.para_github_publication import publication_candidate

    protocol, effects = _load(request_id)
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        event = db.get(IncidentEvent, row.event_id) if row.event_id else None
        claim = json_loads(event.payload_json, {}).get("_team_claim", {}) if event else {}
        cancelled = row.status == "cancelled"
        candidate = publication_candidate(db, event)
    team = claim.get("team", [])
    failed = any(
        r.get("status") in {"failed", "cancelled", "manual_review", "rejected"} for r in team
    )
    commits = {
        out["commit_sha"]
        for member in team
        if member.get("role") == "fix" and member.get("ok")
        for out in (member.get("handler_outputs") or {}).get("outputs", [])
        if out.get("commit_sha")
    }
    target = next(iter(commits)) if len(commits) == 1 else ""
    if target and not re.fullmatch(r"[0-9a-f]{40}", target):
        raise ValueError("员工代码回执缺少确切提交")
    from modstore_server.strategic_workspace_bridge import descriptor

    return {
        **({"kind": feedback_execution_kind(effects)} if feedback_execution_kind(effects) else {}),
        "strategic_budget": descriptor(request_id),
        "request_id": request_id,
        "run_id": effects.get("run_id"),
        "repository": protocol["repository"],
        "issue_number": effects.get("issue_number"),
        "finished": bool(claim.get("ok") or failed or cancelled),
        "conclusion": (
            "success"
            if claim.get("ok") and not cancelled and not failed
            else "failure" if failed or cancelled else "unknown"
        ),
        "target_sha": target,
        "benchmark_protocol": protocol,
        "publication_candidate": candidate,
        "model_allocation": effects.get("model_allocation"),
    }


def slot_finished(request_id):
    protocol, effects = _load(request_id)
    return bool(
        effects.get("run_id")
        and github("GET", f"/repos/{protocol['repository']}/actions/runs/{effects['run_id']}").get(
            "status"
        )
        == "completed"
    )


def archive_failed_verification(request_id, protocol, effects, run):
    """Retain an already-produced failed comparison, with no acceptance authority."""
    from modstore_server.integrations.repository_packages import load_repository_module

    if (
        run.get("status") != "completed"
        or run.get("conclusion") != "failure"
        or run.get("id") != effects.get("run_id")
        or run.get("run_attempt") != 1
        or run.get("head_sha") != protocol["source_sha"]
        or run.get("path") != f".github/workflows/{WORKFLOW}"
    ):
        return None
    previous = effects.get("failed_verification")
    if previous and previous.get("run_id") == str(run["id"]):
        return previous
    try:
        worker = worker_status(request_id)
        target = worker.get("target_sha")
        if (
            worker.get("finished") is not True
            or worker.get("conclusion") != "success"
            or not isinstance(target, str)
            or not re.fullmatch(r"[0-9a-f]{40}", target)
            or worker.get("request_id") != request_id
            or worker.get("run_id") != run["id"]
        ):
            return None
        repo = protocol["repository"]
        artifacts = github("GET", f"/repos/{repo}/actions/runs/{run['id']}/artifacts").get(
            "artifacts", []
        )
        matches = [
            a
            for a in artifacts
            if a.get("name") == f"retort-verification-{request_id}" and not a.get("expired")
        ]
        if len(matches) != 1:
            return None
        artifact = matches[0]
        with tempfile.TemporaryDirectory(prefix="retort-failed-evidence-") as directory:
            root = Path(directory)
            _download_artifact(repo, artifact["id"], root, artifact.get("digest", ""))
            bundle = json.loads((root / "verification.json").read_text())
            contract = load_repository_module("retort_engine.evolution_contract")
            report = contract.inspect_bundle(
                protocol, bundle, root, run_id=str(run["id"]), target_sha=target
            )
            report["evidence_archive"] = _retain_artifact(request_id, artifact["digest"], root)
        # A failed workflow never becomes an accepted verification, even if
        # all recorded checks returned zero. Keep the report on a separate key.
        report.update(
            status="workflow_failed",
            artifact_id=artifact["id"],
            artifact_digest=artifact["digest"],
            workflow_conclusion="failure",
        )
    except (HTTPException, httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile):
        # Evidence may be absent when a workflow fails before the comparison.
        # Preserve the failure; absence of evidence is not a verified result.
        return None
    _save(request_id, failed_verification=report)
    return report


def verify_execution(request_id, state):
    from modstore_server.integrations.repository_packages import load_repository_module

    contract = load_repository_module("retort_engine.evolution_contract")
    protocol, execution = state["protocol"], state["execution"]
    repo, run_id = protocol["repository"], execution["run_id"]
    run = github("GET", f"/repos/{repo}/actions/runs/{run_id}")
    if (
        run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("run_attempt") != 1
    ):
        raise ValueError("独立验证工作流尚未成功结束")
    artifacts = github("GET", f"/repos/{repo}/actions/runs/{run_id}/artifacts").get("artifacts", [])
    matches = [
        a
        for a in artifacts
        if a.get("name") == f"retort-verification-{request_id}" and not a.get("expired")
    ]
    if len(matches) != 1:
        raise ValueError("缺少唯一的独立验证证据包")
    with tempfile.TemporaryDirectory(prefix="retort-verification-") as directory:
        root = Path(directory)
        _download_artifact(repo, matches[0]["id"], root, matches[0].get("digest", ""))
        bundle = json.loads((root / "verification.json").read_text())
        try:
            result = contract.verify_bundle(
                protocol,
                bundle,
                root,
                run_id=str(run_id),
                target_sha=execution["target_sha"],
            )
        except ValueError as exc:
            return {
                "status": "failed",
                "reason": str(exc),
                "score": None,
                "domain_status": "UNRATED",
            }
        result["evidence_archive"] = _retain_artifact(request_id, matches[0]["digest"], root)
    result.update(
        artifact_id=matches[0]["id"],
        artifact_digest=matches[0].get("digest"),
        url=run["html_url"],
        pull_request_number=execution["pull_request_number"],
    )
    _save(request_id, verification=result)
    return result


def _retain_artifact(request_id, artifact_digest, root):
    from uuid import UUID

    from modstore_server.infrastructure.private_asset_storage import (
        require_private_directory,
    )
    from modstore_server.integrations.repository_packages import load_repository_module

    runtime = os.environ.get("MODSTORE_RUNTIME_DIR", "")
    if not runtime:
        raise ValueError("请先配置持久证据存储，验收记录不能只依赖临时工作流文件")
    archive = f"retort-evidence/{UUID(request_id)}/{artifact_digest.removeprefix('sha256:')}.json"
    target = require_private_directory(Path(runtime) / archive)
    private = load_repository_module("retort_engine.secure_artifacts")
    payload = {
        "artifact_digest": artifact_digest,
        "files": {
            path.relative_to(root).as_posix(): base64.b64encode(path.read_bytes()).decode()
            for path in root.rglob("*")
            if path.is_file()
        },
    }
    private.write_private_json(target, payload)
    if private.read_private_json(target, allow_legacy=False) != payload:
        raise ValueError("持久证据写入未确认")
    return archive


def _download_artifact(repo, artifact_id, root, expected_digest):
    # GitHub returns a signed storage URL. Never forward its API credential to storage.
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        response = client.get(
            f"https://api.github.com/repos/{repo}/actions/artifacts/{int(artifact_id)}/zip",
            headers={"Authorization": "Bearer " + os.environ.get("MODSTORE_GITHUB_TOKEN", "")},
        )
        if response.status_code != 302:
            response.raise_for_status()
        if response.status_code == 302:
            from urllib.parse import urlparse

            url = response.headers["location"]
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or not parsed.hostname
                or not (
                    parsed.hostname.endswith(".blob.core.windows.net")
                    or parsed.hostname.endswith(".githubusercontent.com")
                )
            ):
                raise ValueError("不受信任的 GitHub 证据下载地址")
            data = bytearray()
            with client.stream("GET", url) as download:
                download.raise_for_status()
                for chunk in download.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 32 * 1024 * 1024:
                        raise ValueError("证据包超出大小限制")
        else:
            data = response.content
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("证据包超出大小限制")
        if expected_digest != "sha256:" + hashlib.sha256(data).hexdigest():
            raise ValueError("GitHub 证据包摘要不匹配")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 64 * 1024 * 1024:
                raise ValueError("证据包展开超出大小限制")
            seen = set()
            for item in archive.infolist():
                path = root / item.filename
                if (
                    not path.resolve().is_relative_to(root.resolve())
                    or item.filename in seen
                    or "\\" in item.filename
                    or (item.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("证据包包含无效路径")
                seen.add(item.filename)
                if item.is_dir():
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(item))
