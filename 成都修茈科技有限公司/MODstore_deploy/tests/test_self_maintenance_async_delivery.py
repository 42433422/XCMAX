from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from modstore_server.maintenance_loop import deployment
from modstore_server.maintenance_loop import memory as memory_domain
from modstore_server.maintenance_loop import outcomes, store
from modstore_server.self_maintenance_deploy_receipts import (
    BuildIdentity,
    DeploymentReceiptError,
    run_staged_deployment_chain,
)
from modstore_server.self_maintenance_gh_gateway import GhActionsDeploymentGateway

MERGE_SHA = "a" * 40
ARTIFACT = "b" * 64


@pytest.fixture(autouse=True)
def isolated_feedback_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEDGER", str(tmp_path / "feedback.jsonl"))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(tmp_path / "memory.json"))


def test_remote_merge_completion_resumes_exact_original_delivery(monkeypatch):
    memory = {
        "open_items": [],
        "recent_runs": [
            {
                "run_id": "original-loop",
                "para_task_id": "original-para",
                "branch": "repair/original",
                "status": "completed_merge_requested",
            }
        ],
    }
    calls = []
    result = {"enabled": True, "ok": False, "reason": "awaiting_verified_delivery"}
    monkeypatch.setattr(
        deployment,
        "_run_deploy_receipts_after_merge",
        lambda **kwargs: calls.append(kwargs) or dict(result),
    )
    reconciled = outcomes._reconcile_requested_merge_feedback(
        memory,
        api_base="https://para.invalid",
        task_fetcher=lambda _base, _task: {
            "status": "merged",
            "merge_commit_sha": MERGE_SHA,
        },
    )
    assert calls == [
        {
            "run_id": "original-loop",
            "merge_result": {
                "ok": True,
                "merge_commit_sha": MERGE_SHA,
                "remote_task_id": "original-para",
                "branch": "repair/original",
            },
        }
    ]
    assert reconciled["merged"] == 1
    assert memory["recent_runs"][0]["deployment_receipt"] == result
    assert memory["recent_runs"][0]["status"] == "completed_merge_requested"


class GitHubFixture(GhActionsDeploymentGateway):
    """GitHub protocol fixture; the adapter, file locking and durable state are real."""

    def __init__(self, remote, *, controller_sha=MERGE_SHA):
        super().__init__(
            repo_root=Path(__file__).resolve().parents[3], repository="owner/product", ref="main"
        )
        self.remote, self.controller_sha = remote, controller_sha
        self.commands = []
        self.lose_response = False
        self.accept = True
        self.scan_sha = MERGE_SHA
        self.clearance = True

    def _json(self, args):
        self.commands.append(list(args))
        if args[0] == sys.executable:
            return {"passed": self.clearance, "release_sha": MERGE_SHA}
        if args[:3] == ["gh", "run", "view"]:
            return {
                "databaseId": args[3],
                "headSha": self.controller_sha,
                "status": "completed",
                "conclusion": "success",
            }
        path = args[-1]
        if "/commits/" in path:
            return {"sha": self.controller_sha}
        if "/compare/" in path:
            ancestor = path.split("/compare/", 1)[1].split("...", 1)[0]
            return {"status": "ahead", "merge_base_commit": {"sha": ancestor}}
        if "fhd-security-full-scan.yml/runs" in path:
            return {
                "workflow_runs": [
                    {
                        "id": 700,
                        "head_sha": self.scan_sha,
                        "head_branch": "main",
                        "status": "completed",
                        "conclusion": "success",
                        "path": ".github/workflows/fhd-security-full-scan.yml",
                    }
                ]
            }
        raise AssertionError(args)

    def _runs(self):
        return [{"headBranch": self.ref, **row} for row in self.remote]

    def _run(self, args):
        self.commands.append(list(args))
        if args[:3] == ["gh", "workflow", "run"]:
            fields = dict(
                args[i + 1].split("=", 1) for i, value in enumerate(args) if value == "-f"
            )
            if self.accept:
                self.remote.append(
                    {
                        "databaseId": 900 + len(self.remote),
                        "headSha": self.controller_sha,
                        "displayTitle": (
                            f"fhd-deploy {fields['environment']} apply-latest "
                            f"autonomy:{fields['action_id']}"
                        ),
                    }
                )
            if self.lose_response:
                raise DeploymentReceiptError("gh_command_failed")
        return ""

    def fetch_release_identity(self, environment):
        return BuildIdentity(MERGE_SHA, ARTIFACT)

    fetch_health_identity = fetch_release_identity


@pytest.fixture
def dispatch_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEDGER", str(tmp_path / "loop.jsonl"))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_PRODUCTION_DEPLOY_ENABLED", "1")


def _submit(gateway, environment="production"):
    return gateway.dispatch(
        environment=environment,
        merge_sha=MERGE_SHA,
        action_id=(
            f"release:{MERGE_SHA}"
            if environment == "production"
            else f"loop:original-loop:deploy:staging:{MERGE_SHA[:12]}"
        ),
    )


def _writes(gateway):
    return [call for call in gateway.commands if call[:3] == ["gh", "workflow", "run"]]


def test_staging_dispatch_binds_exact_release_and_artifact(dispatch_environment):
    gateway = GitHubFixture([])
    _submit(gateway, environment="staging")
    command = _writes(gateway)[0]
    assert f"release_sha={MERGE_SHA}" in command
    assert f"release_artifact_sha256={ARTIFACT}" in command


def test_pending_delivery_recovers_after_history_eviction_and_stays_terminal(monkeypatch):
    store._append_ledger(
        {
            "event": "merge_requested",
            "phase": "merge",
            "status": "pending",
            "run_id": "evicted-original",
            "para_task_id": "evicted-para",
            "branch": "repair/evicted",
        }
    )
    memory = {
        "open_items": [],
        "recent_runs": [{"run_id": f"new-{i}", "status": "skipped"} for i in range(20)],
    }
    calls = []
    completed = {
        "enabled": True,
        "ok": True,
        "staging_verified": True,
        "production_enabled": False,
    }
    monkeypatch.setattr(
        deployment,
        "_run_deploy_receipts_after_merge",
        lambda **kwargs: calls.append(kwargs)
        or (dict(completed) if len(calls) > 1 else {"enabled": True, "ok": False}),
    )
    for _ in range(3):
        outcomes._reconcile_requested_merge_feedback(
            memory,
            api_base="https://para.invalid",
            task_fetcher=lambda *_: {"status": "merged", "merge_commit_sha": MERGE_SHA},
        )
        # Simulate restart from only the persisted bounded projection.
        store._write_loop_memory(memory)
        memory = store._load_loop_memory()
    assert len(calls) == 2
    assert calls[0]["run_id"] == "evicted-original"
    assert calls[0]["merge_result"]["remote_task_id"] == "evicted-para"
    assert len(memory["recent_runs"]) == 20
    assert all(run["status"] == "completed_merged" for run in store.merge_feedback_runs())


def test_evicted_failed_merge_is_not_reopened_after_remediation_resolution():
    store._append_ledger(
        {
            "event": "merge_requested",
            "status": "pending",
            "run_id": "evicted-failure",
            "para_task_id": "failed-task",
        }
    )
    memory = {"open_items": [], "recent_runs": []}
    calls = []

    def fetch(*args):
        calls.append(args)
        return {"status": "merge_conflict", "merge_conflict": {"detail": "conflict"}}

    first = outcomes._reconcile_requested_merge_feedback(
        memory, api_base="https://para.invalid", task_fetcher=fetch
    )
    assert first["remediation_added"] == 1
    memory = store._load_loop_memory()
    closed = memory_domain._close_open_items_in_memory(
        memory,
        actor="test-repair",
        resolution_reason="replacement_merged",
        task_ids=["failed-task"],
    )
    assert closed["closed_count"] == 1
    # Neither bounded UI projection can be used as the permanent replay fence.
    memory["closed_items"] = []
    store._write_loop_memory(memory)
    restarted = store._load_loop_memory()
    second = outcomes._reconcile_requested_merge_feedback(
        restarted, api_base="https://para.invalid", task_fetcher=fetch
    )
    assert second["remediation_added"] == 0 and restarted["open_items"] == []
    assert len(calls) == 1
    assert store.merge_feedback_runs()[0]["status"] == "completed_merge_failed"


@pytest.mark.parametrize("status", ["completed_merged", "completed_merge_failed"])
def test_durable_terminal_feedback_overrides_stale_pending_projection(status, monkeypatch):
    pending = {
        "run_id": "original-loop",
        "para_task_id": "original-task",
        "status": "completed_merge_requested",
    }
    terminal = {
        **pending,
        "event": "merge_feedback_reconciled",
        "status": status,
        "merge_reconciliation": {"status": "merged" if status == "completed_merged" else "failed"},
        "deployment_receipt": {"ok": status == "completed_merged"},
    }
    store._append_ledger(terminal)
    # A late stale final snapshot must not downgrade a durable terminal event.
    store._append_ledger({**pending, "phase": "complete"})
    memory = {"recent_runs": [pending], "open_items": []}

    def forbidden(*_args, **_kwargs):
        pytest.fail("terminal delivery must not fetch or deploy again")

    monkeypatch.setattr(deployment, "_run_deploy_receipts_after_merge", forbidden)
    result = outcomes._reconcile_requested_merge_feedback(
        memory, api_base="https://para.invalid", task_fetcher=forbidden
    )
    assert result["changed"] is True
    assert pending["status"] == status
    assert pending["deployment_receipt"] == terminal["deployment_receipt"]
    assert store.merge_feedback_runs()[0]["status"] == status


def test_memory_terminal_before_interrupted_ledger_append_is_recovered():
    store._append_ledger(
        {
            "event": "merge_requested",
            "status": "pending",
            "run_id": "original-loop",
            "para_task_id": "original-task",
        }
    )
    store._write_loop_memory(
        {
            "recent_runs": [
                {
                    "run_id": "original-loop",
                    "para_task_id": "original-task",
                    "status": "completed_merge_failed",
                    "merge_reconciliation": {"status": "merge_conflict"},
                }
            ],
            "open_items": [],
        }
    )

    def forbidden(*_args):
        pytest.fail("persisted terminal memory must repair the ledger without replay")

    outcomes._reconcile_requested_merge_feedback(
        store._load_loop_memory(), api_base="https://para.invalid", task_fetcher=forbidden
    )
    assert store.merge_feedback_runs()[0]["status"] == "completed_merge_failed"


def test_production_adapter_uses_exact_release_and_real_scan_contract(dispatch_environment):
    gateway = GitHubFixture([])
    receipt = _submit(gateway)
    request = _writes(gateway)[0]
    assert f"action_id=release:{MERGE_SHA}" in request
    assert f"release_sha={MERGE_SHA}" in request
    assert "security_scan_run_id=700" in request
    assert "previous_security_scan_run_id=700" in request
    assert receipt.workflow_run_id == "900"
    assert receipt.head_sha == MERGE_SHA
    assert any(call[0] == sys.executable and "--release-sha" in call for call in gateway.commands)
    assert [row["event"] for row in store._read_ledger(limit=0)] == [
        "deploy_dispatch_intent",
        "deploy_dispatch_bound",
    ]


def test_main_controller_can_advance_without_relabeling_release_source(dispatch_environment):
    gateway = GitHubFixture([], controller_sha="c" * 40)
    receipt = _submit(gateway)
    assert receipt.head_sha == MERGE_SHA
    assert receipt.controller_sha == "c" * 40
    completed = gateway.wait_for_success(receipt)
    assert completed.head_sha == "c" * 40
    assert completed.require_success(receipt) == completed


def test_lost_dispatch_response_recovers_same_workflow_after_restart(dispatch_environment):
    remote = []
    first = GitHubFixture(remote)
    first.lose_response = True
    with pytest.raises(DeploymentReceiptError, match="gh_command_failed"):
        _submit(first)
    second = GitHubFixture(remote)
    assert _submit(second).workflow_run_id == "900"
    assert len(_writes(first)) == 1
    assert _writes(second) == []
    third = GitHubFixture(remote)
    assert _submit(third).workflow_run_id == "900"
    assert _writes(third) == []


def test_unknown_dispatch_is_never_replayed(dispatch_environment):
    first = GitHubFixture([])
    first.lose_response, first.accept = True, False
    with pytest.raises(DeploymentReceiptError, match="gh_command_failed"):
        _submit(first)
    second = GitHubFixture([])
    with pytest.raises(DeploymentReceiptError, match="deployment_dispatch_outcome_unknown"):
        _submit(second)
    assert _writes(second) == []


@pytest.mark.parametrize("failure", ["revoked", "wrong_sha", "failed_clearance", "corrupt_ledger"])
def test_missing_authority_or_evidence_never_dispatches(dispatch_environment, monkeypatch, failure):
    gateway = GitHubFixture([])
    if failure == "revoked":
        monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_PRODUCTION_DEPLOY_ENABLED", "0")
    elif failure == "wrong_sha":
        gateway.scan_sha = "d" * 40
    elif failure == "failed_clearance":
        gateway.clearance = False
    else:
        store.ledger_path().write_text('{"truncated":')
    with pytest.raises(DeploymentReceiptError):
        _submit(gateway)
    assert _writes(gateway) == []


def test_same_action_cannot_change_repository_after_submission(dispatch_environment):
    first = GitHubFixture([])
    _submit(first)
    other = GitHubFixture(first.remote)
    other.repository = "other/product"
    with pytest.raises(DeploymentReceiptError, match="deployment_dispatch_binding_conflict"):
        _submit(other)
    assert _writes(other) == []


def test_exact_workflow_title_does_not_match_prefix_collision(dispatch_environment):
    gateway = GitHubFixture(
        [
            {
                "databaseId": 800,
                "headSha": MERGE_SHA,
                "displayTitle": f"fhd-deploy production apply-latest autonomy:release:{MERGE_SHA}-other",
            }
        ]
    )
    assert _submit(gateway).workflow_run_id == "901"
    assert len(_writes(gateway)) == 1


def test_remote_merge_requires_original_persisted_work_order(dispatch_environment):
    gateway = GitHubFixture([])
    store._append_ledger(
        {
            "event": "merge_requested",
            "ok": True,
            "status": "pending",
            "run_id": "original-loop",
            "para_task_id": "original-task",
            "branch": "original/branch",
            "branch_head_sha": MERGE_SHA,
        }
    )
    verified = gateway.verify_requested_merge(
        run_id="original-loop",
        merge_sha=MERGE_SHA,
        task_id="original-task",
        branch="original/branch",
    )
    assert verified["para_task_id"] == "original-task"
    with pytest.raises(DeploymentReceiptError):
        gateway.verify_requested_merge(
            run_id="original-loop",
            merge_sha=MERGE_SHA,
            task_id="other-task",
            branch="original/branch",
        )
    assert _writes(gateway) == []


def test_concurrent_dispatch_cannot_start_a_second_workflow(dispatch_environment):
    remote, entered, release = [], threading.Event(), threading.Event()
    first, second = GitHubFixture(remote), GitHubFixture(remote)
    run = first._run

    def delayed(args):
        result = run(args)
        if args[:3] == ["gh", "workflow", "run"]:
            entered.set()
            assert release.wait(5)
        return result

    first._run = delayed
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(_submit, first)
        assert entered.wait(5)
        try:
            with pytest.raises(DeploymentReceiptError, match="deployment_dispatch_busy"):
                _submit(second)
        finally:
            release.set()
        assert pending.result(timeout=5).workflow_run_id == "900"
    assert len(remote) == 1
    assert _writes(second) == []


def test_intent_fsync_failure_blocks_external_dispatch(dispatch_environment, monkeypatch):
    gateway = GitHubFixture([])

    def failed(_fd):
        raise OSError("durable storage unavailable")

    monkeypatch.setattr(store.os, "fsync", failed)
    with pytest.raises(OSError, match="durable storage unavailable"):
        _submit(gateway)
    assert _writes(gateway) == []


class PaginatedGitHubFixture(GitHubFixture):
    def _runs(self):
        return GhActionsDeploymentGateway._runs(self)

    def _json(self, args):
        if args[:3] == ["gh", "run", "list"]:
            self.commands.append(list(args))
            return list(reversed(self.remote))[:50]
        if args[-1].endswith("/fhd-deploy.yml/runs?per_page=100"):
            self.commands.append(list(args))
            rows = [
                {
                    "id": row["databaseId"],
                    "head_sha": row["headSha"],
                    "head_branch": row.get("headBranch", "main"),
                    "event": "workflow_dispatch",
                    "path": ".github/workflows/fhd-deploy.yml",
                    "repository": {"full_name": self.repository},
                    "head_repository": {"full_name": self.repository},
                    "display_title": row["displayTitle"],
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": f"https://github.com/{self.repository}/actions/runs/{row['databaseId']}",
                }
                for row in reversed(self.remote)
            ]
            return [
                {"total_count": len(rows), "workflow_runs": rows[offset : offset + 100]}
                for offset in range(0, max(1, len(rows)), 100)
            ]
        return super()._json(args)


@pytest.mark.parametrize("backlog", [150, 1050])
def test_existing_dispatch_beyond_latest_fifty_is_recovered_without_duplicate(
    dispatch_environment,
    backlog,
):
    remote = [
        {
            "databaseId": 800,
            "headSha": MERGE_SHA,
            "displayTitle": f"fhd-deploy production apply-latest autonomy:release:{MERGE_SHA}",
        },
        *[
            {"databaseId": 1000 + index, "headSha": MERGE_SHA, "displayTitle": f"other {index}"}
            for index in range(backlog)
        ],
    ]
    gateway = PaginatedGitHubFixture(remote)
    assert _submit(gateway).workflow_run_id == "800"
    assert _writes(gateway) == []


def test_main_advance_during_dispatch_recovers_actual_controller(dispatch_environment):
    class Advancing(GitHubFixture):
        def _run(self, args):
            if args[:3] == ["gh", "workflow", "run"]:
                self.controller_sha = "c" * 40
            return super()._run(args)

    remote = []
    first = Advancing(remote)
    first.capture_timeout_seconds, first.poll_seconds = 0.01, 0.001
    receipt = _submit(first)
    assert receipt.controller_sha == "c" * 40
    restarted = GitHubFixture(remote, controller_sha="c" * 40)
    assert _submit(restarted) == receipt
    assert len(_writes(first)) == 1 and _writes(restarted) == []


def test_verified_remote_delivery_is_terminal_and_cannot_be_overwritten(monkeypatch):
    memory = {
        "open_items": [],
        "recent_runs": [
            {
                "run_id": "original-loop",
                "para_task_id": "original-para",
                "branch": "repair/original",
                "status": "completed_merge_requested",
            }
        ],
    }
    succeeded = {
        "enabled": True,
        "ok": True,
        "run_id": "original-loop",
        "merge_sha": MERGE_SHA,
        "staging_verified": True,
        "production_enabled": True,
        "production": {"verified": True},
    }
    calls = []

    def delivery(**kwargs):
        calls.append(kwargs)
        return (
            dict(succeeded)
            if len(calls) == 1
            else {"enabled": True, "ok": False, "reason": "release_manifest_sha_mismatch"}
        )

    monkeypatch.setattr(deployment, "_run_deploy_receipts_after_merge", delivery)
    for _ in range(2):
        outcomes._reconcile_requested_merge_feedback(
            memory,
            api_base="https://para.invalid",
            task_fetcher=lambda *_: {"status": "merged", "merge_commit_sha": MERGE_SHA},
        )
    assert len(calls) == 1
    assert memory["recent_runs"][0]["deployment_receipt"] == succeeded
    assert memory["recent_runs"][0]["status"] == "completed_merged"


@pytest.mark.parametrize(
    "failure", ["truncated", "duplicate", "invalid_row", "wrong_repo", "moving_total"]
)
def test_incomplete_or_invalid_github_pages_never_prove_dispatch_absent(
    dispatch_environment,
    failure,
):
    class InvalidPages(PaginatedGitHubFixture):
        def _json(self, args):
            data = super()._json(args)
            if args[-1].endswith("/fhd-deploy.yml/runs?per_page=100"):
                if failure == "truncated":
                    data[0]["total_count"] += 1
                elif failure == "duplicate":
                    data[0]["workflow_runs"] *= 2
                    data[0]["total_count"] = 2
                elif failure == "invalid_row":
                    data[0]["workflow_runs"] = [None]
                elif failure == "wrong_repo":
                    data[0]["workflow_runs"][0]["repository"]["full_name"] = "other/repo"
                else:
                    data.append({"total_count": 2, "workflow_runs": []})
            return data

    gateway = InvalidPages([{"databaseId": 123, "headSha": MERGE_SHA, "displayTitle": "unrelated"}])
    with pytest.raises(DeploymentReceiptError, match="github_run_list_"):
        _submit(gateway)
    assert _writes(gateway) == []


def test_lost_response_after_branch_advance_recovers_without_replay(dispatch_environment):
    class Advancing(GitHubFixture):
        def _run(self, args):
            if args[:3] == ["gh", "workflow", "run"]:
                self.controller_sha = "c" * 40
            return super()._run(args)

    first = Advancing([])
    first.lose_response = True
    with pytest.raises(DeploymentReceiptError, match="gh_command_failed"):
        _submit(first)
    restarted = GitHubFixture(first.remote, controller_sha="d" * 40)
    receipt = _submit(restarted)
    assert receipt.workflow_run_id == "900" and receipt.controller_sha == "c" * 40
    assert _writes(restarted) == []


def test_pending_dispatch_rejects_force_push_away_from_original_controller(dispatch_environment):
    class Rewritten(GitHubFixture):
        def _run(self, args):
            if args[:3] == ["gh", "workflow", "run"]:
                self.controller_sha = "d" * 40
            return super()._run(args)

        def _json(self, args):
            if f"/compare/{'c' * 40}...{'d' * 40}" in args[-1]:
                return {"status": "diverged", "merge_base_commit": {"sha": MERGE_SHA}}
            return super()._json(args)

    first = Rewritten([], controller_sha="c" * 40)
    first.lose_response = True
    with pytest.raises(DeploymentReceiptError, match="gh_command_failed"):
        _submit(first)
    restarted = Rewritten(first.remote, controller_sha="d" * 40)
    with pytest.raises(DeploymentReceiptError, match="deployment_controller_unverified"):
        _submit(restarted)
    assert _writes(restarted) == []


@pytest.mark.parametrize("failure", ["wrong_branch", "unrelated_commit"])
def test_same_title_cannot_bind_unapproved_controller(dispatch_environment, failure):
    class Unrelated(GitHubFixture):
        def _json(self, args):
            if failure == "unrelated_commit" and "/compare/" in args[-1]:
                return {"status": "diverged", "merge_base_commit": {"sha": "d" * 40}}
            return super()._json(args)

    gateway = Unrelated(
        [
            {
                "databaseId": 800,
                "headSha": "c" * 40,
                "headBranch": "other" if failure == "wrong_branch" else "main",
                "displayTitle": f"fhd-deploy production apply-latest autonomy:release:{MERGE_SHA}",
            }
        ]
    )
    with pytest.raises(
        DeploymentReceiptError, match="deployment_(dispatch_ref_mismatch|controller_unverified)"
    ):
        _submit(gateway)
    assert _writes(gateway) == []


def _chain(gateway, *, production=True):
    return run_staged_deployment_chain(
        gateway=gateway,
        record_event=store._append_ledger,
        run_id="original-loop",
        merge_sha=MERGE_SHA,
        allow_production=production,
    )


def test_verified_environments_survive_restart_and_newer_release(dispatch_environment):
    first = GitHubFixture([])
    assert _chain(first)["ok"] is True
    rows = store._read_ledger(limit=0)
    restarted = GitHubFixture(first.remote, controller_sha="d" * 40)
    restarted.fetch_release_identity = lambda _env: BuildIdentity("d" * 40, "e" * 64)
    restarted.fetch_health_identity = restarted.fetch_release_identity
    restored = _chain(restarted)
    assert restored["ok"] is True
    assert restored["staging"]["recovered"] is True
    assert restored["production"]["recovered"] is True
    assert restarted.commands == []
    assert store._read_ledger(limit=0) == rows


def test_partial_delivery_resumes_only_unverified_environment(dispatch_environment):
    class Partial(GitHubFixture):
        def wait_for_success(self, receipt):
            if receipt.environment == "production":
                raise DeploymentReceiptError("workflow_completion_timeout")
            return super().wait_for_success(receipt)

    first = Partial([])
    partial = _chain(first)
    assert partial["staging_verified"] is True and partial["ok"] is False
    restarted = GitHubFixture(first.remote)
    restarted.fetch_release_identity = lambda env: BuildIdentity(
        "d" * 40 if env == "staging" else MERGE_SHA,
        ARTIFACT,
    )
    resumed = _chain(restarted)
    assert resumed["ok"] is True and resumed["staging"]["recovered"] is True
    assert _writes(restarted) == []
    views = [call for call in restarted.commands if call[:3] == ["gh", "run", "view"]]
    assert len(views) == 1 and views[0][3] == "901"


def test_verified_receipt_cannot_cross_repository_boundary(dispatch_environment):
    first = GitHubFixture([])
    assert _chain(first, production=False)["staging_verified"] is True
    other = GitHubFixture(first.remote)
    other.repository = "other/product"
    result = _chain(other, production=False)
    assert result["staging_verified"] is False
    assert result["staging"]["reason"] == "deployment_dispatch_binding_conflict"
    assert other.commands == []
