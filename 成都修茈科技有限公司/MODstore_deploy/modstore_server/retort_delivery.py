"""Read the existing protected release receipts; never merge or deploy from Retort."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zipfile import BadZipFile

import httpx
from fastapi import HTTPException

from modstore_server.customer_ticket_github import configuration, github
from modstore_server.retort_github_workspace import _download_artifact
from modstore_server.self_maintenance_deploy_receipts import (
    BuildIdentity,
    DeploymentReceiptError,
    verify_deployed_identity,
)

DEPLOY_WORKFLOW = "modstore-prod-deploy.yml"
_SHA = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_PRODUCT_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?")


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


def _contains_commit(repo, ancestor, descendant):
    """Ask GitHub for the native Git merge base of the two exact revisions."""
    comparison = github("GET", f"/repos/{repo}/compare/{ancestor}...{descendant}")
    return (
        comparison.get("status") in {"identical", "ahead"}
        and (comparison.get("merge_base_commit") or {}).get("sha") == ancestor
    )


def runtime_identity(release, product_version, release_id):
    # Read the public process after correlating the release's official evidence.
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        response = client.get("https://xiu-ci.com/api/health")
        response.raise_for_status()
        health = response.json()
    if health.get("ok") is not True or health.get("deploy_tier") != "production":
        raise DeploymentReceiptError("public_production_health_unconfirmed")
    identity = verify_deployed_identity(
        merge_sha=release.git_sha,
        release=release,
        health=BuildIdentity.from_payload(health),
    )
    if health.get("release_id") != release_id:
        raise DeploymentReceiptError("health_release_id_mismatch")
    return {**identity, "product_version": product_version, "release_id": release_id}


def _successful_steps(repo, run_id, attempt):
    return {
        (job.get("name"), step.get("name"))
        for job in _rows(f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
        if job.get("status") == "completed" and job.get("conclusion") == "success"
        for step in job.get("steps") or []
        if step.get("status") == "completed" and step.get("conclusion") == "success"
    }


def _release_receipt(repo, run, release, product_version, release_id):
    release_sha = release.git_sha
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
        receipt.get("merge_sha") != release_sha
        or receipt.get("git_sha") != release_sha
        or receipt.get("controller_sha") != run.get("head_sha")
        or receipt.get("environment") != "production"
        or not receipt.get("approval_reference")
        or not receipt.get("approval_scope")
    ):
        raise ValueError("production receipt is not bound to the approved release")
    if "signature_verified" not in receipt:
        raise DeploymentReceiptError("production_release_acceptance_incomplete")
    if (
        receipt.get("product_version") != product_version
        or receipt.get("release_id") != release_id
        or receipt.get("artifact_sha256") != release.artifact_sha256
        or receipt.get("signature_verified") is not True
        or receipt.get("signature_verifier") != "github-artifact-attestations"
        or not re.fullmatch(r"[1-9][0-9]*", str(receipt.get("attestation_id") or ""))
        or receipt.get("workflow_run_id") != str(run["id"])
        or receipt.get("runtime_git_sha") != release_sha
        or receipt.get("runtime_artifact_sha256") != release.artifact_sha256
        or receipt.get("runtime_release_id") != release_id
    ):
        raise ValueError("production acceptance does not match the signed running release")
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
            or evidence.get("head_sha") != release_sha
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
                and evidence.get("display_title") != f"CI/CD {release_sha}"
            )
        ):
            raise ValueError("CI evidence did not test the exact release source")
    deployment_attempt = run.get("run_attempt")
    signed_attempt = receipt.get("signed_run_attempt", "")
    if (
        type(deployment_attempt) is not int
        or deployment_attempt <= 0
        or receipt.get("workflow_run_attempt") != str(deployment_attempt)
        or not isinstance(signed_attempt, str)
        or not re.fullmatch(r"[1-9][0-9]*", signed_attempt)
        or int(signed_attempt) > deployment_attempt
    ):
        raise DeploymentReceiptError("production_release_acceptance_incomplete")
    deploy_steps = _successful_steps(repo, run["id"], deployment_attempt)
    signed_steps = (
        deploy_steps
        if int(signed_attempt) == deployment_attempt
        else _successful_steps(repo, run["id"], int(signed_attempt))
    )
    if (
        "admission",
        "Verify the signature and freeze the approved digest",
    ) not in signed_steps or (
        "deploy",
        "Verify independent public runtime readback",
    ) not in deploy_steps:
        raise DeploymentReceiptError("production_release_acceptance_incomplete")
    return {
        **receipt,
        "artifact_id": artifact["id"],
        "artifact_digest": artifact["digest"],
    }


def collect_delivery(state):
    try:
        return _collect_delivery(state)
    except (HTTPException, httpx.HTTPError, ValueError):
        # An unavailable GitHub or runtime read can be repeated from the
        # durable delivery checkpoint. It does not invalidate an accepted PR.
        return _pending("delivery_evidence_unavailable")


def _collect_delivery(state):
    protocol, verification = state["protocol"], state["verification"]
    repo, candidate = protocol["repository"], verification.get("target_sha", "")
    if repo != configuration()["repository"]:
        return _pending("delivery_repository_unconfirmed")
    number = verification.get("pull_request_number")
    if not number or not isinstance(candidate, str) or not _SHA.fullmatch(candidate):
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
    if not isinstance(merge_sha, str) or not _SHA.fullmatch(merge_sha):
        return _pending("merge_commit_unconfirmed")
    if not _contains_commit(repo, merge_sha, "main"):
        return _pending("merge_not_present_on_main", merge_sha=merge_sha)

    from modstore_server.self_maintenance_loop_api import _release_manifest_payload

    manifest = _release_manifest_payload()
    release = BuildIdentity.from_payload(manifest)
    release_sha = release.git_sha
    product_version = manifest.get("product_version")
    release_id = manifest.get("release_id")
    evidence = {"merge_sha": merge_sha, "release_sha": release_sha}
    if (
        not _SHA.fullmatch(release_sha)
        or not _DIGEST.fullmatch(release.artifact_sha256)
        or not isinstance(product_version, str)
        or not _PRODUCT_VERSION.fullmatch(product_version)
        or release_id != f"xcagi-{product_version}-{release_sha}"
    ):
        return _pending("production_release_manifest_unconfirmed", **evidence)
    if release_sha != merge_sha:
        if not _contains_commit(repo, merge_sha, release_sha):
            return _pending("active_release_does_not_contain_merge", **evidence)
        if not _contains_commit(repo, release_sha, "main"):
            return _pending("active_release_not_present_on_main", **evidence)
    runs = list(
        _rows(
            f"/repos/{repo}/actions/workflows/{DEPLOY_WORKFLOW}/runs?event=workflow_dispatch&branch=main",
            "workflow_runs",
        )
    )
    matches = [
        r
        for r in runs
        if r.get("display_title") == f"Deploy MODstore {release_sha}"
        and r.get("path") == f".github/workflows/{DEPLOY_WORKFLOW}"
        and r.get("head_branch") == "main"
        and r.get("event") == "workflow_dispatch"
    ]
    if not matches:
        return _pending("awaiting_authorized_production_release", **evidence)
    run = max(matches, key=lambda r: int(r["id"]))
    evidence.update(deployment_run_id=run["id"], url=run["html_url"])
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return _pending("production_release_not_successful", **evidence)
    try:
        receipt = _release_receipt(repo, run, release, product_version, release_id)
        if receipt is None:
            return _pending("production_receipt_unavailable", **evidence)
        identity = runtime_identity(release, product_version, release_id)
    except DeploymentReceiptError as exc:
        return _pending(exc.reason, **evidence)
    except (BadZipFile, OSError, ValueError):
        return _pending("production_release_evidence_mismatch", **evidence)
    except (HTTPException, httpx.HTTPError):
        return _pending("delivery_evidence_unavailable", **evidence)
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
