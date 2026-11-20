"""Production completion must be supported by independently read release evidence."""

import hashlib
import io
import json
import zipfile

import httpx
import pytest

from modstore_server import retort_delivery as delivery

SHA, HEAD, CONTROLLER = "a" * 40, "b" * 40, "c" * 40
REPO = "example/product"


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
        "run_attempt": 1,
        "display_title": f"Deploy MODstore {SHA}",
        "path": ".github/workflows/modstore-prod-deploy.yml",
        "head_sha": CONTROLLER,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "html_url": f"https://github.com/{REPO}/actions/runs/50",
    }
    job = {
        "name": "deploy",
        "status": "completed",
        "conclusion": "success",
        "started_at": "2026-11-19T00:10:00Z",
        "completed_at": "2026-11-19T00:20:00Z",
    }
    receipt = {
        "merge_sha": SHA,
        "git_sha": SHA,
        "controller_sha": CONTROLLER,
        "environment": "production",
        "approval_reference": "approved-release-50",
        "approval_scope": "shared host",
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
        for run_id, workflow in ((40, "fhd-ci-cd.yml"), (41, "fhd-security-full-scan.yml"))
    }
    manifest = {"git_sha": SHA, "artifact_sha256": "d" * 64}
    health = {**manifest, "ok": True, "deploy_tier": "production"}
    local_manifest = tmp_path / "release.json"
    local_manifest.write_text(json.dumps(manifest))
    monkeypatch.setenv("MODSTORE_RELEASE_MANIFEST", str(local_manifest))
    monkeypatch.setenv("MODSTORE_GITHUB_TOKEN", "test-only")
    calls = []
    archive = {"digest_override": ""}

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
            return {"status": "ahead", "merge_base_commit": {"sha": SHA}}
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
        if "/attempts/1/jobs?" in path:
            return {"jobs": [job]}
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
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    return {
        "state": {
            "protocol": {"repository": REPO},
            "verification": {"target_sha": HEAD, "pull_request_number": 9},
        },
        "pr": pr,
        "run": run,
        "job": job,
        "checks": checks,
        "receipt": receipt,
        "health": health,
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
    assert result["merge_sha"] == SHA and result["candidate_sha"] == HEAD
    assert result["deployment_completed_at"] == "2026-11-19T00:20:00+00:00"
    assert result["receipt"]["security_scan_run_id"] == 41
    assert result["identity"]["artifact_sha256"] == "d" * 64


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
    with pytest.raises(ValueError):
        delivery.collect_delivery(evidence["state"])


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda e: e["pr"]["head"].update(sha="f" * 40), "accepted_pull_request_identity_changed"),
        (lambda e: e["pr"].update(merged_at=None), "pull_request_closed_without_merge"),
        (lambda e: e["run"].update(conclusion="failure"), "production_release_not_successful"),
        (lambda e: e["health"].update(git_sha="f" * 40), "health_sha_mismatch"),
        (lambda e: e["health"].update(artifact_sha256="e" * 64), "health_artifact_digest_mismatch"),
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
        lambda e: e["checks"]["41"].update(conclusion="failure"),
        lambda e: e["checks"]["40"].update(head_sha="f" * 40),
        lambda e: e["archive"].update(digest_override="sha256:" + "0" * 64),
    ],
)
def test_forged_archive_or_wrong_security_run_is_rejected(evidence, change):
    change(evidence)
    with pytest.raises(ValueError):
        delivery.collect_delivery(evidence["state"])


def test_pagination_limit_never_promotes_partial_evidence(monkeypatch):
    monkeypatch.setattr(delivery, "github", lambda *_: {"workflow_runs": [{}] * 100})
    with pytest.raises(ValueError, match="pagination is incomplete"):
        list(delivery._rows("/runs", "workflow_runs"))


def test_missing_or_untrusted_job_time_never_establishes_exposure(evidence):
    evidence["job"]["completed_at"] = "2026-11-18T00:20:00Z"
    assert delivery.collect_delivery(evidence["state"])["deployment_completed_at"] is None
    evidence["job"]["completed_at"] = None
    assert delivery.collect_delivery(evidence["state"])["deployment_completed_at"] is None
