"""GitHub Actions and HTTP deployment receipt gateway."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import httpx

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.self_maintenance_deploy_receipts import (
    BuildIdentity,
    DeploymentReceiptError,
    DispatchReceipt,
    WorkflowCompletion,
    _environment,
    _merge_sha,
    _sha,
    correlated_verified_deploys,
    resolve_pending_merge_request,
)


class GhActionsDeploymentGateway:
    """Concrete GitHub/HTTP adapter, used only behind an explicit switch."""

    HEALTH_URLS = {
        "staging": "https://xiu-ci.com/fhd-staging-api/api/health",
        "production": "https://xiu-ci.com/fhd-api/api/health",
    }
    RELEASE_URLS = {
        "staging": "https://xiu-ci.com/update/releases/staging/server/fhd-manifest.json",
        "production": "https://xiu-ci.com/update/releases/stable/server/fhd-manifest.json",
    }

    def __init__(
        self,
        *,
        repo_root: Path,
        repository: str,
        ref: str,
        workflow: str = "fhd-deploy.yml",
        poll_seconds: float = 3.0,
        capture_timeout_seconds: int = 90,
        workflow_timeout_seconds: int = 1800,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.repository = repository.strip()
        self.ref = ref.strip()
        self.workflow = workflow.strip()
        self.poll_seconds = max(0.2, poll_seconds)
        self.capture_timeout_seconds = max(10, capture_timeout_seconds)
        self.workflow_timeout_seconds = max(30, workflow_timeout_seconds)
        if "/" not in self.repository or not self.ref:
            raise DeploymentReceiptError("github_deploy_config_missing")

    @classmethod
    def from_environment(cls, *, repo_root: Path, ref: str) -> GhActionsDeploymentGateway:
        return cls(
            repo_root=repo_root,
            repository=str(
                os.environ.get("MODSTORE_SELF_MAINTENANCE_GITHUB_REPOSITORY")
                or os.environ.get("GITHUB_REPOSITORY")
                or ""
            ),
            ref=ref,
            workflow=str(
                os.environ.get("MODSTORE_SELF_MAINTENANCE_DEPLOY_WORKFLOW") or "fhd-deploy.yml"
            ),
        )

    def _run(self, args: Sequence[str]) -> str:
        try:
            result = subprocess.run(
                list(args),
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeploymentReceiptError("gh_command_failed") from exc
        if result.returncode != 0:
            raise DeploymentReceiptError("gh_command_failed")
        return str(result.stdout or "").strip()

    def _json(self, args: Sequence[str]) -> Any:
        try:
            return json.loads(self._run(args) or "null")
        except json.JSONDecodeError as exc:
            raise DeploymentReceiptError("gh_invalid_json") from exc

    def _runs(self) -> List[Dict[str, Any]]:
        # Search filters (including event/head_sha) cap GitHub's results at
        # 1,000. Read every unfiltered page before treating absence as safe.
        payload = self._json(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{self.repository}/actions/workflows/{self.workflow}/runs?per_page=100",
            ]
        )
        if not isinstance(payload, list) or not payload:
            raise DeploymentReceiptError("github_run_list_invalid")
        rows: List[Dict[str, Any]] = []
        identities: set[int] = set()
        totals: set[int] = set()
        for page in payload:
            if (
                not isinstance(page, Mapping)
                or type(page.get("total_count")) is not int
                or page["total_count"] < 0
                or not isinstance(page.get("workflow_runs"), list)
            ):
                raise DeploymentReceiptError("github_run_list_invalid")
            totals.add(page["total_count"])
            for row in page["workflow_runs"]:
                if (
                    not isinstance(row, Mapping)
                    or type(row.get("id")) is not int
                    or row["id"] <= 0
                    or not isinstance(row.get("head_sha"), str)
                    or len(_merge_sha(row["head_sha"])) != 40
                    or not isinstance(row.get("display_title"), str)
                    or not isinstance(row.get("event"), str)
                    or not row["event"]
                    or not isinstance(row.get("status"), str)
                    or not isinstance(row.get("path"), str)
                    or row["path"].split("@", 1)[0] != f".github/workflows/{self.workflow}"
                    or not isinstance(row.get("repository"), Mapping)
                    or row["repository"].get("full_name") != self.repository
                ):
                    raise DeploymentReceiptError("github_run_list_invalid")
                if row["id"] in identities:
                    raise DeploymentReceiptError("github_run_list_incomplete")
                identities.add(row["id"])
                if row["event"] != "workflow_dispatch":
                    continue
                if (
                    not isinstance(row.get("head_branch"), str)
                    or not row["head_branch"]
                    or not isinstance(row.get("head_repository"), Mapping)
                    or row["head_repository"].get("full_name") != self.repository
                ):
                    raise DeploymentReceiptError("github_run_list_invalid")
                rows.append(
                    {
                        "databaseId": row["id"],
                        "headSha": row["head_sha"],
                        "headBranch": row["head_branch"],
                        "displayTitle": row["display_title"],
                        "status": row["status"],
                        "conclusion": row.get("conclusion"),
                        "url": str(row.get("html_url") or ""),
                    }
                )
        # Concurrent additions/deletions or a truncated response are retryable
        # read failures, never proof that the operation has not been accepted.
        if totals != {len(identities)}:
            raise DeploymentReceiptError("github_run_list_incomplete")
        return rows

    @staticmethod
    def _ledger_rows() -> List[Dict[str, Any]]:
        from modstore_server.maintenance_loop import store

        path = store.ledger_path()
        try:
            rows = (
                [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
                if path.exists()
                else []
            )
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError("ledger row is not an object")
            return rows
        except (ValueError, OSError) as exc:
            raise DeploymentReceiptError("deployment_dispatch_ledger_unavailable") from exc

    def _binding(self, environment: str, merge_sha: str, action_id: str) -> Dict[str, str]:
        return {
            "repository": self.repository,
            "workflow": self.workflow,
            "ref": self.ref,
            "environment": environment,
            "merge_sha": merge_sha,
            "action_id": action_id,
        }

    def recover_verified_deployment(
        self, *, run_id: str, merge_sha: str, environment: str, action_id: str
    ) -> Dict[str, Any] | None:
        """A verified historical deployment stays terminal when a later release ships."""
        rows = self._ledger_rows()
        binding = self._binding(environment, merge_sha, action_id)
        bound = [
            row
            for row in rows
            if row.get("event") == "deploy_dispatch_bound" and row.get("action_id") == action_id
        ]
        if any(any(row.get(key) != value for key, value in binding.items()) for row in bound):
            raise DeploymentReceiptError("deployment_dispatch_binding_conflict")
        for row in reversed(correlated_verified_deploys(rows)):
            if (
                row.get("run_id") == run_id
                and row.get("merge_sha") == merge_sha
                and row.get("environment") == environment
                and row.get("action_id") == action_id
                and any(
                    record.get("workflow_run_id") == row.get("workflow_run_id")
                    and record.get("controller_sha") == row.get("controller_sha")
                    for record in bound
                )
            ):
                identity = BuildIdentity.from_payload(row).require_complete("verified_receipt")
                if identity.git_sha != merge_sha:
                    raise DeploymentReceiptError("verified_receipt_sha_mismatch")
                return {**row, "verified": True, "recovered": True}
        return None

    def verify_requested_merge(self, *, run_id, merge_sha, task_id, branch):
        from modstore_server.maintenance_loop import store

        rows = [
            row
            for row in store._read_ledger(limit=0)
            if row.get("event") == "merge_requested"
            and row.get("run_id") == run_id
            and row.get("para_task_id") == task_id
            and row.get("branch") == branch
        ]

        def is_ancestor(ancestor, descendant):
            comparison = self._json(
                [
                    "gh",
                    "api",
                    f"repos/{self.repository}/compare/{ancestor}...{descendant}",
                ]
            )
            return (
                isinstance(comparison, Mapping)
                and comparison.get("status") in {"ahead", "identical"}
                and (comparison.get("merge_base_commit") or {}).get("sha") == ancestor
            )

        try:
            return resolve_pending_merge_request(
                rows, merge_sha=merge_sha, is_ancestor=is_ancestor, requested_run_id=run_id
            )
        except DeploymentReceiptError as exc:
            if exc.reason != "pending_merge_not_found":
                raise
        prs = self._json(
            ["gh", "api", f"repos/{self.repository}/commits/{merge_sha}/pulls?per_page=100"]
        )
        if not isinstance(prs, list) or len(prs) == 100:
            raise DeploymentReceiptError("pending_merge_attestation_incomplete")
        matches = [
            pr
            for pr in prs
            if pr.get("merged_at")
            and pr.get("merge_commit_sha") == merge_sha
            and (pr.get("head") or {}).get("ref") == branch
            and (pr.get("base") or {}).get("ref") == "main"
            and ((pr.get("base") or {}).get("repo") or {}).get("full_name") == self.repository
            and ((pr.get("head") or {}).get("repo") or {}).get("full_name") == self.repository
        ]
        if len(matches) != 1:
            raise DeploymentReceiptError("pending_merge_attestation_unconfirmed")
        return resolve_pending_merge_request(
            rows,
            merge_sha=merge_sha,
            is_ancestor=is_ancestor,
            requested_run_id=run_id,
            attested_branch=branch,
            attested_branch_head_sha=matches[0]["head"]["sha"],
        )

    def dispatch(self, *, environment: str, merge_sha: str, action_id: str) -> DispatchReceipt:
        from filelock import FileLock, Timeout

        from modstore_server.maintenance_loop import store

        environment = _environment(environment)
        merge_sha = _merge_sha(merge_sha)
        path = store.ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(path) + ".deployment.lock", timeout=0):
                return self._dispatch_locked(environment, merge_sha, action_id)
        except Timeout as exc:
            raise DeploymentReceiptError("deployment_dispatch_busy") from exc

    def _dispatch_locked(self, environment: str, merge_sha: str, action_id: str) -> DispatchReceipt:
        from modstore_server.maintenance_loop import store

        binding = self._binding(environment, merge_sha, action_id)
        rows = self._ledger_rows()
        previous = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("event") in {"deploy_dispatch_intent", "deploy_dispatch_bound"}
            and row.get("action_id") == action_id
        ]
        if any(any(row.get(key) != value for key, value in binding.items()) for row in previous):
            raise DeploymentReceiptError("deployment_dispatch_binding_conflict")
        if previous:
            for row in reversed(previous):
                if row.get("event") == "deploy_dispatch_bound":
                    return DispatchReceipt(
                        str(row["workflow_run_id"]),
                        merge_sha,
                        environment,
                        action_id,
                        str(row.get("workflow_url") or ""),
                        str(row["controller_sha"]),
                    )
            receipt = self._find_dispatch(
                environment,
                merge_sha,
                action_id,
                str(previous[0]["controller_sha"]),
                require_descendant=True,
            )
            if receipt is None:
                raise DeploymentReceiptError("deployment_dispatch_outcome_unknown")
            return self._bind_dispatch(binding, receipt)

        ref_data = self._json(["gh", "api", f"repos/{self.repository}/commits/{self.ref}"])
        if not isinstance(ref_data, Mapping):
            raise DeploymentReceiptError("deploy_ref_not_at_merge_sha")
        controller_sha = _merge_sha(ref_data.get("sha"))
        if controller_sha != merge_sha:
            comparison = self._json(
                ["gh", "api", f"repos/{self.repository}/compare/{merge_sha}...{controller_sha}"]
            )
            if (
                not isinstance(comparison, Mapping)
                or comparison.get("status") != "ahead"
                or (comparison.get("merge_base_commit") or {}).get("sha") != merge_sha
            ):
                raise DeploymentReceiptError("deploy_ref_not_at_merge_sha")
        inputs = (
            self._production_inputs(merge_sha, action_id)
            if environment == "production"
            else {"release_sha": merge_sha}
        )
        # apply-latest must already refer to the expected artifact before it is
        # allowed to mutate the server. Post-deploy readback remains mandatory.
        manifest = self.fetch_release_identity(environment).require_complete("release_manifest")
        if manifest.git_sha != merge_sha:
            raise DeploymentReceiptError("release_manifest_sha_mismatch")
        existing = self._find_dispatch(environment, merge_sha, action_id, controller_sha)
        if existing is not None:
            return self._bind_dispatch(binding, existing)
        store._append_ledger(
            {
                **binding,
                "controller_sha": controller_sha,
                "event": "deploy_dispatch_intent",
                "phase": "deployment",
                "status": "submitting",
                "inputs": inputs,
            }
        )
        self._run(
            [
                "gh",
                "workflow",
                "run",
                self.workflow,
                "--repo",
                self.repository,
                "--ref",
                self.ref,
                "-f",
                f"environment={environment}",
                "-f",
                "action=apply-latest",
                "-f",
                f"action_id={action_id}",
                *(item for key, value in inputs.items() for item in ("-f", f"{key}={value}")),
            ]
        )
        deadline = time.monotonic() + self.capture_timeout_seconds
        while time.monotonic() < deadline:
            receipt = self._find_dispatch(
                environment, merge_sha, action_id, controller_sha, require_descendant=True
            )
            if receipt is not None:
                return self._bind_dispatch(binding, receipt)
            threading.Event().wait(self.poll_seconds)
        raise DeploymentReceiptError("workflow_run_capture_timeout")

    def _find_dispatch(
        self, environment, merge_sha, action_id, controller_sha, *, require_descendant=False
    ) -> DispatchReceipt | None:
        title = f"{Path(self.workflow).stem} {environment} apply-latest autonomy:{action_id}"
        matches = [row for row in self._runs() if row.get("displayTitle") == title]
        if len(matches) > 1:
            raise DeploymentReceiptError("deployment_dispatch_ambiguous")
        if not matches:
            return None
        row = matches[0]
        actual_sha = _merge_sha(row.get("headSha"))
        if row.get("headBranch") != self.ref:
            raise DeploymentReceiptError("deployment_dispatch_ref_mismatch")
        if actual_sha != controller_sha:
            # workflow_dispatch resolves a mutable branch after our preflight.
            # Bind the actual run only when its commit contains this release
            # and is still on the configured branch's authenticated ancestry.
            ref = self._json(["gh", "api", f"repos/{self.repository}/commits/{self.ref}"])
            if not isinstance(ref, Mapping):
                raise DeploymentReceiptError("deployment_controller_unverified")
            current = _merge_sha(ref.get("sha"))
            ancestry = [(merge_sha, actual_sha), (actual_sha, current)]
            if require_descendant:
                ancestry.append((controller_sha, actual_sha))
            for ancestor, descendant in ancestry:
                if ancestor == descendant:
                    continue
                comparison = self._json(
                    ["gh", "api", f"repos/{self.repository}/compare/{ancestor}...{descendant}"]
                )
                if (
                    not isinstance(comparison, Mapping)
                    or comparison.get("status") != "ahead"
                    or (comparison.get("merge_base_commit") or {}).get("sha") != ancestor
                ):
                    raise DeploymentReceiptError("deployment_controller_unverified")
        return DispatchReceipt(
            str(row.get("databaseId") or ""),
            merge_sha,
            environment,
            action_id,
            str(row.get("url") or ""),
            actual_sha,
        ).require_correlation(merge_sha=merge_sha, environment=environment)

    @staticmethod
    def _bind_dispatch(binding, receipt: DispatchReceipt) -> DispatchReceipt:
        from modstore_server.maintenance_loop import store

        store._append_ledger(
            {
                **binding,
                "event": "deploy_dispatch_bound",
                "phase": "deployment",
                "status": "accepted",
                "controller_sha": receipt.controller_sha,
                "workflow_run_id": receipt.workflow_run_id,
                "workflow_url": receipt.url,
            }
        )
        return receipt

    def _production_inputs(self, merge_sha: str, action_id: str) -> dict[str, str]:
        from modstore_server.maintenance_loop import config

        if (
            not config._env_bool("MODSTORE_SELF_MAINTENANCE_PRODUCTION_DEPLOY_ENABLED", False)
            or self.ref != "main"
            or self.workflow != "fhd-deploy.yml"
            or action_id != f"release:{merge_sha}"
            or len(merge_sha) != 40
        ):
            raise DeploymentReceiptError("production_deployment_not_authorized")
        payload = self._json(
            [
                "gh",
                "api",
                f"repos/{self.repository}/actions/workflows/fhd-security-full-scan.yml/runs"
                f"?head_sha={merge_sha}&branch=main&status=success&per_page=100",
            ]
        )
        runs = payload.get("workflow_runs") if isinstance(payload, Mapping) else None
        matches = [
            row
            for row in runs or []
            if isinstance(row, Mapping)
            and row.get("head_sha") == merge_sha
            and row.get("head_branch") == "main"
            and row.get("path") == ".github/workflows/fhd-security-full-scan.yml"
            and row.get("status") == "completed"
            and row.get("conclusion") == "success"
            and type(row.get("id")) is int
            and row["id"] > 0
        ]
        if not matches:
            raise DeploymentReceiptError("release_security_scan_unavailable")
        scan_id = str(max(matches, key=lambda row: row["id"])["id"])
        verifier = self.repo_root / "FHD/scripts/security/verify_security_scan_pair.py"
        if not verifier.is_file():
            raise DeploymentReceiptError("release_security_verifier_unavailable")
        with tempfile.TemporaryDirectory(prefix="maintenance-release-scan-") as directory:
            self._run(
                [
                    "gh",
                    "run",
                    "download",
                    scan_id,
                    "--repo",
                    self.repository,
                    "--name",
                    "xcagi-security-release-reports",
                    "--dir",
                    directory,
                ]
            )
            clearance = self._json(
                [
                    sys.executable,
                    str(verifier),
                    "--current-dir",
                    directory,
                    "--release-sha",
                    merge_sha,
                ]
            )
            if (
                not isinstance(clearance, Mapping)
                or clearance.get("passed") is not True
                or clearance.get("release_sha") != merge_sha
            ):
                raise DeploymentReceiptError("release_security_clearance_unverified")
        # The protected workflow still performs its own exact-SHA security,
        # GitHub environment and original approval-ledger checks.
        return {
            "release_sha": merge_sha,
            "security_scan_run_id": scan_id,
            "previous_security_scan_run_id": scan_id,
        }

    def wait_for_success(self, receipt: DispatchReceipt) -> WorkflowCompletion:
        deadline = time.monotonic() + self.workflow_timeout_seconds
        while time.monotonic() < deadline:
            payload = self._json(
                [
                    "gh",
                    "run",
                    "view",
                    receipt.workflow_run_id,
                    "--repo",
                    self.repository,
                    "--json",
                    "databaseId,headSha,status,conclusion,url",
                ]
            )
            if not isinstance(payload, Mapping):
                raise DeploymentReceiptError("github_run_view_invalid")
            completed = WorkflowCompletion(
                str(payload.get("databaseId") or ""),
                _sha(payload.get("headSha")),
                str(payload.get("status") or ""),
                str(payload.get("conclusion") or ""),
                str(payload.get("url") or receipt.url),
            )
            if completed.status.lower() == "completed":
                return completed.require_success(receipt)
            threading.Event().wait(self.poll_seconds)
        raise DeploymentReceiptError("workflow_completion_timeout")

    @staticmethod
    def _fetch(url: str) -> BuildIdentity:
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True, trust_env=False) as client:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
        except RECOVERABLE_ERRORS as exc:
            raise DeploymentReceiptError("identity_fetch_failed") from exc
        if not isinstance(payload, Mapping):
            raise DeploymentReceiptError("identity_payload_invalid")
        return BuildIdentity.from_payload(payload)

    def fetch_release_identity(self, environment: str) -> BuildIdentity:
        environment = _environment(environment)
        key = f"MODSTORE_SELF_MAINTENANCE_{environment.upper()}_RELEASE_URL"
        return self._fetch(str(os.environ.get(key) or self.RELEASE_URLS[environment]))

    def fetch_health_identity(self, environment: str) -> BuildIdentity:
        environment = _environment(environment)
        key = f"MODSTORE_SELF_MAINTENANCE_{environment.upper()}_HEALTH_URL"
        return self._fetch(str(os.environ.get(key) or self.HEALTH_URLS[environment]))
