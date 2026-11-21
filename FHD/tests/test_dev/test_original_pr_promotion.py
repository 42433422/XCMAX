"""Trusted original-PR promotion uses real inert Git objects and exact-tip CAS."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/para_issue_dispatch.py"
spec = importlib.util.spec_from_file_location("original_pr_promotion_dispatch", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


@pytest.fixture
def repository(tmp_path):
    seed, remote = tmp_path / "seed", tmp_path / "origin.git"
    seed.mkdir()

    def run(*args, cwd=seed, **kwargs):
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, **kwargs
        ).stdout.strip()

    run("init", "-b", "main")
    run("config", "user.name", "Fixture")
    run("config", "user.email", "fixture@example.invalid")
    (seed / "module.py").write_text("value = 1\n")
    run("add", "module.py")
    run("commit", "-m", "base")
    old = run("rev-parse", "HEAD")
    run("branch", "fix/ci")
    run("checkout", "-b", "devfleet/fix")
    (seed / "module.py").write_text("value = 2\n")
    run("commit", "-am", "repair")
    new = run("rev-parse", "HEAD")
    run("checkout", "-b", "other", old)
    (seed / "module.py").write_text("value = 3\n")
    run("commit", "-am", "concurrent change")
    other = run("rev-parse", "HEAD")
    orphan = run("commit-tree", run("rev-parse", "HEAD^{tree}"), input="unrelated\n")
    run("branch", "unrelated", orphan)
    run("clone", "--bare", str(seed), str(remote), cwd=tmp_path)
    state = SimpleNamespace(
        url="https://github.com/o/r.git",
        remote=remote,
        old=old,
        new=new,
        other=other,
        orphan=orphan,
        pushes=[],
        lost_ack=False,
    )
    state.tip = lambda: run("rev-parse", "refs/heads/fix/ci", cwd=remote)
    state.update = lambda sha: run("update-ref", "refs/heads/fix/ci", sha, cwd=remote)

    def command(args, **kwargs):
        assert all("fixture-secret" not in argument for argument in args)
        mapped = [str(remote) if argument == state.url else argument for argument in args]
        value = subprocess.run(mapped, check=True, capture_output=True, text=True, **kwargs).stdout
        if "push" in args:
            state.pushes.append(args)
            if state.lost_ack:
                raise subprocess.CalledProcessError(128, ["git", "push"], stderr="ack lost")
        return value

    state.command = command
    state.target = mod.repair.Target(7, "fix/ci", old, 70, 99, ".github/workflows/fhd-ci-cd.yml")
    state.proof = {
        "repository": "o/r",
        "original_pr": asdict(state.target),
        "execution_isolation": mod.repair.HEADER_ONLY_PLATFORM_PROFILE,
        "source_sha": old,
        "commit_sha": new,
    }
    return state


@pytest.mark.parametrize("case", ["main", "unrelated", "before_fetch", "during_write", "replay"])
def test_original_ref_cas_never_rewrites_drift_or_accepts_unrelated_history(repository, case):
    state, target, candidate = repository, repository.target, repository.new
    before = state.old
    if case == "main":
        target = mod.repair.Target(7, "main", state.old, 70, 99, target.workflow_path)
    elif case == "unrelated":
        candidate = state.orphan
    elif case in {"before_fetch", "replay"}:
        before = state.new if case == "replay" else state.other
        state.update(before)
    proof = {**state.proof, "commit_sha": candidate}

    def before_write():
        if case == "during_write":
            state.update(state.other)
        return proof

    with pytest.raises((ValueError, subprocess.SubprocessError)):
        mod.repair.advance(
            state.url,
            target,
            candidate,
            "fixture-secret",
            publication=proof,
            before_write=before_write,
            command=state.command,
        )
    assert state.tip() == (state.other if case == "during_write" else before)
    assert not state.pushes


@pytest.mark.parametrize("lost_ack", [False, True])
@pytest.mark.parametrize("revoked", [False, True])
def test_dispatcher_reaches_original_branch_and_recovers_exact_intent_without_reexecution(
    repository,
    monkeypatch,
    tmp_path,
    lost_ack,
    revoked,
):
    state, target = repository, repository.target
    state.lost_ack = lost_ack
    control = "1" * 32
    request = str(uuid.UUID(hex=control))
    budget = str(uuid.uuid5(uuid.NAMESPACE_URL, f"xcmax:original-pr-budget:{request}"))
    controller = "b" * 40
    manifest = {
        "request_id": request,
        "run_id": "502",
        "repository": "o/r",
        "base_sha": state.old,
        "commit_sha": state.new,
        "task_id": "para1",
        "branch": "devfleet/fix",
    }
    proof = {
        **state.proof,
        "source": "github_isolated_publisher",
        "pushed": True,
        "request_id": request,
        "branch": "devfleet/fix",
        "github_run_id": 502,
        "controller_sha": controller,
        "publication_job_id": 600,
        "budget_request_id": budget,
    }
    task = {
        "id": control,
        "state": "execution_completed",
        "executor": "original_pr_repair",
        "para_task_id": "para1",
        "github_run_id": 502,
        "execution": {
            "candidate": manifest,
            "reports": [{"report": proof}],
            "subtasks": [{"branch_name": "devfleet/fix"}],
        },
    }
    status = {
        "kind": "original_pr_repair",
        "publication_authorized": True,
        "request_id": request,
        "repository": "o/r",
        "issue_number": 5,
        "pull_request": 7,
        "source_sha": state.old,
        "source_run_id": 70,
        "run_id": 502,
        "finished": True,
        "conclusion": "success",
        "publication_candidate": manifest,
        "strategic_budget": {
            "request_id": budget,
            "original_request_id": request,
            "original_request_kind": "original_pr_repair",
            "source_sha": controller,
        },
    }
    bot = {"login": "github-actions[bot]", "type": "Bot"}
    incident = {
        "state": "open",
        "title": "CI repair",
        "user": bot,
        "labels": [{"name": "auto-incident"}, {"name": "ai-implement"}],
        "body": "- Workflow: `CI/CD Pipeline`\n- Run ID: `70`\n- Branch: `fix/ci`\n"
        "- Head Repository: `o/r`\n- Self-Heal-Run: `70/1`\n"
        f"- Self-Heal-Workflow: `99@{target.workflow_path}`\n",
    }
    source_run = {
        "id": 70,
        "workflow_id": 99,
        "path": target.workflow_path,
        "run_attempt": 1,
        "event": "pull_request",
        "head_sha": state.old,
        "head_branch": "fix/ci",
        "head_repository": {"full_name": "o/r"},
        "pull_requests": [{"number": 7}],
        "name": "CI/CD Pipeline",
        "conclusion": "failure",
        "status": "completed",
        "created_at": "2026-11-20T01:00:00Z",
    }
    comments, created, calls = [], [], []

    def get(path, params):
        if path.endswith("/issues/5/comments"):
            return 200, comments
        if path.endswith("/pulls/7"):
            return 200, {
                "number": 7,
                "state": "open",
                "draft": False,
                "labels": [],
                "user": {"login": "maintainer"},
                "head": {"sha": state.tip(), "ref": "fix/ci", "repo": {"full_name": "o/r"}},
                "base": {"ref": "main", "repo": {"full_name": "o/r"}},
            }
        if path.endswith("/actions/runs/70"):
            return 200, source_run
        if path.endswith("/actions/workflows/99/runs"):
            return 200, {
                "workflow_runs": [
                    {
                        **source_run,
                        "id": 71,
                        "head_sha": state.new,
                        "status": "queued",
                        "conclusion": None,
                    }
                ]
                if params.get("head_sha") == state.new
                else []
            }
        pytest.fail(f"unexpected read {path}")

    def post(url, _token, body):
        assert url.endswith("/issues/5/comments"), "Original repair never creates another PR"
        comments.append({"id": len(comments) + 1, "user": bot, "body": body["body"]})
        return {"id": len(comments)}

    class Client:
        def __init__(self, *_):
            pass

        def create(self, body):
            created.append(body)
            return task

        def get(self, task_id):
            assert task_id == control
            return task

        def github_run(self, request_id):
            assert request_id == request
            calls.append(request_id)
            return {**status, "publication_authorized": not revoked or len(calls) == 1}

    for key, value in {
        "MODSTORE_PARA_DISPATCH_TOKEN": "fixture-dispatch",
        "PR_CREATE_TOKEN": "fixture-secret",
        "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "o/r",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(mod, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(mod.impl, "_fetch_issue", lambda *_: incident)
    monkeypatch.setattr(mod.impl, "_fetch_issue_comments", lambda *_: comments)
    monkeypatch.setattr(mod.impl, "_is_authorized", lambda *_: (True, "ok", "allowlist"))
    monkeypatch.setattr(mod.impl, "_gh_post", post)
    monkeypatch.setattr(mod, "_read_github", lambda _: get)
    monkeypatch.setattr(mod.repair, "load_trusted_authors", lambda: ["maintainer"])
    monkeypatch.setattr(mod, "DispatchClient", Client)
    monkeypatch.setattr(mod, "_branch_head", lambda *_: state.new)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    advance = mod.repair.advance
    monkeypatch.setattr(
        mod.repair, "advance", lambda *a, **kw: advance(*a, **kw, command=state.command)
    )
    args = SimpleNamespace(
        repo="o/r",
        issue_number=5,
        token="workflow-token",
        base_branch="fix/ci",
        tool="codex",
        dispatch_base="https://example.invalid",
        poll_seconds=0,
        timeout_minutes=1,
    )
    with pytest.raises(SystemExit) as result:
        mod.run(args)
    assert result.value.code == (6 if revoked else 0)
    assert state.tip() == (state.old if revoked else state.new)
    assert len(created) == 1 and len(state.pushes) == (0 if revoked else 1)
    if revoked:
        assert not any(mod.repair.INTENT_MARKER in row["body"] for row in comments)
        return
    with pytest.raises(SystemExit) as replay:
        mod.run(args)
    assert replay.value.code == 0 and len(created) == len(state.pushes) == 1
    saved = json.loads((tmp_path / "para_issue_dispatch_5.json").read_text())
    assert saved["status"] == "pr_updated_ci_observed" and saved["head_sha"] == state.new
    assert saved["control_task_id"] == control and saved["ci_run_id"] == 71
    assert sum(mod.repair.INTENT_MARKER in row["body"] for row in comments) == 1
