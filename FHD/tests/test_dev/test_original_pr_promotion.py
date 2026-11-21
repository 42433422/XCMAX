"""Original PR promotion preserves drift checks with verified artifacts and ordinary Git."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import uuid
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
    (seed / "module.py").write_text("value = 0\n")
    run("add", "module.py")
    run("commit", "-m", "base")
    controller = run("rev-parse", "HEAD")
    run("checkout", "-b", "fix/ci")
    (seed / "module.py").write_text("value = 1\n")
    run("commit", "-am", "original PR")
    old = run("rev-parse", "HEAD")
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
        controller=controller,
        other=other,
        orphan=orphan,
        pushes=[],
        lost_ack=False,
    )
    state.tip = lambda: run("rev-parse", "refs/heads/fix/ci", cwd=remote)
    state.update = lambda sha: run("update-ref", "refs/heads/fix/ci", sha, cwd=remote)

    def command(args, **kwargs):
        assert all("fixture-secret" not in argument for argument in args)
        assert not any(argument.startswith("--force") for argument in args)
        if args[:2] == ["gh", "api"]:
            if args[2].endswith("/zip"):
                return state.blobs[int(args[2].split("/")[-2])]
            return json.dumps(state.api(args[2]))
        mapped = [str(remote) if argument == state.url else argument for argument in args]
        value = subprocess.run(mapped, check=True, capture_output=True, text=True, **kwargs).stdout
        if "push" in args:
            state.pushes.append(args)
            if state.lost_ack:
                raise subprocess.CalledProcessError(128, ["git", "push"], stderr="ack lost")
        return value

    state.command = command
    state.target = mod.repair.Target(7, "fix/ci", old, 70, 99, ".github/workflows/fhd-ci-cd.yml", 2)
    state.request = str(uuid.UUID(hex="1" * 32))
    state.env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": "502",
        "GITHUB_SHA": controller,
        "PARA_GITHUB_REQUEST_ID": state.request,
    }
    state.worker = {
        "id": 502,
        "run_attempt": 1,
        "head_sha": controller,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "path": ".github/workflows/fhd-para-github-worker.yml",
        "display_title": f"para-workspace-{state.request}",
        "repository": {"full_name": "o/r"},
        "status": "completed",
        "conclusion": "success",
    }
    state.status = {
        "kind": "original_pr_repair",
        "request_id": state.request,
        "repository": "o/r",
        "issue_number": 5,
        "pull_request": 7,
        "source_sha": old,
        "controller_sha": controller,
        "source_run_id": 70,
        "source_run_attempt": 2,
        "run_id": 502,
        "finished": True,
        "model_allocation": {
            "status": "admitted",
            "execution_isolation": mod.repair.publication.HEADER_ONLY_PLATFORM_PROFILE,
        },
        "strategic_budget": {
            "kind": "original_pr_repair",
            "schema": "strategic-pr-repair/v1",
            "request_id": state.request,
            "binding_id": "company-original-pr",
            "source_sha": old,
            "controller_sha": controller,
        },
    }

    def api(path):
        if path.endswith("/actions/runs/502"):
            return state.worker
        if path.endswith("/artifacts?per_page=100"):
            return state.artifacts
        pytest.fail(f"unexpected publication evidence read {path}")

    def authorize(candidate):
        bundle = tmp_path / "candidate.bundle"
        run("bundle", "create", str(bundle), "--all")
        manifest = {
            "schema": "para-github-candidate/v1",
            "request_id": state.request,
            "run_id": "502",
            "repository": "o/r",
            "base_sha": old,
            "commit_sha": candidate,
            "task_id": "para1",
            "subtask_id": "subtask1",
            "attempt_id": "attempt1",
            "branch": "devfleet/fix",
            "pushed": False,
            "publication": "artifact_pending",
            "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "archive_sha256": hashlib.sha256(
                subprocess.check_output(["git", "archive", "--format=tar", candidate], cwd=seed)
            ).hexdigest(),
        }
        isolation = {
            "request_id": state.request,
            "run_id": "502",
            "status": "awaiting_publication",
            "finished": False,
            "execution_isolation": mod.repair.publication.HEADER_ONLY_PLATFORM_PROFILE,
            "source_sha": old,
            "controller_sha": controller,
            "candidate_sha": candidate,
        }
        state.blobs, metadata = {}, []
        for artifact_id, kind, files in (
            (
                456,
                "candidate",
                {"manifest.json": json.dumps(manifest), "candidate.bundle": bundle.read_bytes()},
            ),
            (789, "execution", {"execution.json": json.dumps(isolation)}),
        ):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as archive:
                for name, contents in files.items():
                    archive.writestr(name, contents)
            blob = output.getvalue()
            state.blobs[artifact_id] = blob
            metadata.append(
                {
                    "id": artifact_id,
                    "name": f"para-{kind}-{state.request}",
                    "size_in_bytes": len(blob),
                    "digest": "sha256:" + hashlib.sha256(blob).hexdigest(),
                    "workflow_run": {"id": 502},
                    "expired": False,
                }
            )
        state.artifacts = {"total_count": 2, "artifacts": metadata}
        state.status["publication_candidate"] = manifest
        state.status["publication_authorization"] = {
            "schema": "strategic-pr-publication/v1",
            "authorized": True,
            "request_id": state.request,
            "binding_id": "company-original-pr",
            "decision_id": "decision-original",
            "opportunity_id": "original-pr-repair",
            "proposal_sha256": "e" * 64,
            "original_request_sha256": "f" * 64,
            "repository": "o/r",
            "pull_request": 7,
            "issue_number": 5,
            "source_sha": old,
            "controller_sha": controller,
            "source_run_id": 70,
            "source_run_attempt": 2,
            "run_id": 502,
            "run_attempt": 1,
            "task_id": "para1",
            "subtask_id": "subtask1",
            "attempt_id": "attempt1",
            "candidate_sha256": hashlib.sha256(
                json.dumps(
                    manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
            ).hexdigest(),
            "candidate_commit_sha": candidate,
            "candidate_branch": "devfleet/fix",
            "usage_complete": True,
            "execution_isolation": mod.repair.publication.HEADER_ONLY_PLATFORM_PROFILE,
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
        return mod.repair.publication.verify_original_publication(
            state.status, state.env, api, state.blobs.__getitem__, allow_finished=True
        )

    state.api, state.authorize = api, authorize
    state.proof = authorize(new)
    return state


@pytest.mark.parametrize("case", ["main", "unrelated", "before_fetch", "during_write", "replay"])
def test_original_ref_never_rewrites_drift_or_accepts_unrelated_history(repository, case):
    state, target, candidate = repository, repository.target, repository.new
    before = state.old
    if case == "main":
        target = replace(target, branch="main")
    elif case == "unrelated":
        candidate = state.orphan
        subprocess.run(
            ["git", "-C", str(state.remote), "update-ref", "refs/heads/devfleet/fix", candidate],
            check=True,
        )
    elif case in {"before_fetch", "replay"}:
        before = state.new if case == "replay" else state.other
        state.update(before)
    proof = state.authorize(candidate)

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
            authorization=proof,
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
    manifest = state.status["publication_candidate"]
    report = {
        "source": "github_isolated_publisher",
        "pushed": True,
        "request_id": state.request,
        "branch": "devfleet/fix",
        "commit_sha": state.new,
        "github_run_id": 502,
        "controller_sha": state.controller,
        "publication_job_id": 600,
    }
    task = {
        "id": control,
        "state": "execution_completed",
        "executor": "original_pr_repair",
        "para_task_id": "para1",
        "github_run_id": 502,
        "execution": {
            "candidate": manifest,
            "reports": [{"report": report}],
            "subtasks": [{"branch_name": "devfleet/fix"}],
        },
    }
    bot = {"login": "github-actions[bot]", "type": "Bot"}
    incident = {
        "state": "open",
        "title": "CI repair",
        "user": bot,
        "labels": [{"name": "auto-incident"}, {"name": "ai-implement"}],
        "body": "- Workflow: `CI/CD Pipeline`\n- Run ID: `70`\n- Branch: `fix/ci`\n"
        "- Head Repository: `o/r`\n- Self-Heal-Run: `70/2`\n"
        f"- Self-Heal-Workflow: `99@{target.workflow_path}`\n",
    }
    source_run = {
        "id": 70,
        "workflow_id": 99,
        "path": target.workflow_path,
        "run_attempt": 2,
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
        if path.endswith("/issues/5"):
            return 200, incident
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

        def publication(self, task_id):
            assert task_id == control
            calls.append(task_id)
            return {
                **state.status,
                "publication_authorization": {
                    **state.status["publication_authorization"],
                    "authorized": not revoked or len(calls) == 1,
                },
            }

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
    monkeypatch.setattr(mod.repair.publication, "run_command", state.command)
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
    # The original intent is persisted before the final authority read. Revocation
    # prevents the push; a retry keeps this exact intent and never creates another task.
    assert sum(mod.repair.INTENT_MARKER in row["body"] for row in comments) == 1
    with pytest.raises(SystemExit) as replay:
        mod.run(args)
    assert replay.value.code == (6 if revoked else 0)
    assert len(created) == 1 and len(state.pushes) == (0 if revoked else 1)
    saved = json.loads((tmp_path / "para_issue_dispatch_5.json").read_text())
    assert saved["status"] == ("pr_update_unconfirmed" if revoked else "pr_updated_ci_observed")
    assert saved["head_sha"] == state.new and saved["control_task_id"] == control
    assert saved["ci_run_id"] == (0 if revoked else 71)
    assert sum(mod.repair.INTENT_MARKER in row["body"] for row in comments) == 1
