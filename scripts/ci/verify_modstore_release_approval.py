"""Bind a committed human approval to complete CI and security evidence."""

import json
import os
import re
import subprocess
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


def main():
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
