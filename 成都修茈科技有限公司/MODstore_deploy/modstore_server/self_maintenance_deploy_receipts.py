# mypy: disable-error-code="arg-type, attr-defined, no-any-return, valid-type"
# isort: skip_file
"""Fail-closed deployment receipts for self-maintenance runs.

A successful workflow dispatch command is only acceptance. A deployment is
verified only when the exact workflow run succeeds and the release manifest
and health endpoint expose the merge SHA and the same artifact digest.
"""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Protocol

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
    def from_payload(cls, payload: Mapping[str, Any]) -> BuildIdentity:
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

    def require_complete(self, source: str) -> BuildIdentity:
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

    def require_correlation(self, *, merge_sha: str, environment: str) -> DispatchReceipt:
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

    def require_success(self, receipt: DispatchReceipt) -> WorkflowCompletion:
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
        except RECOVERABLE_ERRORS:
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
            except RECOVERABLE_ERRORS:
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


from modstore_server.self_maintenance_receipt_recording import (  # noqa: E402
    record_completed_deployment_receipt as record_completed_deployment_receipt,
)


from modstore_server.self_maintenance_gh_gateway import (  # noqa: E402
    GhActionsDeploymentGateway as GhActionsDeploymentGateway,
)

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
