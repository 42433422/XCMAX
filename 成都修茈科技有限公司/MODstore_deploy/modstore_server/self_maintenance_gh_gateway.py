"""GitHub Actions and HTTP deployment receipt gateway."""

from __future__ import annotations

import json
import os
import subprocess
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
        payload = self._json(
            [
                "gh",
                "run",
                "list",
                "--repo",
                self.repository,
                "--workflow",
                self.workflow,
                "--event",
                "workflow_dispatch",
                "--limit",
                "50",
                "--json",
                "databaseId,headSha,status,conclusion,displayTitle,url",
            ]
        )
        if not isinstance(payload, list):
            raise DeploymentReceiptError("github_run_list_invalid")
        return [dict(row) for row in payload if isinstance(row, Mapping)]

    def dispatch(self, *, environment: str, merge_sha: str, action_id: str) -> DispatchReceipt:
        environment = _environment(environment)
        merge_sha = _merge_sha(merge_sha)
        ref_data = self._json(["gh", "api", f"repos/{self.repository}/commits/{self.ref}"])
        if not isinstance(ref_data, Mapping) or _sha(ref_data.get("sha")) != merge_sha:
            raise DeploymentReceiptError("deploy_ref_not_at_merge_sha")
        baseline = {str(row.get("databaseId") or "") for row in self._runs()}
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
            ]
        )
        deadline = time.monotonic() + self.capture_timeout_seconds
        while time.monotonic() < deadline:
            for row in self._runs():
                workflow_id = str(row.get("databaseId") or "")
                title = str(row.get("displayTitle") or "")
                if (
                    workflow_id
                    and workflow_id not in baseline
                    and _sha(row.get("headSha")) == merge_sha
                    and action_id in title
                    and environment in title.lower()
                ):
                    return DispatchReceipt(
                        workflow_id,
                        merge_sha,
                        environment,
                        action_id,
                        str(row.get("url") or ""),
                    )
            threading.Event().wait(self.poll_seconds)
        raise DeploymentReceiptError("workflow_run_capture_timeout")

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
