from __future__ import annotations

from dataclasses import dataclass, field

from modstore_server.self_maintenance_deploy_receipts import (
    BuildIdentity,
    DispatchReceipt,
    WorkflowCompletion,
    correlated_verified_deploys,
    run_staged_deployment_chain,
)
from modstore_server import self_maintenance_loop_runner


MERGE_SHA = "a" * 40
ARTIFACT_SHA = "b" * 64


def test_loop_runner_deployment_receipts_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_DEPLOY_RECEIPTS_ENABLED", raising=False)

    result = self_maintenance_loop_runner._run_deploy_receipts_after_merge(
        run_id="run-disabled",
        merge_result={"ok": True, "merge_commit_sha": MERGE_SHA},
    )

    assert result == {"enabled": False, "reason": "deploy_receipts_disabled"}


@dataclass
class FakeGateway:
    conclusions: dict[str, str] = field(
        default_factory=lambda: {"staging": "success", "production": "success"}
    )
    health_sha: str = MERGE_SHA
    health_artifact: str = ARTIFACT_SHA
    dispatches: list[str] = field(default_factory=list)

    def dispatch(
        self, *, environment: str, merge_sha: str, action_id: str
    ) -> DispatchReceipt:
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
    assert {key: dispatch[key] for key in keys} == {
        key: verified[key] for key in keys
    }
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
