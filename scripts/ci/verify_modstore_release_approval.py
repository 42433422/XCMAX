"""Bind a committed human approval to complete CI and security evidence."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def verify(approval, sha, version, runs):
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
    for key, path in [
        ("ci_run_id", ".github/workflows/fhd-ci-cd.yml"),
        ("security_scan_run_id", ".github/workflows/fhd-security-full-scan.yml"),
    ]:
        run = runs[key]
        if (
            run["id"] != approval[key]
            or run["head_sha"] != sha
            or run["path"] != path
            or run["status"] != "completed"
            or run["conclusion"] != "success"
            or run["head_branch"] != "main"
        ):
            raise ValueError(
                f"{key}: complete successful same-SHA main evidence required"
            )
        # Dispatch head_sha is the controller; CI's existing run-name identifies
        # inputs.release_sha, which can select a different checkout on main.
        if key == "ci_run_id" and (
            run.get("event") not in {"push", "schedule", "workflow_dispatch"}
            or (
                run.get("event") == "workflow_dispatch"
                and run.get("display_title") != f"CI/CD {sha}"
            )
        ):
            raise ValueError(
                "ci_run_id: actual tested source must match the release SHA"
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
    runs = {}
    for key, variable in [
        ("ci_run_id", "CI_RUN_ID"),
        ("security_scan_run_id", "SECURITY_SCAN_RUN_ID"),
    ]:
        run_id = os.environ[variable]
        if not run_id.isdecimal():
            raise ValueError("numeric evidence run ID required")
        runs[key] = json.loads(
            subprocess.check_output(
                [
                    "gh",
                    "api",
                    f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}",
                ]
            )
        )
    verify(approval, sha, os.environ["PRODUCT_VERSION"], runs)
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
    )
    Path(os.environ["RUNNER_TEMP"], "modstore-deployment-correlation.json").write_text(
        json.dumps(receipt)
    )
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"sha={sha}\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
