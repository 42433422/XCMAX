"""Recover the same original task after a completed-worker producer was interrupted."""

from __future__ import annotations

import pytest

from tests.test_ci.test_self_heal_freshness import (
    BOT,
    NEW,
    OLD,
    REPO,
    RecoveryGitHub,
    _recover,
    heal,
)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "implementation_repo",
        "implementation_sha",
        "worker_id",
        "worker_path",
        "worker_branch",
        "worker_repo",
        "worker_attempt",
        "worker_failure",
        "worker_sha",
        "control_task",
        "source_attempt",
        "missing_worker",
    ],
)
def test_original_worker_receipt_resumes_only_its_original_task(monkeypatch, fault):
    para = heal.recovery.para
    control = "1" * 32
    worker = {
        "id": 50,
        "workflow_id": 101,
        "path": ".github/workflows/fhd-para-github-worker.yml",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": "c" * 40,
        "repository": {"full_name": REPO},
        "display_title": "para-workspace-11111111-1111-1111-1111-111111111111",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
    }
    implementation = {
        "event": "workflow_run",
        "head_sha": NEW,
        "repository": {"full_name": REPO},
    }
    changes = {
        "worker_id": {"id": 51},
        "worker_path": {"path": ".github/workflows/other.yml"},
        "worker_branch": {"head_branch": "feature/other"},
        "worker_repo": {"repository": {"full_name": "foreign/repository"}},
        "worker_attempt": {"run_attempt": 2},
        "worker_failure": {"conclusion": "failure"},
        "worker_sha": {"head_sha": "unknown"},
    }
    worker.update(changes.get(fault, {}))
    if fault == "implementation_repo":
        implementation["repository"] = {"full_name": "foreign/repository"}
    if fault == "implementation_sha":
        implementation["head_sha"] = "unknown"
    comments = []
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    monkeypatch.setattr(
        para,
        "_comment",
        lambda result, token, body: comments.append({"user": BOT, "body": body}),
    )
    para._receipt(
        para.DispatchResult(
            issue_number=1,
            repo=REPO,
            started_at="",
            status="timeout",
            base_branch="feat/x",
            original_sha=OLD,
            source_run_id=7,
            source_run_attempt=2 if fault == "source_attempt" else 1,
            control_task_id="2" * 32 if fault == "control_task" else control,
            para_task_id="para-original",
            github_run_id=0 if fault == "missing_worker" else 50,
        ),
        "read-only-test",
    )

    class GitHub(RecoveryGitHub):
        def __call__(self, path, params):
            if path == f"/repos/{REPO}/actions/runs/50":
                return 200, worker
            return super().__call__(path, params)

    result, writes, dispatches = _recover(
        GitHub(comments=comments, implementation_run=implementation)
    )
    assert writes == [], "the observer must never rerun the original paid worker"
    if fault is None:
        assert result["state"] == "resumed" and result["reason"] == "resume_control_task"
        assert len(dispatches) == 1
        assert dispatches[0][1] == {"target_branch": "feat/x", "control_task_id": control}
    else:
        assert result["state"] == "unresolved" and dispatches == []
