from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass, field

import pytest

from modstore_server import (
    models,
    self_maintenance_loop_api,
    self_maintenance_loop_runner,
)
from modstore_server.self_maintenance_deploy_receipts import (
    BuildIdentity,
    DeploymentReceiptError,
    DispatchReceipt,
    WorkflowCompletion,
    correlated_verified_deploys,
    record_completed_deployment_receipt,
    resolve_pending_merge_request,
    run_staged_deployment_chain,
)
from modstore_server.self_maintenance_loop_api import _deployment_receipt_token_valid

MERGE_SHA = "a" * 40
ARTIFACT_SHA = "b" * 64


def test_loop_runner_deployment_receipts_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_DEPLOY_RECEIPTS_ENABLED", raising=False)

    result = self_maintenance_loop_runner._run_deploy_receipts_after_merge(
        run_id="run-disabled",
        merge_result={"ok": True, "merge_commit_sha": MERGE_SHA},
    )

    assert result == {"enabled": False, "reason": "deploy_receipts_disabled"}


def test_deployment_receipt_callback_requires_exact_shared_token(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_OPS_INGEST_TOKEN", "expected-token")

    assert _deployment_receipt_token_valid("Bearer expected-token", None) is True
    assert _deployment_receipt_token_valid(None, "expected-token") is True
    assert _deployment_receipt_token_valid("Bearer wrong-token", None) is False
    assert _deployment_receipt_token_valid(None, None) is False


def test_git_is_ancestor_fetches_missing_exact_commit_before_compare(tmp_path, monkeypatch) -> None:
    ancestor = "c" * 40
    descendant = "d" * 40
    calls: list[list[str]] = []
    return_codes = iter([1, 0, 0, 0, 0])

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=next(return_codes))

    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(self_maintenance_loop_api.subprocess, "run", fake_run)

    assert self_maintenance_loop_api._git_is_ancestor(ancestor, descendant) is True
    assert calls == [
        ["git", "-C", str(tmp_path), "cat-file", "-e", f"{ancestor}^{{commit}}"],
        [
            "git",
            "-C",
            str(tmp_path),
            "fetch",
            "--quiet",
            "--no-tags",
            "origin",
            ancestor,
        ],
        ["git", "-C", str(tmp_path), "cat-file", "-e", f"{ancestor}^{{commit}}"],
        ["git", "-C", str(tmp_path), "cat-file", "-e", f"{descendant}^{{commit}}"],
        [
            "git",
            "-C",
            str(tmp_path),
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
        ],
    ]


def test_only_verified_production_receipt_credits_release_officer(tmp_path, monkeypatch) -> None:
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "deploy-receipt.sqlite"))
    models.init_db()
    sf = models.get_session_factory()
    with sf() as session:
        session.add(
            models.User(
                username="deploy_admin",
                password_hash="x",
                email="deploy@example.com",
                is_admin=True,
            )
        )
        session.commit()

    base = {
        "event": "post_deploy_verified",
        "environment": "production",
        "ok": True,
        "identity_verified": True,
        "status": "verified",
        "run_id": "self-maintenance-123",
        "merge_sha": MERGE_SHA,
        "workflow_run_id": "98765",
    }
    assert self_maintenance_loop_runner._record_verified_deploy_employee_metric(base) is True
    assert self_maintenance_loop_runner._record_verified_deploy_employee_metric(base) is False
    assert (
        self_maintenance_loop_runner._record_verified_deploy_employee_metric(
            {**base, "environment": "staging", "workflow_run_id": "98766"}
        )
        is False
    )

    with sf() as session:
        rows = (
            session.query(models.EmployeeExecutionMetric)
            .filter(models.EmployeeExecutionMetric.employee_id == "deploy-release-officer")
            .all()
        )
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert MERGE_SHA[:12] in rows[0].task
    models._engine = None
    models._SessionFactory = None


def test_deployment_receipt_callback_routes_verified_event_to_employee_metric(
    monkeypatch,
) -> None:
    events: list[dict] = []
    metric_events: list[dict] = []
    monkeypatch.setenv("MODSTORE_OPS_INGEST_TOKEN", "receipt-token")
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_api._release_manifest_payload",
        lambda: {"git_sha": MERGE_SHA, "artifact_sha256": ARTIFACT_SHA},
    )
    monkeypatch.setattr(
        "modstore_server.deploy_context.health_payload",
        lambda: {"git_sha": MERGE_SHA, "artifact_sha256": ARTIFACT_SHA},
    )
    monkeypatch.setattr(self_maintenance_loop_runner, "_append_ledger", events.append)
    monkeypatch.setattr(self_maintenance_loop_runner, "_append_governance_audit", lambda _e: None)
    monkeypatch.setattr(
        self_maintenance_loop_runner,
        "_record_verified_deploy_employee_metric",
        lambda event: metric_events.append(dict(event)) or True,
    )
    monkeypatch.setattr(self_maintenance_loop_runner, "_read_ledger", lambda limit=5000: [])

    callback_kwargs: dict = {}

    def fake_record_completed_deployment_receipt(**kwargs):
        callback_kwargs.update(kwargs)
        event = {
            "event": "post_deploy_verified",
            "environment": "production",
            "ok": True,
            "identity_verified": True,
            "status": "verified",
            "run_id": "self-maintenance-123",
            "merge_sha": MERGE_SHA,
            "workflow_run_id": "98765",
        }
        kwargs["record_event"](event)
        return {"recorded": True, "run_id": event["run_id"]}

    monkeypatch.setattr(
        "modstore_server.self_maintenance_deploy_receipts.record_completed_deployment_receipt",
        fake_record_completed_deployment_receipt,
    )

    result = asyncio.run(
        self_maintenance_loop_api.record_self_maintenance_deployment_receipt(
            body={
                "merge_sha": MERGE_SHA,
                "environment": "production",
                "workflow_run_id": "98765",
                "workflow_status": "completed",
                "workflow_conclusion": "success",
                "attested_branch": "devfleet/run-receipt",
                "attested_branch_head_sha": "c" * 40,
                "attested_pr_number": "559",
            },
            authorization=None,
            x_autonomy_token="receipt-token",
        )
    )

    assert result["recorded"] is True
    assert len(events) == 1
    assert metric_events == [events[0]]
    assert callback_kwargs["attested_branch"] == "devfleet/run-receipt"
    assert callback_kwargs["attested_branch_head_sha"] == "c" * 40
    assert callback_kwargs["attested_pr_number"] == "559"


@dataclass
class FakeGateway:
    conclusions: dict[str, str] = field(
        default_factory=lambda: {"staging": "success", "production": "success"}
    )
    health_sha: str = MERGE_SHA
    health_artifact: str = ARTIFACT_SHA
    dispatches: list[str] = field(default_factory=list)

    def dispatch(self, *, environment: str, merge_sha: str, action_id: str) -> DispatchReceipt:
        self.dispatches.append(environment)
        return DispatchReceipt(
            workflow_run_id=f"workflow-{environment}",
            head_sha=merge_sha,
            environment=environment,
            action_id=action_id,
            url=f"https://example.invalid/{environment}",
        )

    def wait_for_success(self, receipt: DispatchReceipt) -> WorkflowCompletion:
        return WorkflowCompletion(
            workflow_run_id=receipt.workflow_run_id,
            head_sha=receipt.head_sha,
            status="completed",
            conclusion=self.conclusions[receipt.environment],
        )

    def fetch_release_identity(self, environment: str) -> BuildIdentity:
        return BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA)

    def fetch_health_identity(self, environment: str) -> BuildIdentity:
        return BuildIdentity(
            git_sha=self.health_sha,
            artifact_sha256=self.health_artifact,
        )


def test_dispatch_accepted_is_not_deploy_verified() -> None:
    events: list[dict] = []
    gateway = FakeGateway(conclusions={"staging": "failure", "production": "success"})

    result = run_staged_deployment_chain(
        gateway=gateway,
        record_event=events.append,
        run_id="run-accepted-only",
        merge_sha=MERGE_SHA,
    )

    assert result["staging_verified"] is False
    assert gateway.dispatches == ["staging"]
    assert [event["event"] for event in events] == [
        "deploy_dispatch",
        "deploy_verification_failed",
    ]
    assert correlated_verified_deploys(events) == []


def test_staging_failure_blocks_production_even_when_enabled() -> None:
    events: list[dict] = []
    gateway = FakeGateway(conclusions={"staging": "failure", "production": "success"})

    result = run_staged_deployment_chain(
        gateway=gateway,
        record_event=events.append,
        run_id="run-stage-failed",
        merge_sha=MERGE_SHA,
        allow_production=True,
    )

    assert result["production_attempted"] is False
    assert result["production"]["reason"] == "staging_not_verified"
    assert gateway.dispatches == ["staging"]
    assert events[-1]["event"] == "deploy_dispatch_blocked"
    assert events[-1]["environment"] == "production"


def test_verified_receipt_has_exact_same_run_sha_environment_and_workflow() -> None:
    events: list[dict] = []
    gateway = FakeGateway()

    result = run_staged_deployment_chain(
        gateway=gateway,
        record_event=events.append,
        run_id="run-correlated",
        merge_sha=MERGE_SHA,
    )

    assert result["staging_verified"] is True
    dispatch, verified = events
    keys = ("run_id", "merge_sha", "environment", "workflow_run_id", "action_id")
    assert {key: dispatch[key] for key in keys} == {key: verified[key] for key in keys}
    assert verified["artifact_sha256"] == ARTIFACT_SHA
    assert correlated_verified_deploys(events) == [verified]


def test_unrelated_verification_event_does_not_become_scoreable() -> None:
    events: list[dict] = []
    run_staged_deployment_chain(
        gateway=FakeGateway(),
        record_event=events.append,
        run_id="run-one",
        merge_sha=MERGE_SHA,
    )
    dispatch = events[0]
    unrelated = {
        **events[1],
        "run_id": "run-two",
        "workflow_run_id": "workflow-other",
    }

    assert correlated_verified_deploys([dispatch, unrelated]) == []


def test_health_artifact_mismatch_keeps_deployment_unverified() -> None:
    events: list[dict] = []
    gateway = FakeGateway(health_artifact="c" * 64)

    result = run_staged_deployment_chain(
        gateway=gateway,
        record_event=events.append,
        run_id="run-bad-artifact",
        merge_sha=MERGE_SHA,
    )

    assert result["staging_verified"] is False
    assert events[-1]["reason"] == "health_artifact_digest_mismatch"
    assert correlated_verified_deploys(events) == []


def _pending(run_id: str, branch_head_sha: str) -> dict:
    return {
        "event": "merge_requested",
        "ok": True,
        "status": "pending",
        "run_id": run_id,
        "branch": f"devfleet/{run_id}",
        "branch_head_sha": branch_head_sha,
        "para_task_id": f"task-{run_id}",
    }


def test_completed_workflow_records_exact_merge_dispatch_and_verified_identity() -> None:
    events: list[dict] = []
    branch_head = "c" * 40

    result = record_completed_deployment_receipt(
        rows=[_pending("run-callback", branch_head)],
        record_event=events.append,
        merge_sha=MERGE_SHA,
        environment="production",
        workflow_run_id="12345",
        workflow_status="completed",
        workflow_conclusion="success",
        release=BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA),
        health=BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA),
        is_ancestor=lambda ancestor, descendant: (
            ancestor == branch_head and descendant == MERGE_SHA
        ),
        workflow_url="https://example.invalid/actions/runs/12345",
        observed_at="2026-07-23T00:00:00+00:00",
    )

    assert result["recorded"] is True
    assert result["run_id"] == "run-callback"
    assert [row["event"] for row in events] == [
        "deploy_dispatch",
        "post_deploy_verified",
        "merge_completed",
    ]
    assert events[-1]["status"] == "completed_merged"
    assert correlated_verified_deploys(events) == [events[1]]


def test_unrelated_production_deploy_does_not_claim_a_pending_loop() -> None:
    with pytest.raises(DeploymentReceiptError, match="pending_merge_not_found"):
        resolve_pending_merge_request(
            [_pending("run-unrelated", "c" * 40)],
            merge_sha=MERGE_SHA,
            is_ancestor=lambda _ancestor, _descendant: False,
        )


def test_squash_merge_uses_exact_github_pr_attestation_for_requested_run() -> None:
    pending = _pending("run-squash", "")
    attested_head = "d" * 40

    resolved = resolve_pending_merge_request(
        [pending],
        merge_sha=MERGE_SHA,
        is_ancestor=lambda _ancestor, _descendant: False,
        requested_run_id="run-squash",
        attested_branch="devfleet/run-squash",
        attested_branch_head_sha=attested_head,
    )

    assert resolved["run_id"] == "run-squash"
    assert resolved["branch_head_sha"] == attested_head
    assert resolved["head_verification"] == "github_pr_attestation"


def test_squash_attestation_fails_closed_without_exact_run_and_branch() -> None:
    pending = _pending("run-squash", "")

    with pytest.raises(DeploymentReceiptError, match="pending_merge_not_found"):
        resolve_pending_merge_request(
            [pending],
            merge_sha=MERGE_SHA,
            is_ancestor=lambda _ancestor, _descendant: False,
            requested_run_id="run-other",
            attested_branch="devfleet/run-squash",
            attested_branch_head_sha="d" * 40,
        )


def test_ambiguous_pending_ancestry_fails_closed() -> None:
    with pytest.raises(DeploymentReceiptError, match="pending_merge_ambiguous"):
        resolve_pending_merge_request(
            [_pending("run-one", "c" * 40), _pending("run-two", "d" * 40)],
            merge_sha=MERGE_SHA,
            is_ancestor=lambda _ancestor, _descendant: True,
        )


def test_exact_completed_callback_is_idempotent() -> None:
    existing = {
        "event": "post_deploy_verified",
        "ok": True,
        "identity_verified": True,
        "run_id": "run-existing",
        "merge_sha": MERGE_SHA,
        "environment": "production",
        "workflow_run_id": "777",
    }
    events: list[dict] = []

    result = record_completed_deployment_receipt(
        rows=[
            existing,
            {
                **existing,
                "event": "merge_completed",
                "status": "completed_merged",
            },
        ],
        record_event=events.append,
        merge_sha=MERGE_SHA,
        environment="production",
        workflow_run_id="777",
        workflow_status="completed",
        workflow_conclusion="success",
        release=BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA),
        health=BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA),
        is_ancestor=lambda _ancestor, _descendant: True,
    )

    assert result["idempotent"] is True
    assert result["recorded"] is False
    assert events == []


def test_successful_redeploy_for_same_run_is_idempotent() -> None:
    existing = {
        "event": "post_deploy_verified",
        "ok": True,
        "identity_verified": True,
        "run_id": "run-existing",
        "merge_sha": MERGE_SHA,
        "environment": "production",
        "workflow_run_id": "777",
    }
    events: list[dict] = []

    result = record_completed_deployment_receipt(
        rows=[
            existing,
            {
                **existing,
                "event": "merge_completed",
                "status": "completed_merged",
            },
        ],
        record_event=events.append,
        merge_sha=MERGE_SHA,
        environment="production",
        workflow_run_id="779",
        workflow_status="completed",
        workflow_conclusion="success",
        release=BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA),
        health=BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA),
        is_ancestor=lambda _ancestor, _descendant: True,
        requested_run_id="run-existing",
    )

    assert result["idempotent"] is True
    assert result["recorded"] is False
    assert result["workflow_run_id"] == "779"
    assert result["previous_workflow_run_id"] == "777"
    assert events == []


def test_successful_redeploy_for_same_run_rechecks_runtime_identity() -> None:
    existing = {
        "event": "post_deploy_verified",
        "ok": True,
        "identity_verified": True,
        "run_id": "run-existing",
        "merge_sha": MERGE_SHA,
        "environment": "production",
        "workflow_run_id": "777",
    }

    with pytest.raises(DeploymentReceiptError, match="health_sha_mismatch"):
        record_completed_deployment_receipt(
            rows=[existing],
            record_event=lambda _event: None,
            merge_sha=MERGE_SHA,
            environment="production",
            workflow_run_id="779",
            workflow_status="completed",
            workflow_conclusion="success",
            release=BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA),
            health=BuildIdentity(git_sha="d" * 40, artifact_sha256=ARTIFACT_SHA),
            is_ancestor=lambda _ancestor, _descendant: True,
            requested_run_id="run-existing",
        )


def test_retry_repairs_missing_terminal_merge_row_after_verified_receipt() -> None:
    existing = {
        "event": "post_deploy_verified",
        "ok": True,
        "identity_verified": True,
        "run_id": "run-partial",
        "merge_sha": MERGE_SHA,
        "environment": "production",
        "workflow_run_id": "778",
    }
    events: list[dict] = []

    result = record_completed_deployment_receipt(
        rows=[existing],
        record_event=events.append,
        merge_sha=MERGE_SHA,
        environment="production",
        workflow_run_id="778",
        workflow_status="completed",
        workflow_conclusion="success",
        release=BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA),
        health=BuildIdentity(git_sha=MERGE_SHA, artifact_sha256=ARTIFACT_SHA),
        is_ancestor=lambda _ancestor, _descendant: True,
    )

    assert result["idempotent"] is True
    assert [row["event"] for row in events] == ["merge_completed"]
