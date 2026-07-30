"""Fail-closed deployment receipts for self-maintenance runs.

A successful workflow dispatch command is only acceptance. A deployment is
verified only when the exact workflow run succeeds and the release manifest
and health endpoint expose the merge SHA and the same artifact digest.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Protocol, Sequence

import httpx

from modstore_server.deployment_receipt_history import completed_receipt

_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_ARTIFACT_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENVIRONMENTS = frozenset({"staging", "production"})


class DeploymentReceiptError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _sha(value: Any) -> str:
    return str(value or "").strip().lower()


def _merge_sha(value: Any) -> str:
    value = _sha(value)
    if not _COMMIT_RE.fullmatch(value):
        raise DeploymentReceiptError("invalid_merge_sha")
    return value


def _environment(value: Any) -> str:
    value = str(value or "").strip().lower()
    if value not in _ENVIRONMENTS:
        raise DeploymentReceiptError("unsupported_environment")
    return value


@dataclass(frozen=True)
class BuildIdentity:
    git_sha: str
    artifact_sha256: str = ""
    image_digest: str = ""

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "BuildIdentity":
        root: Mapping[str, Any] = payload
        data = root.get("data")
        if isinstance(data, Mapping):
            root = data
        build = root.get("build")
        if isinstance(build, Mapping):
            root = build
        return cls(
            git_sha=_sha(root.get("git_sha")),
            artifact_sha256=str(root.get("artifact_sha256") or root.get("sha256") or "")
            .strip()
            .lower(),
            image_digest=str(root.get("image_digest") or "").strip().lower(),
        )

    def require_complete(self, source: str) -> "BuildIdentity":
        if not _COMMIT_RE.fullmatch(self.git_sha):
            raise DeploymentReceiptError(f"{source}_missing_git_sha")
        if not (
            _ARTIFACT_RE.fullmatch(self.artifact_sha256) or _IMAGE_RE.fullmatch(self.image_digest)
        ):
            raise DeploymentReceiptError(f"{source}_missing_artifact_digest")
        return self


@dataclass(frozen=True)
class DispatchReceipt:
    workflow_run_id: str
    head_sha: str
    environment: str
    action_id: str
    url: str = ""

    def require_correlation(self, *, merge_sha: str, environment: str) -> "DispatchReceipt":
        if not str(self.workflow_run_id or "").strip():
            raise DeploymentReceiptError("dispatch_missing_workflow_run_id")
        if _sha(self.head_sha) != merge_sha:
            raise DeploymentReceiptError("dispatch_head_sha_mismatch")
        if str(self.environment or "").lower() != environment:
            raise DeploymentReceiptError("dispatch_environment_mismatch")
        return self


@dataclass(frozen=True)
class WorkflowCompletion:
    workflow_run_id: str
    head_sha: str
    status: str
    conclusion: str
    url: str = ""

    def require_success(self, receipt: DispatchReceipt) -> "WorkflowCompletion":
        if str(self.workflow_run_id) != str(receipt.workflow_run_id):
            raise DeploymentReceiptError("workflow_run_id_mismatch")
        if _sha(self.head_sha) != _sha(receipt.head_sha):
            raise DeploymentReceiptError("workflow_head_sha_mismatch")
        if str(self.status or "").lower() != "completed":
            raise DeploymentReceiptError("workflow_not_completed")
        if str(self.conclusion or "").lower() != "success":
            raise DeploymentReceiptError("workflow_not_successful")
        return self


class DeploymentReceiptGateway(Protocol):
    def dispatch(self, *, environment: str, merge_sha: str, action_id: str) -> DispatchReceipt: ...

    def wait_for_success(self, receipt: DispatchReceipt) -> WorkflowCompletion: ...

    def fetch_release_identity(self, environment: str) -> BuildIdentity: ...

    def fetch_health_identity(self, environment: str) -> BuildIdentity: ...


def verify_deployed_identity(
    *, merge_sha: str, release: BuildIdentity, health: BuildIdentity
) -> Dict[str, str]:
    expected = _merge_sha(merge_sha)
    release.require_complete("release_manifest")
    health.require_complete("health")
    if release.git_sha != expected:
        raise DeploymentReceiptError("release_manifest_sha_mismatch")
    if health.git_sha != expected:
        raise DeploymentReceiptError("health_sha_mismatch")
    if release.artifact_sha256:
        if health.artifact_sha256 != release.artifact_sha256:
            raise DeploymentReceiptError("health_artifact_digest_mismatch")
        return {
            "git_sha": expected,
            "artifact_sha256": release.artifact_sha256,
            "image_digest": "",
        }
    if health.image_digest != release.image_digest:
        raise DeploymentReceiptError("health_image_digest_mismatch")
    return {
        "git_sha": expected,
        "artifact_sha256": "",
        "image_digest": release.image_digest,
    }


EventSink = Callable[[Dict[str, Any]], None]
AncestorCheck = Callable[[str, str], bool]


def _deploy_one(
    *,
    gateway: DeploymentReceiptGateway,
    record_event: EventSink,
    run_id: str,
    merge_sha: str,
    environment: str,
) -> Dict[str, Any]:
    action_id = f"loop:{run_id}:deploy:{environment}:{merge_sha[:12]}"
    receipt: DispatchReceipt | None = None
    try:
        receipt = gateway.dispatch(
            environment=environment, merge_sha=merge_sha, action_id=action_id
        ).require_correlation(merge_sha=merge_sha, environment=environment)
        correlation = {
            "run_id": run_id,
            "merge_sha": merge_sha,
            "environment": environment,
            "workflow_run_id": str(receipt.workflow_run_id),
            "action_id": action_id,
        }
        record_event(
            {
                **correlation,
                "event": "deploy_dispatch",
                "phase": "deployment",
                "status": "accepted",
                "ok": True,
                "verification_state": "pending",
                "workflow_url": receipt.url,
            }
        )
        gateway.wait_for_success(receipt).require_success(receipt)
        identity = verify_deployed_identity(
            merge_sha=merge_sha,
            release=gateway.fetch_release_identity(environment),
            health=gateway.fetch_health_identity(environment),
        )
        record_event(
            {
                **correlation,
                **identity,
                "event": "post_deploy_verified",
                "phase": "deployment",
                "status": "verified",
                "ok": True,
                "identity_verified": True,
                "workflow_url": receipt.url,
            }
        )
        return {"ok": True, "verified": True, **correlation, **identity}
    except DeploymentReceiptError as exc:
        failed: Dict[str, Any] = {
            "run_id": run_id,
            "merge_sha": merge_sha,
            "environment": environment,
            "event": "deploy_verification_failed",
            "phase": "deployment",
            "status": "failed",
            "ok": False,
            "reason": exc.reason,
        }
        if receipt is not None:
            failed.update(
                workflow_run_id=str(receipt.workflow_run_id),
                action_id=receipt.action_id,
                workflow_url=receipt.url,
            )
        record_event(failed)
        return {
            "ok": False,
            "verified": False,
            "reason": exc.reason,
            "workflow_run_id": str(receipt.workflow_run_id) if receipt else "",
        }


def run_staged_deployment_chain(
    *,
    gateway: DeploymentReceiptGateway,
    record_event: EventSink,
    run_id: str,
    merge_sha: str,
    allow_production: bool = False,
) -> Dict[str, Any]:
    """Staging first; production is opt-in and cannot bypass verification."""

    run_id = str(run_id or "").strip()
    if not run_id:
        raise DeploymentReceiptError("missing_self_maintenance_run_id")
    merge_sha = _merge_sha(merge_sha)
    staging = _deploy_one(
        gateway=gateway,
        record_event=record_event,
        run_id=run_id,
        merge_sha=merge_sha,
        environment="staging",
    )
    result: Dict[str, Any] = {
        "ok": bool(staging.get("verified")),
        "run_id": run_id,
        "merge_sha": merge_sha,
        "staging": staging,
        "staging_verified": bool(staging.get("verified")),
        "production_attempted": False,
        "production_enabled": bool(allow_production),
    }
    if not allow_production:
        result["production"] = {"ok": False, "reason": "production_disabled"}
        return result
    if not staging.get("verified"):
        record_event(
            {
                "run_id": run_id,
                "merge_sha": merge_sha,
                "environment": "production",
                "event": "deploy_dispatch_blocked",
                "phase": "deployment",
                "status": "blocked",
                "ok": False,
                "reason": "staging_not_verified",
            }
        )
        result["production"] = {"ok": False, "reason": "staging_not_verified"}
        return result
    production = _deploy_one(
        gateway=gateway,
        record_event=record_event,
        run_id=run_id,
        merge_sha=merge_sha,
        environment="production",
    )
    result.update(
        ok=bool(production.get("verified")),
        production=production,
        production_attempted=True,
    )
    return result


def correlated_verified_deploys(
    rows: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Only exact run/SHA/environment/workflow pairs are scoreable."""

    rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    dispatched: set[tuple[str, str, str, str]] = set()
    for row in rows:
        if (
            row.get("event") == "deploy_dispatch"
            and row.get("ok") is True
            and str(row.get("status") or "").lower() == "accepted"
        ):
            key = (
                str(row.get("run_id") or ""),
                _sha(row.get("merge_sha")),
                str(row.get("environment") or "").lower(),
                str(row.get("workflow_run_id") or ""),
            )
            if all(key) and _COMMIT_RE.fullmatch(key[1]):
                dispatched.add(key)
    verified: List[Dict[str, Any]] = []
    for row in rows:
        if (
            row.get("event") != "post_deploy_verified"
            or row.get("ok") is not True
            or row.get("identity_verified") is not True
            or str(row.get("status") or "").lower() != "verified"
        ):
            continue
        key = (
            str(row.get("run_id") or ""),
            _sha(row.get("merge_sha")),
            str(row.get("environment") or "").lower(),
            str(row.get("workflow_run_id") or ""),
        )
        if key in dispatched:
            verified.append(row)
    return verified


def resolve_pending_merge_request(
    rows: Iterable[Mapping[str, Any]],
    *,
    merge_sha: str,
    is_ancestor: AncestorCheck,
    requested_run_id: str = "",
    attested_branch: str = "",
    attested_branch_head_sha: str = "",
) -> Dict[str, Any]:
    """Resolve one pending loop merge by exact Git ancestry.

    The remote Para worker performs a normal Git merge on the base branch.  A
    self-maintenance request is therefore correlated only when its reviewed
    branch head is an ancestor of the deployed merge commit.  Zero or multiple
    matches remain unscoreable instead of being guessed from timestamps.
    """

    merge_sha = _merge_sha(merge_sha)
    requested_run_id = str(requested_run_id or "").strip()
    normalized = [dict(row) for row in rows if isinstance(row, Mapping)]
    terminal_run_ids = {
        str(row.get("run_id") or "").strip()
        for row in normalized
        if row.get("event") == "merge_completed" and row.get("ok") is True
    }
    pending_by_run: Dict[str, Dict[str, Any]] = {}
    for row in normalized:
        run_id = str(row.get("run_id") or "").strip()
        if (
            row.get("event") != "merge_requested"
            or row.get("ok") is not True
            or str(row.get("status") or "").lower() != "pending"
            or not run_id
            or run_id in terminal_run_ids
        ):
            continue
        if requested_run_id and run_id != requested_run_id:
            continue
        pending_by_run[run_id] = row

    matches: List[Dict[str, Any]] = []
    for row in pending_by_run.values():
        branch_head = _sha(row.get("branch_head_sha"))
        if not _COMMIT_RE.fullmatch(branch_head):
            continue
        try:
            matched = bool(is_ancestor(branch_head, merge_sha))
        except Exception:
            matched = False
        if matched:
            matches.append(row)
    if len(matches) > 1:
        raise DeploymentReceiptError("pending_merge_ambiguous")
    if matches:
        return matches[0]

    # Protected GitHub branches may squash a reviewed PR, so its final head is
    # not an ancestor of the deployed commit.  The receipt workflow supplies a
    # GitHub API attestation for the unique PR associated with that exact
    # deployed commit.  This fallback is deliberately available only when the
    # trusted workflow also carries the exact requested run id and branch.
    attested_branch = str(attested_branch or "").strip()
    attested_head = _sha(attested_branch_head_sha)
    if not requested_run_id or not attested_branch or not _COMMIT_RE.fullmatch(attested_head):
        raise DeploymentReceiptError("pending_merge_not_found")

    attested_matches: List[Dict[str, Any]] = []
    for row in pending_by_run.values():
        if str(row.get("run_id") or "").strip() != requested_run_id:
            continue
        if str(row.get("branch") or "").strip() != attested_branch:
            continue
        requested_head = _sha(row.get("branch_head_sha"))
        if _COMMIT_RE.fullmatch(requested_head) and requested_head != attested_head:
            try:
                head_advanced = bool(is_ancestor(requested_head, attested_head))
            except Exception:
                head_advanced = False
            if not head_advanced:
                continue
        attested_matches.append(
            {
                **row,
                "branch_head_sha": attested_head,
                "head_verification": "github_pr_attestation",
                "requested_branch_head_sha": requested_head,
            }
        )
    if not attested_matches:
        raise DeploymentReceiptError("pending_merge_not_found")
    if len(attested_matches) != 1:
        raise DeploymentReceiptError("pending_merge_ambiguous")
    return attested_matches[0]


def record_completed_deployment_receipt(
    *,
    rows: Iterable[Mapping[str, Any]],
    record_event: EventSink,
    merge_sha: str,
    environment: str,
    workflow_run_id: str,
    workflow_status: str,
    workflow_conclusion: str,
    release: BuildIdentity,
    health: BuildIdentity,
    is_ancestor: AncestorCheck,
    requested_run_id: str = "",
    attested_branch: str = "",
    attested_branch_head_sha: str = "",
    attested_pr_number: str = "",
    workflow_url: str = "",
    action_id: str = "",
    observed_at: str = "",
) -> Dict[str, Any]:
    """Record an authenticated workflow completion against one pending loop.

    GitHub's callback is only an execution attestation.  The deployed release
    and health identities are independently read by the server and must expose
    the same exact merge SHA and artifact digest before any scoreable rows are
    appended.
    """

    normalized_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    merge_sha = _merge_sha(merge_sha)
    environment = _environment(environment)
    workflow_run_id = str(workflow_run_id or "").strip()
    if not workflow_run_id:
        raise DeploymentReceiptError("dispatch_missing_workflow_run_id")
    if str(workflow_status or "").strip().lower() != "completed":
        raise DeploymentReceiptError("workflow_not_completed")
    if str(workflow_conclusion or "").strip().lower() != "success":
        raise DeploymentReceiptError("workflow_not_successful")

    existing = completed_receipt(
        normalized_rows,
        merge_sha=merge_sha,
        environment=environment,
        workflow_run_id=workflow_run_id,
        requested_run_id=requested_run_id,
    )
    if existing is not None:
        previous_workflow_run_id = str(existing.get("workflow_run_id") or "")
        if previous_workflow_run_id != workflow_run_id:
            # A second successful deployment for the same loop/SHA is a valid
            # idempotent retry, but it must still expose the exact runtime
            # identity before the new workflow may be acknowledged.
            verify_deployed_identity(merge_sha=merge_sha, release=release, health=health)
        run_id = str(existing.get("run_id") or "")
        merge_recorded = any(
            row.get("event") == "merge_completed"
            and row.get("ok") is True
            and str(row.get("run_id") or "") == run_id
            and _sha(row.get("merge_sha")) == merge_sha
            for row in normalized_rows
        )
        if not merge_recorded:
            record_event(
                {
                    **existing,
                    "event": "merge_completed",
                    "phase": "merge",
                    "status": "completed_merged",
                    "ok": True,
                }
            )
        return {
            "ok": True,
            "recorded": False,
            "idempotent": True,
            "run_id": run_id,
            "merge_sha": merge_sha,
            "environment": environment,
            "workflow_run_id": workflow_run_id,
            "previous_workflow_run_id": previous_workflow_run_id,
        }

    pending = resolve_pending_merge_request(
        normalized_rows,
        merge_sha=merge_sha,
        is_ancestor=is_ancestor,
        requested_run_id=requested_run_id,
        attested_branch=attested_branch,
        attested_branch_head_sha=attested_branch_head_sha,
    )
    identity = verify_deployed_identity(merge_sha=merge_sha, release=release, health=health)
    run_id = str(pending.get("run_id") or "").strip()
    branch_head_sha = _sha(pending.get("branch_head_sha"))
    action_id = str(action_id or "").strip() or (
        f"loop:{run_id}:deploy:{environment}:{merge_sha[:12]}"
    )
    correlation: Dict[str, Any] = {
        "action_id": action_id,
        "attested_pr_number": str(attested_pr_number or "").strip(),
        "branch": str(pending.get("branch") or ""),
        "branch_head_sha": branch_head_sha,
        "created_at": str(observed_at or ""),
        "environment": environment,
        "merge_sha": merge_sha,
        "para_task_id": str(pending.get("para_task_id") or ""),
        "head_verification": str(pending.get("head_verification") or "git_ancestry"),
        "run_id": run_id,
        "workflow_run_id": workflow_run_id,
        "workflow_url": str(workflow_url or ""),
    }
    events = [
        {
            **correlation,
            "event": "deploy_dispatch",
            "phase": "deployment",
            "status": "accepted",
            "ok": True,
            "verification_state": "completed",
        },
        {
            **correlation,
            **identity,
            "event": "post_deploy_verified",
            "phase": "deployment",
            "status": "verified",
            "ok": True,
            "identity_verified": True,
        },
        {
            **correlation,
            "event": "merge_completed",
            "phase": "merge",
            "status": "completed_merged",
            "ok": True,
        },
    ]
    for event in events:
        record_event(event)
    return {
        "ok": True,
        "recorded": True,
        "idempotent": False,
        "run_id": run_id,
        "merge_sha": merge_sha,
        "environment": environment,
        "workflow_run_id": workflow_run_id,
        **identity,
    }


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
    def from_environment(cls, *, repo_root: Path, ref: str) -> "GhActionsDeploymentGateway":
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
        except Exception as exc:
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


__all__ = [
    "BuildIdentity",
    "DeploymentReceiptError",
    "DispatchReceipt",
    "GhActionsDeploymentGateway",
    "WorkflowCompletion",
    "correlated_verified_deploys",
    "record_completed_deployment_receipt",
    "resolve_pending_merge_request",
    "run_staged_deployment_chain",
    "verify_deployed_identity",
]
