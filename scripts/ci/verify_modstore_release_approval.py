"""Bind a committed human approval to complete CI and security evidence."""

import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def verify_run_source(key, run, sha, *, source_evidence=None, contains=None):
    """Keep the immutable workflow controller distinct from its tested checkout."""
    controller = run.get("head_sha", "")
    workflow = {
        "ci_run_id": "fhd-ci-cd.yml",
        "security_scan_run_id": "fhd-security-full-scan.yml",
    }[key]
    if (
        not isinstance(controller, str)
        or not re.fullmatch(r"[0-9a-f]{40}", controller)
        or run.get("path") != f".github/workflows/{workflow}"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("head_branch") != "main"
    ):
        raise ValueError(f"{key}: complete successful main evidence required")
    event = run.get("event")
    if key == "ci_run_id" and (
        event not in {"push", "schedule", "workflow_dispatch"}
        or (
            event == "workflow_dispatch"
            and not re.fullmatch(
                re.escape(f"CI/CD {sha}")
                + r"(?: \[delivery:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\])?",
                str(run.get("display_title") or ""),
            )
        )
    ):
        raise ValueError("ci_run_id: actual tested source must match the release SHA")
    if controller != sha and (
        event != "workflow_dispatch"
        or not isinstance(source_evidence, dict)
        or contains is None
        or not contains(sha, controller)
        or not contains(controller, "main")
        or source_evidence.get("source_sha") != sha
        or source_evidence.get("controller_sha") != controller
        or source_evidence.get("run_id") != run.get("id")
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] < 1
        or source_evidence.get("run_attempt") != run["run_attempt"]
    ):
        raise ValueError(
            f"{key}: original controller and tested source are unconfirmed"
        )


def read_source_evidence(repo, key, run, sha, *, api, read_archive):
    """Verify bytes from the existing CI/security producers; never create new proof."""
    try:
        return _read_source_evidence(
            repo, key, run, sha, api=api, read_archive=read_archive
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("original source evidence is missing or malformed") from exc


def _read_source_evidence(repo, key, run, sha, *, api, read_archive):
    attempt = run.get("run_attempt")
    if type(attempt) is not int or attempt < 1:
        raise ValueError("original evidence attempt is missing")
    name = (
        f"backend-combined-{attempt}"
        if key == "ci_run_id"
        else "xcagi-security-release-reports"
    )
    route = f"/repos/{repo}/actions/runs/{run['id']}"
    original = api(f"{route}/attempts/{attempt}")
    if any(
        original.get(field) != run.get(field)
        for field in (
            "id",
            "run_attempt",
            "head_sha",
            "path",
            "status",
            "conclusion",
        )
    ):
        raise ValueError("original source attempt changed")
    rows, total = [], None
    for page in range(1, 11):
        data = api(f"{route}/artifacts?per_page=100&page={page}")
        batch, count = data.get("artifacts"), data.get("total_count")
        if (
            not isinstance(batch, list)
            or type(count) is not int
            or count < 0
            or (total is not None and count != total)
        ):
            raise ValueError("original source artifacts are incomplete")
        rows.extend(batch)
        total = count
        if len(rows) == count:
            break
        if len(rows) > count or not batch:
            raise ValueError("original source artifacts are incomplete")
    else:
        raise ValueError("original source artifact pagination exceeded")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate source artifact identity")
    matches = [row for row in rows if row.get("name") == name]
    if len(matches) != 1:
        raise ValueError("original source artifact missing or ambiguous")
    artifact = matches[0]

    def stamp(value):
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            raise ValueError("source timestamps must carry a timezone")
        return parsed.astimezone(UTC)

    if (
        artifact.get("expired") is not False
        or type(artifact.get("size_in_bytes")) is not int
        or not 0 < artifact["size_in_bytes"] <= 32 * 1024 * 1024
        or (artifact.get("workflow_run") or {}).get("id") != run["id"]
        or (artifact.get("workflow_run") or {}).get("head_sha") != run["head_sha"]
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact.get("digest") or ""))
        or not stamp(original["run_started_at"])
        <= stamp(artifact.get("created_at"))
        <= stamp(original["updated_at"])
    ):
        raise ValueError("original source artifact/attempt mismatch")
    # Transport must authenticate GitHub and compare its immutable ZIP digest.
    files = read_archive(artifact)
    if key == "ci_run_id":
        evidence = json.loads(files["business-contract-evidence.json"])
        if any(
            evidence.get(field) != value
            for field, value in {
                "source_sha": sha,
                "test_sha": sha,
                "run_id": str(run["id"]),
                "run_attempt": str(attempt),
                "execution_environment": "github-actions",
            }.items()
        ):
            raise ValueError(
                "CI native artifact tested a different checkout or attempt"
            )
        selected = ["business-contract-evidence.json"]
    else:
        # Reuse the release scanner inventory, not a second scanner allowlist.
        path = (
            Path(__file__).resolve().parents[2]
            / "FHD/scripts/security/security_release_gate.py"
        )
        spec = importlib.util.spec_from_file_location(
            "_xcmax_security_release_gate", path
        )
        if not spec or not spec.loader:
            raise ValueError("original security source contract unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        selected = [f"{scanner}.json" for scanner in module.REQUIRED_SCANNERS]
        for filename in selected:
            evidence = json.loads(files[filename])
            if (
                evidence.get("release_sha") != sha
                or evidence.get("source_sha") != sha
                or evidence.get("available") is not True
            ):
                raise ValueError(
                    "security native artifact scanned a different checkout"
                )
    latest = api(route)
    if any(
        latest.get(field) != run.get(field)
        for field in (
            "id",
            "run_attempt",
            "head_sha",
            "path",
            "status",
            "conclusion",
        )
    ):
        raise ValueError("source run changed during readback")
    return {
        "run_id": run["id"],
        "run_attempt": attempt,
        "source_sha": sha,
        "controller_sha": run["head_sha"],
        "artifact_id": artifact["id"],
        "artifact_digest": artifact["digest"],
        "files": {name: hashlib.sha256(files[name]).hexdigest() for name in selected},
    }


def _api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], timeout=60))


def _archive(repo, artifact):
    raw = subprocess.check_output(
        ["gh", "api", f"/repos/{repo}/actions/artifacts/{artifact['id']}/zip"],
        timeout=120,
    )
    if (
        len(raw) != artifact["size_in_bytes"]
        or artifact["digest"] != "sha256:" + hashlib.sha256(raw).hexdigest()
    ):
        raise ValueError("original source archive byte digest mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if (
            len(names) != len(set(names))
            or sum(row.file_size for row in archive.infolist()) > 64 * 1024 * 1024
        ):
            raise ValueError("original source archive is ambiguous or oversized")
        # No extraction: only the canonical JSON files are consumed below.
        return {name: archive.read(name) for name in names if name.endswith(".json")}


def _contains(ancestor, descendant):
    target = "HEAD" if descendant == "main" else descendant
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, target],
            capture_output=True,
            check=False,
            timeout=15,
        ).returncode
        == 0
    )


def verify(approval, sha, version, runs, *, source_evidence=None, contains=None):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("full release SHA required")
    if (
        approval["git_sha"] != sha
        or approval["product_version"] != version
        or not re.fullmatch(r"[0-9a-f]{40}", approval["expected_production_sha"])
        or not approval["approval_reference"]
        or not approval["approval_scope"]
    ):
        raise ValueError("release differs from committed human approval")
    for key in ("ci_run_id", "security_scan_run_id"):
        run = runs[key]
        if run["id"] != approval[key]:
            raise ValueError(f"{key}: exact approved evidence run required")
        verify_run_source(
            key,
            run,
            sha,
            source_evidence=(source_evidence or {}).get(key),
            contains=contains,
        )


def verify_running_release(
    admission,
    health,
    digest,
    *,
    controller_sha,
    workflow_run_id,
    signed_attempt,
    workflow_attempt,
):
    """Finalize acceptance only after a signed artifact and public runtime agree."""
    sha = admission.get("git_sha", "")
    version = admission.get("product_version", "")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", sha)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?", version)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not re.fullmatch(r"[0-9a-f]{40}", controller_sha)
        or not re.fullmatch(r"[1-9][0-9]*", workflow_run_id)
        or not re.fullmatch(r"[1-9][0-9]*", signed_attempt)
        or not re.fullmatch(r"[1-9][0-9]*", workflow_attempt)
        or int(signed_attempt) > int(workflow_attempt)
        or admission.get("merge_sha") != sha
        or admission.get("controller_sha") != controller_sha
        or admission.get("workflow_run_id") != workflow_run_id
        or admission.get("signed_run_attempt") != signed_attempt
        or admission.get("environment") != "production"
        or admission.get("artifact_sha256") != digest
        or admission.get("signature_verified") is not True
        or admission.get("signature_verifier") != "github-artifact-attestations"
        or not re.fullmatch(r"[1-9][0-9]*", admission.get("attestation_id", ""))
    ):
        raise ValueError(
            "release admission is not bound to the verified signature and workflow"
        )
    release_id = f"xcagi-{version}-{sha}"
    if (
        health.get("ok") is not True
        or health.get("deploy_tier") != "production"
        or health.get("git_sha") != sha
        or health.get("artifact_sha256") != digest
        or health.get("release_id") != release_id
    ):
        raise ValueError(
            "public runtime differs from the signed artifact, version, or release SHA"
        )
    return {
        **admission,
        "release_id": release_id,
        "workflow_run_attempt": workflow_attempt,
        "runtime_release_id": health["release_id"],
        "runtime_git_sha": health["git_sha"],
        "runtime_artifact_sha256": health["artifact_sha256"],
    }


def main():
    if sys.argv[1:] == ["--finalize"]:
        root = Path(os.environ["RUNNER_TEMP"])
        receipt = verify_running_release(
            json.loads((root / "modstore-release-admission.json").read_text()),
            json.loads((root / "modstore-release-health.json").read_text()),
            os.environ["APPROVED_ARTIFACT_SHA256"],
            controller_sha=os.environ["GITHUB_SHA"],
            workflow_run_id=os.environ["GITHUB_RUN_ID"],
            signed_attempt=os.environ["SIGNED_RUN_ATTEMPT"],
            workflow_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
        )
        (root / "modstore-deployment-correlation.json").write_text(json.dumps(receipt))
        return
    if sys.argv[1:]:
        raise SystemExit("Unexpected release verifier arguments")
    sha = os.environ["REQUESTED_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("full release SHA required")
    approval = json.loads(Path(f"ops/releases/{sha}.json").read_text())
    runs, source_evidence = {}, {}
    repo = os.environ["GITHUB_REPOSITORY"]
    for key, variable in [
        ("ci_run_id", "CI_RUN_ID"),
        ("security_scan_run_id", "SECURITY_SCAN_RUN_ID"),
    ]:
        run_id = os.environ[variable]
        if not run_id.isdecimal():
            raise ValueError("numeric evidence run ID required")
        runs[key] = _api(f"/repos/{repo}/actions/runs/{run_id}")
        if runs[key].get("head_sha") != sha:
            source_evidence[key] = read_source_evidence(
                repo,
                key,
                runs[key],
                sha,
                api=_api,
                read_archive=lambda artifact: _archive(repo, artifact),
            )
    verify(
        approval,
        sha,
        os.environ["PRODUCT_VERSION"],
        runs,
        source_evidence=source_evidence,
        contains=_contains,
    )
    for earlier, later in [(sha, "HEAD"), (approval["expected_production_sha"], sha)]:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", earlier, later], check=True
        )
    receipt = dict(
        approval,
        merge_sha=sha,
        controller_sha=os.environ["GITHUB_SHA"],
        run_id=os.environ.get("SELF_MAINTENANCE_RUN_ID", ""),
        environment="production",
        source_evidence=source_evidence,
    )
    Path(os.environ["RUNNER_TEMP"], "modstore-deployment-correlation.json").write_text(
        json.dumps(receipt)
    )
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"sha={sha}\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
