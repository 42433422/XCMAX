"""Production completion must be supported by independently read release evidence."""

import hashlib
import io
import json
import zipfile

import httpx
import pytest
from fastapi import HTTPException

from modstore_server import retort_delivery as delivery

SHA, HEAD, CONTROLLER = "a" * 40, "b" * 40, "c" * 40
REPO = "example/product"
LATER = "e" * 40
VERSION = "1.0.0.7"
ARTIFACT = "d" * 64


@pytest.fixture
def evidence(monkeypatch, tmp_path):
    pr = {
        "number": 9,
        "state": "closed",
        "merged_at": "2026-11-19T00:00:00Z",
        "merge_commit_sha": SHA,
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
        "base": {"ref": "main", "repo": {"full_name": REPO}},
    }
    run = {
        "id": 50,
        "run_attempt": 2,
        "display_title": f"Deploy MODstore {SHA}",
        "path": ".github/workflows/modstore-prod-deploy.yml",
        "head_sha": CONTROLLER,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "html_url": f"https://github.com/{REPO}/actions/runs/50",
    }
    receipt = {
        "merge_sha": SHA,
        "git_sha": SHA,
        "controller_sha": CONTROLLER,
        "environment": "production",
        "approval_reference": "approved-release-50",
        "approval_scope": "shared host",
        "product_version": VERSION,
        "release_id": f"xcagi-{VERSION}-{SHA}",
        "artifact_sha256": ARTIFACT,
        "runtime_git_sha": SHA,
        "runtime_artifact_sha256": ARTIFACT,
        "runtime_release_id": f"xcagi-{VERSION}-{SHA}",
        "signature_verified": True,
        "signature_verifier": "github-artifact-attestations",
        "workflow_run_id": "50",
        "workflow_run_attempt": "2",
        "signed_run_attempt": "2",
        "attestation_id": "51",
        "ci_run_id": 40,
        "security_scan_run_id": 41,
    }
    checks = {
        str(run_id): {
            "id": run_id,
            "path": f".github/workflows/{workflow}",
            "head_sha": SHA,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "event": "push" if run_id == 40 else "workflow_dispatch",
            "display_title": f"CI/CD {SHA}" if run_id == 40 else "Security full release scan",
        }
        for run_id, workflow in (
            (40, "fhd-ci-cd.yml"),
            (41, "fhd-security-full-scan.yml"),
        )
    }
    jobs = [
        {
            "name": job,
            "status": "completed",
            "conclusion": "success",
            "steps": [{"name": step, "status": "completed", "conclusion": "success"}],
        }
        for job, step in (
            ("admission", "Verify the signature and freeze the approved digest"),
            ("deploy", "Verify independent public runtime readback"),
        )
    ]
    jobs_by_attempt = {"1": jobs[:1], "2": jobs}
    manifest = {
        "git_sha": SHA,
        "artifact_sha256": ARTIFACT,
        "release_id": f"xcagi-{VERSION}-{SHA}",
        "product_version": VERSION,
    }
    health = {**manifest, "ok": True, "deploy_tier": "production"}
    local_manifest = tmp_path / "release.json"
    local_manifest.write_text(json.dumps(manifest))
    monkeypatch.setenv("MODSTORE_RELEASE_MANIFEST", str(local_manifest))
    monkeypatch.setenv("MODSTORE_GITHUB_TOKEN", "test-only")
    monkeypatch.setenv("MODSTORE_GITHUB_REPOSITORY", REPO)
    calls = []
    archive = {"digest_override": ""}
    comparisons = {
        f"{SHA}...main": {"status": "ahead", "merge_base_commit": {"sha": SHA}},
        f"{SHA}...{LATER}": {"status": "ahead", "merge_base_commit": {"sha": SHA}},
        f"{LATER}...main": {"status": "ahead", "merge_base_commit": {"sha": LATER}},
    }

    def packed():
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as zipped:
            zipped.writestr(
                zipfile.ZipInfo("modstore-deployment-correlation.json", (2026, 1, 1, 0, 0, 0)),
                json.dumps(receipt),
            )
        return stream.getvalue()

    def github(method, path, body=None):
        assert method == "GET", "delivery polling must never mutate or bypass release approval"
        calls.append(path)
        if path.endswith("/pulls/9"):
            return pr
        if "/compare/" in path:
            return comparisons[path.rsplit("/", 1)[-1]]
        if "/artifacts?" in path:
            return {
                "artifacts": [
                    {
                        "id": 60,
                        "name": "modstore-deployment-correlation",
                        "expired": False,
                        "digest": archive["digest_override"]
                        or "sha256:" + hashlib.sha256(packed()).hexdigest(),
                    }
                ]
            }
        if "/attempts/" in path:
            assert "/runs/50/attempts/" in path
            return {"jobs": jobs_by_attempt[path.split("/attempts/")[1].split("/")[0]]}
        if "/workflows/" in path:
            return {"workflow_runs": [run]}
        return checks[path.rsplit("/", 1)[-1]]

    def respond(request):
        if request.url.host == "api.github.com":
            assert request.headers["authorization"] == "Bearer test-only"
            return httpx.Response(
                302, headers={"location": "https://proof.blob.core.windows.net/archive"}
            )
        assert "authorization" not in request.headers
        if request.url.host == "proof.blob.core.windows.net":
            return httpx.Response(200, content=packed())
        assert str(request.url) == "https://xiu-ci.com/api/health"
        return httpx.Response(200, json=health)

    original = httpx.Client
    monkeypatch.setattr(delivery, "github", github)
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    return {
        "state": {
            "protocol": {"repository": REPO},
            "verification": {"target_sha": HEAD, "pull_request_number": 9},
        },
        "pr": pr,
        "run": run,
        "checks": checks,
        "jobs": jobs,
        "jobs_by_attempt": jobs_by_attempt,
        "receipt": receipt,
        "health": health,
        "manifest": manifest,
        "manifest_path": local_manifest,
        "comparisons": comparisons,
        "archive": archive,
        "calls": calls,
    }


def test_verified_branch_is_not_complete_before_protected_merge(evidence):
    evidence["pr"].update(merged_at=None, state="open")
    result = delivery.collect_delivery(evidence["state"])
    assert result["reason"] == "awaiting_protected_merge"
    assert len(evidence["calls"]) == 1


def test_exact_production_receipt_and_public_identity_complete_delivery(evidence):
    result = delivery.collect_delivery(evidence["state"])
    assert result["status"] == "deployment_verified"
    assert result["merge_sha"] == result["release_sha"] == SHA
    assert result["candidate_sha"] == HEAD
    assert result["identity"]["product_version"] == VERSION
    assert result["receipt"]["security_scan_run_id"] == 41
    assert result["identity"]["artifact_sha256"] == "d" * 64


def _active_descendant(evidence):
    release_id = f"xcagi-{VERSION}-{LATER}"
    evidence["manifest"].update(git_sha=LATER, release_id=release_id)
    evidence["manifest_path"].write_text(json.dumps(evidence["manifest"]))
    evidence["health"].update(git_sha=LATER, release_id=release_id)
    evidence["run"].update(display_title=f"Deploy MODstore {LATER}")
    evidence["receipt"].update(
        merge_sha=LATER,
        git_sha=LATER,
        release_id=release_id,
        runtime_git_sha=LATER,
        runtime_release_id=release_id,
    )
    for check in evidence["checks"].values():
        check.update(head_sha=LATER)


def test_newer_production_release_includes_older_verified_merge(evidence):
    _active_descendant(evidence)
    result = delivery.collect_delivery(evidence["state"])
    assert result["status"] == "deployment_verified"
    assert result["merge_sha"] == SHA
    assert result["release_sha"] == result["identity"]["git_sha"] == LATER
    assert result["receipt"]["git_sha"] == LATER
    assert f"/repos/{REPO}/compare/{SHA}...{LATER}" in evidence["calls"]
    assert f"/repos/{REPO}/compare/{LATER}...main" in evidence["calls"]


@pytest.mark.parametrize("status", ["behind", "diverged"])
def test_active_release_without_verified_merge_stays_pending(evidence, status):
    _active_descendant(evidence)
    evidence["comparisons"][f"{SHA}...{LATER}"]["status"] = status
    result = delivery.collect_delivery(evidence["state"])
    assert result["reason"] == "active_release_does_not_contain_merge"
    assert len(evidence["calls"]) == 3


def test_descendant_outside_current_main_stays_pending(evidence):
    _active_descendant(evidence)
    evidence["comparisons"][f"{LATER}...main"].update(status="diverged")
    result = delivery.collect_delivery(evidence["state"])
    assert result["reason"] == "active_release_not_present_on_main"


def test_descendant_cannot_use_predecessors_release_receipt(evidence):
    _active_descendant(evidence)
    evidence["run"].update(display_title=f"Deploy MODstore {SHA}")
    result = delivery.collect_delivery(evidence["state"])
    assert result["reason"] == "awaiting_authorized_production_release"


def test_descendant_cannot_borrow_predecessors_ci_evidence(evidence):
    _active_descendant(evidence)
    evidence["checks"]["40"].update(head_sha=SHA)
    assert (
        delivery.collect_delivery(evidence["state"])["reason"]
        == "production_release_evidence_mismatch"
    )


@pytest.mark.parametrize("index", [0, 1])
def test_receipt_cannot_claim_unexecuted_protected_steps(evidence, index):
    evidence["jobs"][index]["steps"][0]["conclusion"] = "skipped"
    result = delivery.collect_delivery(evidence["state"])
    assert result["status"] == "waiting_delivery"
    assert result["reason"] == "production_release_acceptance_incomplete"


def test_deploy_retry_reuses_successful_admission_from_same_workflow_run(evidence):
    evidence["receipt"]["signed_run_attempt"] = "1"
    evidence["jobs_by_attempt"]["2"] = evidence["jobs"][1:]
    assert delivery.collect_delivery(evidence["state"])["status"] == "deployment_verified"
    assert any("/runs/50/attempts/1/jobs?" in call for call in evidence["calls"])


def test_old_correlation_cannot_claim_a_newer_deploy_attempt(evidence):
    evidence["run"]["run_attempt"] = 3
    assert (
        delivery.collect_delivery(evidence["state"])["reason"]
        == "production_release_acceptance_incomplete"
    )


def test_legacy_unsigned_workflow_receipt_stays_pending(evidence):
    del evidence["receipt"]["signature_verified"]
    result = delivery.collect_delivery(evidence["state"])
    assert result["reason"] == "production_release_acceptance_incomplete"


@pytest.mark.parametrize(
    "event,title",
    [
        ("push", "Legacy push title"),
        ("schedule", "Nightly CI"),
        ("workflow_dispatch", f"CI/CD {SHA}"),
    ],
)
def test_ci_checkout_source_accepts_supported_main_events(evidence, event, title):
    evidence["checks"]["40"].update(event=event, display_title=title)
    assert delivery.collect_delivery(evidence["state"])["status"] == "deployment_verified"


@pytest.mark.parametrize(
    "event,title",
    [
        ("workflow_dispatch", f"CI/CD {HEAD}"),
        ("workflow_dispatch", f"CI/CD {SHA} candidate"),
        ("workflow_dispatch", None),
        ("pull_request", f"CI/CD {SHA}"),
        (None, f"CI/CD {SHA}"),
    ],
)
def test_ci_controller_sha_without_tested_source_cannot_complete_delivery(evidence, event, title):
    evidence["checks"]["40"].update(event=event, display_title=title)
    assert (
        delivery.collect_delivery(evidence["state"])["reason"]
        == "production_release_evidence_mismatch"
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        (
            lambda e: e["pr"]["head"].update(sha="f" * 40),
            "accepted_pull_request_identity_changed",
        ),
        (lambda e: e["pr"].update(merged_at=None), "pull_request_closed_without_merge"),
        (
            lambda e: e["run"].update(conclusion="failure"),
            "production_release_not_successful",
        ),
        (lambda e: e["health"].update(git_sha="f" * 40), "health_sha_mismatch"),
        (
            lambda e: e["health"].update(artifact_sha256="e" * 64),
            "health_artifact_digest_mismatch",
        ),
        (
            lambda e: e["health"].update(release_id=f"xcagi-1.0.0.6-{SHA}"),
            "health_release_id_mismatch",
        ),
        (
            lambda e: e["health"].update(deploy_tier="staging"),
            "public_production_health_unconfirmed",
        ),
    ],
)
def test_incomplete_or_changed_evidence_never_completes(evidence, change, reason):
    change(evidence)
    result = delivery.collect_delivery(evidence["state"])
    assert result["status"] != "deployment_verified" and result["reason"] == reason


@pytest.mark.parametrize(
    "change",
    [
        lambda e: e["receipt"].update(git_sha="f" * 40),
        lambda e: e["receipt"].update(approval_reference=""),
        lambda e: e["receipt"].update(signature_verified=False),
        lambda e: e["receipt"].update(attestation_id="0"),
        lambda e: e["receipt"].update(workflow_run_id="49"),
        lambda e: e["receipt"].update(product_version="1.0.0.6"),
        lambda e: e["receipt"].update(artifact_sha256="b" * 64),
        lambda e: e["receipt"].update(runtime_git_sha=LATER),
        lambda e: e["checks"]["41"].update(conclusion="failure"),
        lambda e: e["checks"]["40"].update(head_sha="f" * 40),
        lambda e: e["archive"].update(digest_override="sha256:" + "0" * 64),
    ],
)
def test_forged_archive_or_wrong_security_run_is_rejected(evidence, change):
    change(evidence)
    assert (
        delivery.collect_delivery(evidence["state"])["reason"]
        == "production_release_evidence_mismatch"
    )


def test_unconfigured_repository_never_queries_github(evidence):
    evidence["state"]["protocol"]["repository"] = "other/repo"
    result = delivery.collect_delivery(evidence["state"])
    assert result["reason"] == "delivery_repository_unconfirmed"
    assert not evidence["calls"]


def test_unavailable_github_evidence_keeps_delivery_resumable(evidence, monkeypatch):
    def unavailable(*args):
        raise HTTPException(502, "GitHub unavailable")

    monkeypatch.setattr(delivery, "github", unavailable)
    assert delivery.collect_delivery(evidence["state"]) == {
        "status": "waiting_delivery",
        "reason": "delivery_evidence_unavailable",
    }


def test_pagination_limit_never_promotes_partial_evidence(monkeypatch):
    monkeypatch.setattr(delivery, "github", lambda *_: {"workflow_runs": [{}] * 100})
    with pytest.raises(ValueError, match="pagination is incomplete"):
        list(delivery._rows("/runs", "workflow_runs"))
