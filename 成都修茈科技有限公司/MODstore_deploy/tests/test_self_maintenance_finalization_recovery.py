"""Real durable checkpoints recover original publication, never another merge."""

from __future__ import annotations

import copy
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from modstore_server import self_evolution_knowledge
from modstore_server.maintenance_loop import (
    decision,
    deployment,
    merge,
    outcomes,
    para_client,
    store,
    workspace,
)
from modstore_server.self_maintenance_deploy_receipts import GhActionsDeploymentGateway
from tests.test_self_maintenance_runtime_composition import RuntimeHarness

HEAD, BASE, MERGED = "a" * 40, "b" * 40, "c" * 40


@pytest.fixture
def original(tmp_path, monkeypatch):
    for key, value in {
        "MODSTORE_SELF_MAINTENANCE_MEMORY": str(tmp_path / "memory.json"),
        "MODSTORE_SELF_MAINTENANCE_LEDGER": str(tmp_path / "loop.jsonl"),
        "MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT": str(tmp_path / "audit.jsonl"),
        "MODSTORE_SELF_MAINTENANCE_LEASE_FILE": str(tmp_path / "lease.lock"),
        "MODSTORE_PARA_REPO_URL": "https://github.com/example/original.git",
        "MODSTORE_PARA_API_BASE": "https://para.invalid",
        "MODSTORE_PARA_BRANCH": "main",
        "MODSTORE_AUTO_MERGE_ALLOW_REMOTE": "1",
    }.items():
        monkeypatch.setenv(key, value)
    harness = RuntimeHarness("original")
    store._write_loop_memory(harness.memory)
    original_lease = harness.runtime.state.lease

    @contextmanager
    def lease():
        with original_lease() as acquired, store._exclusive_loop_lease() as durable:
            yield acquired and durable

    def project(final, _gate):
        memory = store._load_loop_memory()
        harness.outcomes.append(copy.deepcopy(final))
        memory["last_run"] = {
            **{key: final[key] for key in ("run_id", "branch", "para_task_id", "status")},
            "action": final["policy_decision"]["action"],
        }
        store._write_loop_memory(memory)

    harness.runtime.state = replace(
        harness.runtime.state,
        lease=lease,
        load_memory=store._load_loop_memory,
        write_memory=store._write_loop_memory,
        memory_path=store.loop_memory_path,
        append=store._append_ledger,
        record_outcome=project,
        recorded_outcome=store._has_recorded_outcome,
    )
    harness.runtime.policy = replace(
        harness.runtime.policy,
        decide=decision._decide_post_loop_policy,
        recover=decision._recover_post_loop_policy,
        prepare=decision._prepare_post_loop_policy,
    )
    monkeypatch.setattr(decision.review, "_structured_report_gate", lambda *_: {"ok": True})
    monkeypatch.setattr(decision.review, "_missing_report_only_evidence", lambda *_: [])
    monkeypatch.setattr(decision.governance, "_loop_steps_roster_gate", lambda *_: {"ok": True})
    monkeypatch.setattr(decision.governance, "_governance_audit_gate", lambda: {"ok": True})
    monkeypatch.setattr(decision.governance, "_policy_active_gates_snapshot", lambda **_: {})
    monkeypatch.setattr(decision.self_evolution_knowledge, "evolution_metrics_gate", lambda: {})
    monkeypatch.setattr(
        workspace, "_remote_branch_head", lambda _repo, branch: BASE if branch == "main" else HEAD
    )
    monkeypatch.setattr(
        "modstore_server.autonomy_guard_delegate.evaluate_risk",
        lambda action, **kwargs: SimpleNamespace(
            allowed=True,
            to_dict=lambda: {
                "decision": "allow",
                "allowed": True,
                "action": action,
                "action_id": kwargs["action_id"],
            },
        ),
    )
    calls = {"merge": 0, "deploy": [], "read": []}

    def lost_ack(**_):
        calls["merge"] += 1
        pending = store._load_loop_memory()["pending_execution"]
        assert pending["state"] == "finalizing"
        assert pending["final_policy_progress"]["intent"]["branch_head_sha"] == HEAD
        raise TimeoutError("request was accepted but acknowledgement was lost")

    monkeypatch.setattr(para_client, "_request_para_task_merge", lost_ack)
    task = {"id": "task-original", "status": "merged", "merge_commit_sha": MERGED}
    pr = {
        "number": 17,
        "merged_at": "2026-11-21T12:00:00Z",
        "merge_commit_sha": MERGED,
        "head": {"ref": "branch-original", "sha": HEAD, "repo": {"full_name": "example/original"}},
        "base": {"ref": "main", "repo": {"full_name": "example/original"}},
    }
    comparison = {"status": "ahead", "merge_base_commit": {"sha": MERGED}}
    monkeypatch.setattr(
        para_client,
        "_fetch_para_task_state",
        lambda base, task_id: calls["read"].append((base, task_id)) or task,
    )
    monkeypatch.setattr(
        GhActionsDeploymentGateway,
        "_json",
        lambda self, args: (
            [pr]
            if "/pulls?" in args[-1]
            else (
                {"status": "ahead", "merge_base_commit": {"sha": BASE}}
                if f"/{BASE}..." in args[-1]
                else comparison
            )
        ),
    )
    monkeypatch.setattr(
        deployment,
        "_run_deploy_receipts_after_merge",
        lambda **kwargs: calls["deploy"].append(kwargs) or {"enabled": False},
    )
    return harness, calls, task, pr, comparison


def _crash_before_policy(harness):
    write = harness.runtime.state.write_memory

    def interrupt(memory):
        write(memory)
        if (memory.get("pending_execution") or {}).get("state") == "finalizing":
            raise KeyboardInterrupt("process stopped after the original final record was saved")

    harness.runtime.state = replace(harness.runtime.state, write_memory=interrupt)
    with pytest.raises(KeyboardInterrupt):
        harness.runtime.run()
    harness.runtime.state = replace(harness.runtime.state, write_memory=write)


@pytest.mark.parametrize(
    "boundary",
    ["before_policy", "gate_error", "failed_before_policy", "retort_stop", "retort_scope"],
)
def test_pre_effects_crash_recovers_original_terminal_without_task_replay(
    original, monkeypatch, boundary
):
    harness, calls, *_ = original
    failed = boundary == "failed_before_policy" or boundary.startswith("retort_")
    if boundary.startswith("retort_"):
        gate = {"blocked": True, "reason": "retort_clarification_pending"}
        if boundary == "retort_scope":
            gate["clarification"] = {"questions": [{"reason": "elevated_risk_or_large_diff"}]}
        harness.runtime.execution = replace(
            harness.runtime.execution, retort_before_review=lambda **_: gate
        )
    elif failed:
        execute = harness.runtime.execution.run_step

        def fail_review(**kwargs):
            result = list(execute(**kwargs))
            if kwargs["step_name"] == "review":
                result[1:3] = [False, "original_review_rejected"]
            return tuple(result)

        harness.runtime.execution = replace(harness.runtime.execution, run_step=fail_review)
    if boundary == "gate_error":

        def unavailable():
            raise RuntimeError("temporary gate read failure before any merge intent")

        monkeypatch.setattr(decision.governance, "_governance_audit_gate", unavailable)
        assert harness.runtime.run()["status"] == "waiting_reconciliation"
        monkeypatch.setattr(decision.governance, "_governance_audit_gate", lambda: {"ok": True})
    else:
        _crash_before_policy(harness)
    pending = store._load_loop_memory()["pending_execution"]
    original_record = pending["final_record"]
    assert pending["final_policy_progress"]["stage"] == "before_policy"
    assert pending["final_policy_progress"]["policy"] == {
        "gate": pending["final_gate"],
        "deployment_scope": deployment._deployment_scope(),
    }
    assert calls["merge"] == 0
    final = harness.runtime.run()
    if failed:
        assert final["status"] == "failed"
        if boundary == "retort_scope":
            assert final["policy_decision"] == pending["final_policy_progress"]["policy_override"]
            assert final["policy_decision"]["resume_from_clean_baseline"] is True
        else:
            assert final["policy_decision"] == {"action": "stop", "reason": "loop_not_completed"}
        assert calls["merge"] == 0
    else:
        assert final["status"] == "waiting_reconciliation"
        assert (
            store._load_loop_memory()["pending_execution"]["final_policy_progress"]["stage"]
            == "merge_intent"
        )
        final = harness.runtime.run()
        assert final["status"] == "completed_merged" and calls["merge"] == 1
    assert final["run_id"] == original_record["run_id"] == "run-original-1"
    assert final["steps"] == original_record["steps"]
    assert [call["step_name"] for call in harness.calls] == (
        ["code"]
        if boundary.startswith("retort_")
        else ["code", "review"] if failed else ["code", "review", "qa"]
    )
    assert len(harness.outcomes) == 1
    assert "pending_execution" not in store._load_loop_memory()


@pytest.mark.parametrize("changed", ["legacy", "binding", "gate", "scope"])
def test_pre_effects_recovery_requires_original_protocol_identity_and_scope(
    original, monkeypatch, changed
):
    harness, calls, *_ = original
    _crash_before_policy(harness)
    memory = store._load_loop_memory()
    pending = memory["pending_execution"]
    if changed == "legacy":
        pending.pop("final_policy_progress", None)
    elif changed == "binding":
        pending["final_policy_progress"]["binding"]["request_id"] = "f" * 32
    elif changed == "gate":
        pending["final_policy_progress"]["policy"]["gate"] = {"owner": "foreign"}
    else:
        monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_PRODUCTION_DEPLOY_ENABLED", "1")
    store._write_loop_memory(memory)
    assert harness.runtime.run()["status"] == "waiting_reconciliation"
    assert calls["merge"] == 0 and calls["deploy"] == []
    assert len(harness.calls) == 3 and harness.outcomes == []
    assert store._load_loop_memory()["pending_execution"]["final_record"] == pending["final_record"]


@pytest.mark.parametrize(
    "unavailable",
    ["head", "base", "short_head", "short_base", "foreign_repo", "query_repo"],
)
def test_durable_merge_never_posts_without_supported_repository_and_exact_heads(
    original, monkeypatch, unavailable
):
    harness, calls, *_ = original
    heads = {"main": BASE, "branch-original": HEAD}
    if unavailable.endswith("repo"):
        monkeypatch.setenv(
            "MODSTORE_PARA_REPO_URL",
            (
                "https://example.invalid/example/original.git"
                if unavailable == "foreign_repo"
                else "https://github.com/example/original.git?foreign=true"
            ),
        )
    else:
        heads["main" if unavailable.endswith("base") else "branch-original"] = (
            "abcd" if unavailable.startswith("short") else None
        )
    monkeypatch.setattr(workspace, "_remote_branch_head", lambda _repo, branch: heads[branch])

    def request(**_):
        calls["merge"] += 1
        return {"ok": True}

    monkeypatch.setattr(para_client, "_request_para_task_merge", request)
    final = harness.runtime.run()
    assert final["status"] == "completed_held_for_remediation"
    assert final["policy_decision"]["reason"] == "original_merge_readback_unavailable"
    assert calls["merge"] == 0 and calls["deploy"] == []
    assert len(harness.outcomes) == 1 and "pending_execution" not in store._load_loop_memory()


@pytest.mark.parametrize("throttle", [None, "cooldown", "below_threshold"])
def test_lost_merge_ack_recovers_original_run_without_any_policy_or_task_replay(original, throttle):
    harness, calls, *_ = original
    first = harness.runtime.run()
    assert first["status"] == "waiting_reconciliation"
    persisted = store._load_loop_memory()["pending_execution"]
    assert persisted["final_policy_progress"]["binding"]["final_run_id"] == "run-original-1"
    if throttle:
        harness.runtime.policy = replace(
            harness.runtime.policy, admit=lambda **_: {"should_run": False, "reason": throttle}
        )
    final = harness.runtime.run()
    assert final["status"] == "completed_merged"
    assert final["run_id"] == "run-original-1"
    assert calls["merge"] == 1
    assert [call["step_name"] for call in harness.calls] == ["code", "review", "qa"]
    assert len(harness.outcomes) == 1
    assert calls["deploy"][0]["merge_result"]["merge_commit_sha"] == MERGED
    assert "pending_execution" not in store._load_loop_memory()


@pytest.mark.parametrize(
    "changed",
    ["task", "head", "branch", "repository", "base", "merge", "main", "unknown", "binding", "gate"],
)
def test_unrelated_or_unknown_receipt_preserves_intent_without_delivery(original, changed):
    harness, calls, task, pr, comparison = original
    assert harness.runtime.run()["status"] == "waiting_reconciliation"
    if changed == "task":
        task["id"] = "another-task"
    elif changed == "head":
        pr["head"]["sha"] = "d" * 40
    elif changed == "branch":
        pr["head"]["ref"] = "another-branch"
    elif changed == "repository":
        pr["head"]["repo"]["full_name"] = "example/foreign"
    elif changed == "base":
        pr["base"]["ref"] = "release-other"
    elif changed == "merge":
        pr["merge_commit_sha"] = "d" * 40
    elif changed == "main":
        comparison["merge_base_commit"]["sha"] = "d" * 40
    elif changed == "unknown":
        task["status"] = "completed"
    else:
        memory = store._load_loop_memory()
        progress = memory["pending_execution"]["final_policy_progress"]
        if changed == "binding":
            progress["binding"]["user_id"] = -1
        else:
            progress["policy"]["gate"] = {"owner": "foreign"}
        store._write_loop_memory(memory)
    for _ in range(2):
        assert harness.runtime.run()["status"] == "waiting_reconciliation"
    assert calls["merge"] == 1 and calls["deploy"] == []
    assert harness.outcomes == []
    assert store._load_loop_memory()["pending_execution"]["state"] == "finalizing"


def test_pending_deployment_recovers_frozen_merge_even_if_remote_task_later_disappears(
    original, monkeypatch
):
    harness, calls, task, *_ = original
    assert harness.runtime.run()["status"] == "waiting_reconciliation"
    receipts = [
        {"enabled": True, "ok": False, "reason": "workflow_not_completed"},
        {"enabled": True, "ok": True, "staging_verified": True, "production_enabled": False},
    ]
    monkeypatch.setattr(
        deployment,
        "_run_deploy_receipts_after_merge",
        lambda **kwargs: calls["deploy"].append(kwargs) or receipts.pop(0),
    )
    assert harness.runtime.run()["status"] == "waiting_reconciliation"
    pending = store._load_loop_memory()["pending_execution"]
    assert pending["final_policy_progress"]["stage"] == "merge_observed"
    assert pending["final_policy_progress"]["policy"]["deployment_receipt"]["ok"] is False
    task.clear()
    final = harness.runtime.run()
    assert final["status"] == "completed_merged"
    assert len(calls["read"]) == 1
    assert len(calls["deploy"]) == 2 and calls["deploy"][0] == calls["deploy"][1]
    assert calls["merge"] == 1


def test_recovery_respects_disabled_admission(original):
    harness, calls, *_ = original
    harness.runtime.run()
    harness.runtime.policy = replace(
        harness.runtime.policy, admit=lambda **_: {"should_run": False, "reason": "disabled"}
    )
    assert harness.runtime.run()["status"] == "skipped_disabled"
    assert calls["read"] == calls["deploy"] == []


def test_local_push_readback_requires_real_published_merge_and_frozen_parents(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "test")
    git("config", "user.email", "test@example.invalid")
    (repo / "baseline.txt").write_text("original\n")
    git("add", "baseline.txt")
    git("commit", "-m", "baseline")
    base = git("rev-parse", "HEAD")
    git("checkout", "-b", "repair")
    (repo / "repair.txt").write_text("approved change\n")
    git("add", "repair.txt")
    git("commit", "-m", "repair")
    head = git("rev-parse", "HEAD")
    git("checkout", "main")
    git("merge", "--no-ff", "--no-edit", "repair")
    sha = git("rev-parse", "HEAD")
    intent = {
        "kind": "local_merge",
        "repo_url": repo.as_uri(),
        "api_base": "https://para.invalid",
        "run_id": "original-run",
        "task_id": "original-task",
        "base_branch": "main",
        "branch": "repair",
        "base_head_sha": base,
        "branch_head_sha": head,
        "merge_commit_sha": sha,
        "risk_decision": {
            "decision": "allow",
            "allowed": True,
            "action": "self_maintenance_l1_merge",
            "action_id": "loop:original-run:self_maintenance_l1_merge",
        },
        "policy": {"ok": True},
    }
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", intent["repo_url"])
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", intent["api_base"])
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "main")
    assert merge._readback_original_merge(intent)["merge_commit_sha"] == sha
    with pytest.raises(ValueError, match="parent_mismatch"):
        merge._readback_original_merge({**intent, "base_head_sha": head})
    git("update-ref", "refs/heads/main", base)
    with pytest.raises(RuntimeError, match="command failed"):
        merge._readback_original_merge(intent)


@pytest.mark.parametrize(
    "crash_at", ["ledger", "fixes", "patterns", "before_memory", "after_memory"]
)
def test_outcome_recovery_applies_one_projection_and_one_knowledge_pair(
    original, tmp_path, monkeypatch, crash_at
):
    harness, *_ = original
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    monkeypatch.setenv("DEVFLEET_WORKSPACE_ROOT", str(tmp_path / "empty-workspace"))
    harness.runtime.policy = replace(
        harness.runtime.policy,
        decide=lambda **_: {
            "action": "auto_merged_low_risk",
            "merge_result": {
                "merge_commit_sha": MERGED,
                "changed_files": ["app.py"],
                "diff_excerpt": "diff --git a/app.py b/app.py\n-old\n+approved\n",
            },
        },
    )
    harness.runtime.state = replace(
        harness.runtime.state, record_outcome=outcomes._update_loop_memory, outcome_recoverable=True
    )
    write_doc = self_evolution_knowledge._write_kb_doc
    write_memory = store._write_loop_memory
    write_ledger = store._append_ledger
    crashed = False

    def crash():
        nonlocal crashed
        crashed = True
        raise KeyboardInterrupt("simulated process death during original outcome projection")

    def knowledge(kind, prefix, payload):
        path = write_doc(kind, prefix, payload)
        if not crashed and crash_at == kind:
            crash()
        return path

    def memory(record):
        projecting = record.get("run_count") == 1
        if projecting and not crashed and crash_at == "before_memory":
            crash()
        write_memory(record)
        if projecting and not crashed and crash_at == "after_memory":
            crash()

    def ledger(record):
        write_ledger(record)
        if not crashed and crash_at == "ledger" and record.get("phase") == "complete":
            crash()

    harness.runtime.state = replace(harness.runtime.state, append=ledger)
    monkeypatch.setattr(self_evolution_knowledge, "_write_kb_doc", knowledge)
    monkeypatch.setattr(store, "_write_loop_memory", memory)
    with pytest.raises(KeyboardInterrupt):
        harness.runtime.run()
    pending = store._load_loop_memory()["pending_execution"]
    assert pending["state"] == "recording_outcome" and pending["outcome_recoverable"] is True
    final = harness.runtime.run()
    state = store._load_loop_memory()
    assert final["run_id"] == "run-original-1" and final["status"] == "completed_merged"
    assert state["run_count"] == len(state["recent_runs"]) == 1
    assert len(state["last_run"]["outcome_projection_id"]) == 64
    assert len(list((tmp_path / "kb/fixes").glob("*.json"))) == 1
    assert len(list((tmp_path / "kb/patterns").glob("*.json"))) == 1
    assert "pending_execution" not in state
    assert (
        len(
            [
                row
                for row in store._read_ledger(0)
                if row.get("phase") == "complete" and row.get("run_id") == "run-original-1"
            ]
        )
        == 1
    )
    assert [call["step_name"] for call in harness.calls] == ["code", "review", "qa"]


def test_same_outcome_knowledge_identity_cannot_replace_different_content(tmp_path, monkeypatch):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    arguments = {
        "symptom": "observed failure",
        "root_cause": "original cause",
        "fix_diff": "approved diff",
        "metadata": {"outcome_projection_id": "f" * 64},
    }
    first = self_evolution_knowledge.record_fix_knowledge(**arguments)
    assert self_evolution_knowledge.record_fix_knowledge(**arguments)["_path"] == first["_path"]
    with pytest.raises(ValueError, match="original outcome knowledge conflict"):
        self_evolution_knowledge.record_fix_knowledge(
            **{**arguments, "root_cause": "different cause"}
        )
    assert len(list((tmp_path / "kb/fixes").glob("*.json"))) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("MODSTORE_SELF_MAINTENANCE_PRODUCTION_DEPLOY_ENABLED", "1"),
        ("MODSTORE_SELF_MAINTENANCE_DEPLOY_RECEIPTS_ENABLED", "1"),
        ("MODSTORE_SELF_MAINTENANCE_GITHUB_REPOSITORY", "example/foreign"),
        ("MODSTORE_SELF_MAINTENANCE_DEPLOY_REF", "other-release"),
        ("MODSTORE_SELF_MAINTENANCE_DEPLOY_WORKFLOW", "other.yml"),
    ],
)
def test_recovery_does_not_expand_or_rebind_original_deployment_scope(
    original, monkeypatch, key, value
):
    harness, calls, *_ = original
    assert harness.runtime.run()["status"] == "waiting_reconciliation"
    monkeypatch.setenv(key, value)
    assert harness.runtime.run()["status"] == "waiting_reconciliation"
    assert calls["merge"] == 1 and calls["deploy"] == []


def test_outcome_append_readback_rejects_different_or_partial_original_record(original):
    final = {
        "run_id": "same-run",
        "phase": "complete",
        "status": "completed",
        "policy_decision": {},
    }
    store._append_ledger(final)
    assert store._has_recorded_outcome(final) is True
    with pytest.raises(ValueError, match="identity_conflict"):
        store._has_recorded_outcome({**final, "status": "failed"})
    with store.ledger_path().open("a", encoding="utf-8") as handle:
        handle.write('{"run_id":')
    with pytest.raises(ValueError, match="incomplete"):
        store._has_recorded_outcome(final)
