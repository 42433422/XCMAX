"""Original company-approved PR publication and automatic resume use real inert Git."""

import copy
import hashlib
import io
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from tests.test_para_github_publication import (
    REQUEST,
    ROOT,
    WORKSPACE,
    artifact,
    isolation_artifact,
    manifest,
    publisher,
)


@pytest.fixture
def original_publication(tmp_path, monkeypatch):
    """Real inert Git objects; only GitHub/management I/O and scanner availability are fixtures."""
    monkeypatch.syspath_prepend(str(ROOT / "FHD"))
    from scripts.dev import para_pr_repair

    monkeypatch.setattr(para_pr_repair, "load_trusted_authors", lambda: ["maintainer"])
    source, remote = tmp_path / "source", tmp_path / "remote.git"
    source.mkdir()

    def git(*args, cwd=source):
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL).strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@example.test")
    git("config", "user.name", "Test")
    (source / "app.py").write_text("value = 0\n")
    git("add", ".")
    git("commit", "-m", "trusted controller")
    controller = git("rev-parse", "HEAD").decode()
    git("checkout", "-b", "fix/ci")
    (source / "app.py").write_text("value = 1\n")
    git("commit", "-am", "original PR")
    base = git("rev-parse", "HEAD").decode()
    git("init", "--bare", str(remote))
    git("push", remote.as_uri(), "main", "fix/ci")
    git("checkout", "-b", manifest()["branch"])
    (source / "app.py").write_text("value = 2\n")
    git("commit", "-am", "repair original PR")
    commit = git("rev-parse", "HEAD").decode()
    bundle = tmp_path / "candidate.bundle"
    git("bundle", "create", str(bundle), f"{base}..{manifest()['branch']}")
    value = {
        **manifest(),
        "base_sha": base,
        "commit_sha": commit,
        "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
    }
    # git archive is binary; do not strip its padding when signing the exact tar stream.
    value["archive_sha256"] = hashlib.sha256(
        subprocess.check_output(["git", "archive", "--format=tar", commit], cwd=source)
    ).hexdigest()
    data, digest = artifact(
        entries=[("manifest.json", json.dumps(value)), ("candidate.bundle", bundle.read_bytes())]
    )
    isolated, isolation = isolation_artifact(
        {"source_sha": base, "controller_sha": controller, "candidate_sha": commit}
    )
    metadata = {
        "id": 456,
        "name": f"para-candidate-{REQUEST}",
        "digest": digest,
        "size_in_bytes": len(data),
        "workflow_run": {"id": 123},
        "expired": False,
    }
    artifacts = {"total_count": 2, "artifacts": [metadata, isolation]}
    blobs = {456: data, 789: isolated}
    state = {
        **WORKSPACE,
        "kind": "original_pr_repair",
        "source_sha": base,
        "controller_sha": controller,
        "source_run_id": 70,
        "source_run_attempt": 2,
        "pull_request": 42,
        "publication_candidate": value,
        "finished": False,
        "strategic_budget": {
            "kind": "original_pr_repair",
            "schema": "strategic-pr-repair/v1",
            "request_id": REQUEST,
            "binding_id": "company-budget-original",
            "source_sha": base,
            "controller_sha": controller,
        },
        "model_allocation": {
            "status": "admitted",
            "execution_isolation": publisher.HEADER_ONLY_PLATFORM_PROFILE,
        },
    }
    state["publication_authorization"] = {
        "schema": "strategic-pr-publication/v1",
        "authorized": True,
        "request_id": REQUEST,
        "binding_id": "company-budget-original",
        "decision_id": "decision-original",
        "opportunity_id": "company-original-pr",
        "proposal_sha256": "e" * 64,
        "original_request_sha256": "f" * 64,
        "repository": "owner/repo",
        "pull_request": 42,
        "issue_number": 42,
        "source_sha": base,
        "controller_sha": controller,
        "source_run_id": 70,
        "source_run_attempt": 2,
        "run_id": 123,
        "run_attempt": 1,
        "task_id": value["task_id"],
        "subtask_id": value["subtask_id"],
        "attempt_id": value["attempt_id"],
        "candidate_sha256": hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest(),
        "candidate_commit_sha": commit,
        "candidate_branch": value["branch"],
        "usage_complete": True,
        "execution_isolation": publisher.HEADER_ONLY_PLATFORM_PROFILE,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": controller,
        "GITHUB_REPOSITORY": "owner/repo",
        "PARA_GITHUB_REQUEST_ID": REQUEST,
        "GH_TOKEN": "publisher-test",
        "MODSTORE_PARA_DISPATCH_TOKEN": "management-test",
        "RUNNER_TEMP": str(tmp_path),
    }
    run = {
        "id": 123,
        "head_sha": controller,
        "workflow_id": 55,
        "head_branch": "main",
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "path": ".github/workflows/fhd-para-github-worker.yml",
        "display_title": f"para-workspace-{REQUEST}",
        "repository": {"full_name": "owner/repo"},
        "status": "completed",
        "conclusion": "success",
    }
    target = para_pr_repair.Target(42, "fix/ci", base, 70, 99, ".github/workflows/fhd-ci-cd.yml", 2)
    source_run = {
        "id": 70,
        "workflow_id": 99,
        "path": target.workflow_path,
        "run_attempt": 2,
        "event": "pull_request",
        "head_sha": base,
        "head_branch": "fix/ci",
        "head_repository": {"full_name": "owner/repo"},
        "pull_requests": [{"number": 42}],
        "name": "CI/CD Pipeline",
        "status": "completed",
        "conclusion": "failure",
        "created_at": "2026-11-20T01:00:00Z",
    }
    incident = {
        "state": "open",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
        "labels": [{"name": "auto-incident"}, {"name": "ai-implement"}],
        "body": "- Workflow: `CI/CD Pipeline`\n- Run ID: `70`\n- Branch: `fix/ci`\n"
        "- Head Repository: `owner/repo`\n- Self-Heal-Run: `70/2`\n"
        f"- Self-Heal-Workflow: `99@{target.workflow_path}`\n",
    }
    pr = {
        "number": 42,
        "state": "open",
        "draft": False,
        "labels": [],
        "user": {"login": "maintainer"},
        "head": {"ref": "fix/ci", "sha": base, "repo": {"full_name": "owner/repo"}},
        "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
    }
    calls, reads = [], []

    def api(path):
        path = urlsplit(path).path
        if path.endswith("/actions/runs/123"):
            return run
        if path.endswith("/artifacts"):
            return artifacts
        if path.endswith("/issues/42"):
            return incident
        if path.endswith("/pulls/42"):
            return pr
        if path.endswith("/actions/runs/70"):
            return source_run
        if path.endswith("/actions/workflows/99/runs"):
            return {"workflow_runs": []}
        pytest.fail(f"unexpected GitHub read {path}")

    def command(args, **kwargs):
        calls.append(args)
        if args[:2] == ["gh", "api"]:
            if args[2].endswith("/zip"):
                return blobs[int(args[2].split("/")[-2])]
            return json.dumps(api(args[2]))
        if args[0] == "gitleaks":
            return "8.18.4\n" if args[1] == "version" else ""
        assert args[0] == "git", "candidate must not execute or create a new PR"
        args = [
            remote.as_uri() if arg == "https://github.com/owner/repo.git" else arg for arg in args
        ]
        return publisher.run_command(args, **kwargs)

    def opener(request, **kwargs):
        assert request.full_url.endswith(f"/github-runs/{REQUEST}")
        reads.append(copy.deepcopy(state))
        return io.BytesIO(json.dumps(state).encode())

    return SimpleNamespace(**locals())


def test_original_publisher_reuses_verified_remote_candidate_without_another_push_or_pr(
    original_publication,
):
    f = original_publication
    first = publisher.publish(f.env, command=f.command, opener=f.opener)
    second = publisher.publish(f.env, command=f.command, opener=f.opener)
    assert first == second and first["delivered"] is False
    assert first["status"] == "awaiting_original_pr_update"
    assert first["pull_request_url"] == "https://github.com/owner/repo/pull/42"
    assert f.git("rev-parse", f"refs/heads/{f.value['branch']}", cwd=f.remote).decode() == f.commit
    assert f.git("rev-parse", "refs/heads/fix/ci", cwd=f.remote).decode() == f.base
    assert sum("push" in call for call in f.calls) == 1
    assert not any(
        call[0] == "node" or any(arg.startswith("--force") for arg in call) for call in f.calls
    )


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "revoked",
        "unknown_usage",
        "expired",
        "source_sha",
        "controller_sha",
        "source_run_attempt",
        "worker_attempt",
        "boolean_attempt",
        "manifest_digest",
        "unbound",
        "retort_kind",
        "retort_schema",
        "isolation_source",
        "isolation_controller",
        "isolation_digest",
        "isolation_missing",
    ],
)
def test_original_publication_gate_requires_current_company_and_immutable_isolation(
    original_publication, fault
):
    f = original_publication
    gate = f.state["publication_authorization"]
    if fault in {"revoked", "unknown_usage"}:
        gate["authorized" if fault == "revoked" else "usage_complete"] = False
    elif fault == "expired":
        gate["expires_at"] = "2020-01-01T00:00:00Z"
    elif fault in {"source_sha", "controller_sha"}:
        gate[fault] = "0" * 40
    elif fault == "source_run_attempt":
        gate[fault] = 1  # Original CI attempt 2 is distinct from worker attempt 1.
    elif fault in {"worker_attempt", "boolean_attempt"}:
        gate["run_attempt"] = 2 if fault == "worker_attempt" else True
    elif fault == "manifest_digest":
        gate["candidate_sha256"] = "0" * 64
    elif fault == "unbound":
        f.state["publication_authorization"] = {}
    elif fault == "retort_kind":
        f.state["strategic_budget"]["kind"] = "github_opencode_workspace"
    elif fault == "retort_schema":
        f.state["strategic_budget"]["schema"] = "strategic-workspace/v1"
    elif fault in {"isolation_source", "isolation_controller"}:
        data, metadata = isolation_artifact(
            {
                "source_sha": f.base,
                "controller_sha": f.controller,
                "candidate_sha": f.commit,
                "source_sha" if fault == "isolation_source" else "controller_sha": "0" * 40,
            }
        )
        f.blobs[789], f.artifacts["artifacts"][1] = data, metadata
    elif fault == "isolation_digest":
        f.artifacts["artifacts"][1]["digest"] = "sha256:" + "0" * 64
    elif fault == "isolation_missing":
        f.artifacts["artifacts"].pop()
    if fault:
        with pytest.raises(ValueError):
            publisher.verify_original_publication(f.state, f.env, f.api, f.blobs.__getitem__)
    else:
        proof = publisher.verify_original_publication(f.state, f.env, f.api, f.blobs.__getitem__)
        assert proof.authorization["source_run_attempt"] == 2
        assert proof.authorization["run_attempt"] == 1
        assert proof.manifest["base_sha"] != f.env["GITHUB_SHA"]
        assert proof.isolation_artifact_id == 789


@pytest.mark.parametrize("fault", [None, "last_read_revoked", "source_rerun", "lost_ack"])
def test_original_publisher_writes_exact_candidate_only_after_fresh_gate(
    original_publication, fault
):
    f = original_publication

    def opener(request, **kwargs):
        if fault == "last_read_revoked" and len(f.reads) == 2:
            f.state["publication_authorization"]["authorized"] = False
        if fault == "source_rerun" and len(f.reads) == 2:
            f.source_run["run_attempt"] = 3
        return f.opener(request, **kwargs)

    def command(args, **kwargs):
        answer = f.command(args, **kwargs)
        if "push" in args and fault == "lost_ack":
            raise subprocess.TimeoutExpired("git push", 1)
        return answer

    if fault in {"last_read_revoked", "source_rerun"}:
        with pytest.raises(ValueError):
            publisher.publish(f.env, command=command, opener=opener)
        assert not any("push" in call for call in f.calls)
        assert f.git("ls-remote", f.remote.as_uri(), f"refs/heads/{f.value['branch']}") == b""
    else:
        result = publisher.publish(f.env, command=command, opener=opener)
        assert result["status"] == "awaiting_original_pr_update"
        assert result["pull_request_url"] == "https://github.com/owner/repo/pull/42"
        assert (
            f.git("rev-parse", f"refs/heads/{f.value['branch']}", cwd=f.remote).decode() == f.commit
        )
        assert sum("push" in call for call in f.calls) == 1
        assert len(f.reads) == 3
    assert f.git("rev-parse", "refs/heads/fix/ci", cwd=f.remote).decode() == f.base
    assert not any("--force" in call or "checkout" in call for call in f.calls)


@pytest.mark.parametrize(
    "fault", [None, "revoked", "changed_artifact", "candidate_moved", "lost_ack", "unknown_ack"]
)
def test_original_advance_uses_bare_git_exact_intent_and_never_repushes_unknown_ack(
    original_publication, monkeypatch, fault
):
    f = original_publication
    repair = f.para_pr_repair
    f.git("push", f.remote.as_uri(), f.value["branch"])
    f.state["finished"] = (
        True  # Publishing has completed; original advance still needs the live gate.
    )
    monkeypatch.setattr(repair.publication, "run_command", f.command)
    proof = repair.verify_publication(
        f.state,
        f.target,
        f.commit,
        repo="owner/repo",
        control_task_id=REQUEST.replace("-", ""),
        para_task_id="task-1",
        github_run_id=123,
        token="read-only",
    )
    intents, writes = [], []

    def before_write():
        intents.append(
            repair.intent_body(
                "owner/repo",
                42,
                f.target,
                f.commit,
                control_task_id=REQUEST,
                para_task_id="task-1",
                github_run_id=123,
            )
        )
        if fault == "revoked":
            f.state["publication_authorization"]["authorized"] = False
        if fault == "changed_artifact":
            f.artifacts["artifacts"][1]["id"] = 790
            f.blobs[790] = f.blobs[789]
        return repair.verify_publication(
            f.state,
            f.target,
            f.commit,
            repo="owner/repo",
            control_task_id=REQUEST,
            para_task_id="task-1",
            github_run_id=123,
            token="read-only",
        )

    def command(args, **kwargs):
        if "push" in args:
            assert len(intents) == 1, "persist the exact original intent before any write"
            writes.append(args)
            if fault == "unknown_ack":
                raise subprocess.TimeoutExpired("git push", 1)
        answer = f.command(args, **kwargs)
        if "push" in args and fault == "lost_ack":
            raise subprocess.TimeoutExpired("git push", 1)
        return answer

    if fault == "candidate_moved":
        f.git("update-ref", f"refs/heads/{f.value['branch']}", f.base, cwd=f.remote)
    if fault in {"revoked", "changed_artifact", "candidate_moved", "unknown_ack"}:
        with pytest.raises(ValueError):
            repair.advance(
                "https://github.com/owner/repo.git",
                f.target,
                f.commit,
                "write-only",
                before_write=before_write,
                authorization=proof,
                command=command,
            )
        assert f.git("rev-parse", "refs/heads/fix/ci", cwd=f.remote).decode() == f.base
        assert len(writes) == (1 if fault == "unknown_ack" else 0)
    else:
        assert (
            repair.advance(
                "https://github.com/owner/repo.git",
                f.target,
                f.commit,
                "write-only",
                before_write=before_write,
                authorization=proof,
                command=command,
            )
            == 1
        )
        assert f.git("rev-parse", "refs/heads/fix/ci", cwd=f.remote).decode() == f.commit
        assert len(writes) == 1
    assert not any("--force" in call or "checkout" in call for call in f.calls)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "ledger_delay",
        "unbound",
        "revoked",
        "fork_event",
        "rerun",
        "event_sha",
        "wrong_controller",
        "wrong_run",
        "wrong_source_attempt",
        "wrong_task",
        "wrong_workflow",
        "other_worker_kind",
        "applied",
    ],
)
def test_completed_worker_event_resumes_original_producer_without_dispatch(
    original_publication, monkeypatch, tmp_path, fault
):
    from scripts.dev import para_issue_dispatch as dispatch

    f = original_publication
    control_id = REQUEST.replace("-", "")
    f.git("push", f.remote.as_uri(), f.value["branch"])
    event = {
        "action": "completed",
        "repository": {"full_name": "owner/repo"},
        "workflow_run": copy.deepcopy(f.run),
    }
    comments = [{"author_association": "OWNER", "user": {"login": "owner"}, "body": "确认实现"}]
    writes, polls, ledger = [], [], []
    if fault == "unbound":
        f.state["publication_authorization"] = {}
    elif fault == "revoked":
        f.state["publication_authorization"]["authorized"] = False
    elif fault == "fork_event":
        event["repository"]["full_name"] = "fork/repo"
    elif fault == "rerun":
        event["workflow_run"]["run_attempt"] = 2
    elif fault == "event_sha":
        event["workflow_run"]["head_sha"] = "0" * 40
    elif fault == "wrong_controller":
        f.state["controller_sha"] = "0" * 40
    elif fault == "wrong_run":
        f.state["run_id"] = 124
    elif fault == "wrong_source_attempt":
        f.state["source_run_attempt"] = 1
    elif fault == "wrong_workflow":
        f.run["path"] = ".github/workflows/unrelated.yml"
    elif fault == "other_worker_kind":
        f.state["kind"] = "customer_feedback_repair"
    elif fault == "applied":
        f.git("push", f.remote.as_uri(), f"{f.commit}:refs/heads/fix/ci")
        f.state["publication_authorization"]["authorized"] = False
        f.pr["labels"] = [{"name": "hold-merge"}]
        comments.append(
            {
                "user": {"login": "github-actions[bot]", "type": "Bot"},
                "body": dispatch.repair.intent_body(
                    "owner/repo",
                    42,
                    f.target,
                    f.commit,
                    control_task_id=control_id,
                    para_task_id="task-1",
                    github_run_id=123,
                ),
            }
        )

    def github(url, _token):
        parsed = urlsplit(url)
        if parsed.path.endswith("/issues/42/comments"):
            return comments
        if parsed.path.endswith("/pulls/42"):
            f.pr["head"]["sha"] = f.git("rev-parse", "refs/heads/fix/ci", cwd=f.remote).decode()
        if "/branches/" in parsed.path:
            branch = unquote(parsed.path.split("/branches/", 1)[1])
            return {
                "commit": {"sha": f.git("rev-parse", f"refs/heads/{branch}", cwd=f.remote).decode()}
            }
        if parsed.path.endswith("/actions/workflows/99/runs") and parse_qs(parsed.query).get(
            "head_sha"
        ) == [f.commit]:
            return {
                "workflow_runs": [
                    {
                        **f.source_run,
                        "id": 71,
                        "head_sha": f.commit,
                        "status": "queued",
                        "conclusion": None,
                    }
                ]
            }
        return f.api(url)

    def post(url, _token, payload):
        assert url.endswith(
            "/issues/42/comments"
        ), "the resume must not open another PR or dispatch"
        writes.append(payload)
        comments.append({"user": {"login": "github-actions[bot]", "type": "Bot"}, **payload})
        return {"id": len(comments)}

    class Client:
        def __init__(self, *_args):
            pass

        def create(self, *_args):
            pytest.fail("a worker completion must never create another model task")

        def publication(self, task_id):
            assert task_id == control_id
            ledger.append(task_id)
            if fault == "ledger_delay" and len(ledger) == 1:
                raise OSError("temporary original ledger read failure")
            return copy.deepcopy(f.state)

        def get(self, task_id):
            assert task_id == control_id
            polls.append(task_id)
            completed = len(polls) >= 4
            if completed:
                f.state["finished"] = True
            return {
                "id": "other" if fault == "wrong_task" else control_id,
                "executor": "original_pr_repair",
                "github_run_id": 123,
                "para_task_id": "task-1",
                "state": "execution_completed" if completed else "waiting_phase",
                "execution": (
                    {
                        "subtasks": [{"branch_name": f.value["branch"]}],
                        "reports": [
                            {
                                "report": {
                                    "pushed": True,
                                    "branch": f.value["branch"],
                                    "commit_sha": f.commit,
                                }
                            }
                        ],
                    }
                    if completed
                    else {}
                ),
            }

    advance = dispatch.repair.advance
    monkeypatch.setattr(
        dispatch.repair, "advance", lambda *a, **kw: advance(*a, **kw, command=f.command)
    )
    monkeypatch.setattr(dispatch.repair.publication, "run_command", f.command)
    monkeypatch.setattr(dispatch, "DispatchClient", Client)
    monkeypatch.setattr(dispatch.impl, "_gh_get", github)
    monkeypatch.setattr(dispatch.impl, "_gh_post", post)
    monkeypatch.setattr(dispatch, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(dispatch.time, "sleep", lambda _seconds: None)
    event_path, output = tmp_path / "event.json", tmp_path / "outputs"
    event_path.write_text(json.dumps(event))
    for key, value in {
        **f.env,
        "GITHUB_EVENT_NAME": "workflow_run",
        "GITHUB_EVENT_PATH": str(event_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_TOKEN": "read-token",
        "PR_CREATE_TOKEN": "write-token",
    }.items():
        monkeypatch.setenv(key, value)
    argv = [
        "para_issue_dispatch.py",
        "--repo",
        "owner/repo",
        "--resume-worker-event",
        "--poll-seconds",
        "0",
    ]
    monkeypatch.setattr(sys, "argv", [*argv, "--resolve-only"])
    if fault not in {None, "ledger_delay", "other_worker_kind", "applied"}:
        with pytest.raises(SystemExit, match="identity rejected"):
            dispatch.main()
        assert not output.exists() and not writes
    else:
        dispatch.main()  # Read-only resolve job, before same-Issue native concurrency.
        assert not writes and not any("push" in call for call in f.calls)
        if fault == "other_worker_kind":
            assert not output.exists() and not polls
            return
        assert output.read_text() == "issue_number=42\n"
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as result:
            dispatch.main()
        assert result.value.code == 0
        assert f.git("rev-parse", "refs/heads/fix/ci", cwd=f.remote).decode() == f.commit
        assert sum("push" in call for call in f.calls) == (0 if fault == "applied" else 1)
        if fault == "applied":
            assert not writes
        else:
            assert (
                len(polls) >= 4
            ), "empty completion projection must wait on the same original task"
            assert (
                sum(item["body"].startswith(dispatch.repair.INTENT_MARKER) for item in writes) == 1
            )
        report = json.loads((dispatch.REPORT_DIR / "para_issue_dispatch_42.json").read_text())
        assert report["status"] == "pr_updated_ci_observed" and report["ci_run_id"] == 71
