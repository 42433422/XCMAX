"""Read the existing protected release receipts; never merge or deploy from Retort."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from modstore_server.customer_ticket_github import github
from modstore_server.retort_github_workspace import _download_artifact
from modstore_server.self_maintenance_deploy_receipts import (
    BuildIdentity,
    DeploymentReceiptError,
    verify_deployed_identity,
)

DEPLOY_WORKFLOW = "modstore-prod-deploy.yml"


def _pending(reason, **evidence):
    return {"status": "waiting_delivery", "reason": reason, **evidence}


def _rows(path, key=None):
    """Bounded, complete pagination. Partial results cannot establish delivery."""
    for page in range(1, 6):
        payload = github("GET", f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        rows = payload[key] if key else payload
        if not isinstance(rows, list):
            raise ValueError("delivery evidence list is invalid")
        yield from rows
        if len(rows) < 100:
            return
    raise ValueError("delivery evidence pagination is incomplete")


def runtime_identity(merge_sha):
    # Share the same release manifest and digest policy as authenticated deploy
    # callbacks; additionally read the public process, not a model's receipt.
    from modstore_server.self_maintenance_loop_api import _release_manifest_payload

    with httpx.Client(timeout=10, follow_redirects=False) as client:
        response = client.get("https://xiu-ci.com/api/health")
        response.raise_for_status()
        health = response.json()
    if health.get("ok") is not True or health.get("deploy_tier") != "production":
        raise DeploymentReceiptError("public_production_health_unconfirmed")
    return verify_deployed_identity(
        merge_sha=merge_sha,
        release=BuildIdentity.from_payload(_release_manifest_payload()),
        health=BuildIdentity.from_payload(health),
    )


def _release_receipt(repo, run, merge_sha):
    artifacts = list(_rows(f"/repos/{repo}/actions/runs/{run['id']}/artifacts", "artifacts"))
    matches = [
        a
        for a in artifacts
        if a.get("name") == "modstore-deployment-correlation" and not a.get("expired")
    ]
    if len(matches) != 1:
        return None
    with tempfile.TemporaryDirectory(prefix="retort-delivery-") as directory:
        root = Path(directory)
        artifact = matches[0]
        _download_artifact(repo, artifact["id"], root, artifact.get("digest", ""))
        receipt = json.loads((root / "modstore-deployment-correlation.json").read_text())
    if (
        receipt.get("merge_sha") != merge_sha
        or receipt.get("git_sha") != merge_sha
        or receipt.get("controller_sha") != run.get("head_sha")
        or receipt.get("environment") != "production"
        or not receipt.get("approval_reference")
        or not receipt.get("approval_scope")
    ):
        raise ValueError("production receipt is not bound to the approved release")
    for key, workflow in (
        ("ci_run_id", "fhd-ci-cd.yml"),
        ("security_scan_run_id", "fhd-security-full-scan.yml"),
    ):
        run_id = receipt.get(key)
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("production receipt is missing an exact evidence run")
        evidence = github("GET", f"/repos/{repo}/actions/runs/{run_id}")
        if (
            evidence.get("id") != run_id
            or evidence.get("path") != f".github/workflows/{workflow}"
            or evidence.get("head_sha") != merge_sha
            or evidence.get("head_branch") != "main"
            or evidence.get("status") != "completed"
            or evidence.get("conclusion") != "success"
        ):
            raise ValueError(f"{key} does not attest the exact successful main release")
        # Manual CI can test inputs.release_sha while head_sha names main's
        # controller. Preserve both identities before accepting old receipts.
        if key == "ci_run_id" and (
            evidence.get("event") not in {"push", "schedule", "workflow_dispatch"}
            or (
                evidence.get("event") == "workflow_dispatch"
                and evidence.get("display_title") != f"CI/CD {merge_sha}"
            )
        ):
            raise ValueError("CI evidence did not test the exact release source")
    return {**receipt, "artifact_id": artifact["id"], "artifact_digest": artifact["digest"]}


def collect_delivery(state):
    protocol, verification = state["protocol"], state["verification"]
    repo, candidate = protocol["repository"], verification.get("target_sha", "")
    number = verification.get("pull_request_number")
    if not number or not re.fullmatch(r"[0-9a-f]{40}", candidate):
        return _pending("verified_pull_request_identity_missing")
    pr = github("GET", f"/repos/{repo}/pulls/{int(number)}")
    if (
        pr.get("head", {}).get("sha") != candidate
        or pr.get("head", {}).get("repo", {}).get("full_name") != repo
        or pr.get("base", {}).get("ref") != "main"
        or pr.get("base", {}).get("repo", {}).get("full_name") != repo
    ):
        return {"status": "failed", "reason": "accepted_pull_request_identity_changed"}
    if not pr.get("merged_at"):
        if pr.get("state") == "closed":
            return {"status": "failed", "reason": "pull_request_closed_without_merge"}
        return _pending("awaiting_protected_merge", pull_request_number=number)
    merge_sha = pr.get("merge_commit_sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", merge_sha):
        return _pending("merge_commit_unconfirmed")
    comparison = github("GET", f"/repos/{repo}/compare/{merge_sha}...main")
    if comparison.get("merge_base_commit", {}).get("sha") != merge_sha or comparison.get(
        "status"
    ) not in {"identical", "ahead"}:
        return _pending("merge_not_present_on_main", merge_sha=merge_sha)
    runs = list(
        _rows(
            f"/repos/{repo}/actions/workflows/{DEPLOY_WORKFLOW}/runs?event=workflow_dispatch&branch=main",
            "workflow_runs",
        )
    )
    matches = [
        r
        for r in runs
        if r.get("display_title") == f"Deploy MODstore {merge_sha}"
        and r.get("path") == f".github/workflows/{DEPLOY_WORKFLOW}"
        and r.get("head_branch") == "main"
        and r.get("event") == "workflow_dispatch"
    ]
    if not matches:
        return _pending("awaiting_authorized_production_release", merge_sha=merge_sha)
    run = max(matches, key=lambda r: int(r["id"]))
    evidence = {"merge_sha": merge_sha, "deployment_run_id": run["id"], "url": run["html_url"]}
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return _pending("production_release_not_successful", **evidence)
    receipt = _release_receipt(repo, run, merge_sha)
    if receipt is None:
        return _pending("production_receipt_unavailable", **evidence)
    try:
        identity = runtime_identity(merge_sha)
    except DeploymentReceiptError as exc:
        return _pending(exc.reason, **evidence)
    return {
        "status": "deployment_verified",
        "scope": "shared_host_production",
        "verified_at": datetime.now(UTC).isoformat(),
        "candidate_sha": candidate,
        "pull_request_number": number,
        "receipt": receipt,
        "identity": identity,
        **evidence,
    }
