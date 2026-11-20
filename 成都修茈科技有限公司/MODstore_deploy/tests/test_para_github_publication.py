"""The job boundary carries inert objects; original dispatch evidence controls publication."""

import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from modstore_server import para_github_publication as publication
from tests.test_incident_team_continuation import incident as incident_fixture
from tests.test_para_first_no_planning_llm import fresh_db as fresh_db_fixture

incident = incident_fixture
fresh_db = fresh_db_fixture

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "publish_para_candidate", ROOT / "FHD/scripts/autonomy/publish_para_candidate.py"
)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
REQUEST = "11111111-2222-4333-8444-555555555555"
ATTEMPT = "a" * 32
WORKSPACE = {
    "request_id": REQUEST,
    "run_id": 123,
    "repository": "owner/repo",
    "issue_number": 42,
    "source_sha": "b" * 40,
}


def receipt():
    return {
        "source": "executor_git_readback",
        "pushed": False,
        "publication": "artifact_pending",
        "base_sha": "b" * 40,
        "branch": "devfleet/codex/sub-test",
        "task_id": "task-1",
        "subtask_id": "sub-1",
        "attempt_id": ATTEMPT,
        "commit_sha": "c" * 40,
        "archive_sha256": "d" * 64,
        "bundle_sha256": hashlib.sha256(b"bundle").hexdigest(),
    }


def task():
    marker = hashlib.sha256(REQUEST.encode()).hexdigest()[:32]
    return {
        "id": "task-1",
        "title": f"[xcmax:{marker}:{ATTEMPT}] fix",
        "status": "completed",
        "repo_url": "https://github.com/owner/repo.git",
        "branch": "b" * 40,
        "subTasks": [
            {
                "id": "sub-1",
                "device_id": "cloud",
                "status": "completed",
                "branch_name": "devfleet/codex/sub-test",
                "logs": [{"content": json.dumps(receipt())}],
            }
        ],
    }


def snapshot(value=None):
    from modstore_server.para_delegate_handler import _task_result_snapshot

    return _task_result_snapshot({"task": value or task()})


def manifest():
    return publication.candidate_receipt(snapshot(), WORKSPACE, ATTEMPT)


def artifact(value=None, entries=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in entries or [
            ("manifest.json", json.dumps(value or manifest())),
            ("candidate.bundle", b"bundle"),
        ]:
            archive.writestr(name, data)
    data = stream.getvalue()
    return data, "sha256:" + hashlib.sha256(data).hexdigest()


def test_original_single_fix_receipt_is_required_without_advancing_team(monkeypatch):
    from modstore_server import customer_ticket_github

    monkeypatch.setattr(customer_ticket_github, "authorized_incident", lambda *a: True)
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_API_BASE", "https://para.example.test")
    output = {
        "handler": "para_delegate",
        "executor": "github_actions",
        "accepted": True,
        "task_id": "task-1",
        "required_subtask_ids": ["sub-1"],
        "planned_devices": ["cloud"],
    }
    payload = {
        "github_workspace": WORKSPACE,
        "_team_claim": {
            "ok": False,
            "team": [
                {
                    "role": "fix",
                    "attempt_id": ATTEMPT,
                    "status": "pending",
                    "handler_outputs": {"outputs": [output]},
                }
            ],
        },
    }
    event = SimpleNamespace(id=12, payload_json=json.dumps(payload))
    calls = []

    def fetch(base, task_id):
        calls.append((base, task_id))
        return task()

    result = publication.publication_candidate(None, event, fetcher=fetch)
    assert result == manifest()
    assert calls == [("https://para.example.test", "task-1")]
    assert json.loads(event.payload_json) == payload  # No candidate => completed promotion.
    assert (
        publication.publication_candidate(
            None, event, fetcher=lambda *a: {**task(), "status": "running"}
        )
        is None
    )
    bad = task()
    bad["title"] = "other request"
    with pytest.raises(ValueError, match="dispatch_mismatch"):
        publication.publication_candidate(None, event, fetcher=lambda *a: bad)
    payload["_team_claim"]["team"].append(copy.deepcopy(payload["_team_claim"]["team"][0]))
    event.payload_json = json.dumps(payload)
    with pytest.raises(ValueError, match="one_fix_attempt"):
        publication.publication_candidate(None, event, fetcher=fetch)
    monkeypatch.setattr(customer_ticket_github, "authorized_incident", lambda *a: False)
    assert (
        publication.publication_candidate(
            None, event, fetcher=lambda *a: pytest.fail("unauthorized fetch")
        )
        is None
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("branch", "main"),
        ("attempt_id", "e" * 32),
        ("task_id", "foreign"),
        ("base_sha", "e" * 40),
        ("pushed", True),
    ],
)
def test_candidate_cannot_change_original_dispatch(key, value):
    raw = task()
    evidence = receipt()
    evidence[key] = value
    raw["subTasks"][0]["logs"][0]["content"] = json.dumps(evidence)
    with pytest.raises(ValueError, match="identity_mismatch"):
        publication.candidate_receipt(snapshot(raw), WORKSPACE, ATTEMPT)


def test_multiple_candidates_and_subtasks_are_not_arbitrarily_selected():
    raw = task()
    second = receipt()
    second["commit_sha"] = "e" * 40
    raw["subTasks"][0]["logs"].append({"content": json.dumps(second)})
    with pytest.raises(ValueError, match="ambiguous"):
        publication.candidate_receipt(snapshot(raw), WORKSPACE, ATTEMPT)
    raw = task()
    raw["subTasks"].append({**raw["subTasks"][0], "id": "sub-2"})
    with pytest.raises(ValueError, match="one_fix_subtask"):
        publication.candidate_receipt(snapshot(raw), WORKSPACE, ATTEMPT)


def test_artifact_digest_paths_symlinks_and_bundle_hash_fail_closed():
    data, digest = artifact()
    assert publisher.safe_artifact(data, digest)[0] == manifest()
    with pytest.raises(ValueError, match="digest_mismatch"):
        publisher.safe_artifact(data + b"changed", digest)
    for bad_path in [
        "../candidate.bundle",
        "/candidate.bundle",
        "a/candidate.bundle",
        "candidate.bundle\\evil",
    ]:
        data, digest = artifact(
            entries=[("manifest.json", json.dumps(manifest())), (bad_path, "bundle")]
        )
        with pytest.raises(ValueError, match="unexpected_paths"):
            publisher.safe_artifact(data, digest)
    link = zipfile.ZipInfo("candidate.bundle")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    data, digest = artifact(
        entries=[("manifest.json", json.dumps(manifest())), (link, "/etc/passwd")]
    )
    with pytest.raises(ValueError, match="non_regular"):
        publisher.safe_artifact(data, digest)
    data, digest = artifact(
        entries=[
            ("manifest.json", json.dumps(manifest())),
            ("candidate.bundle", "changed"),
        ]
    )
    with pytest.raises(ValueError, match="bundle_digest"):
        publisher.safe_artifact(data, digest)


def test_publication_binds_run_attempt_workflow_and_authoritative_receipt():
    value = manifest()
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": "b" * 40,
        "GITHUB_REPOSITORY": "owner/repo",
        "PARA_GITHUB_REQUEST_ID": REQUEST,
    }
    state = {**WORKSPACE, "publication_candidate": value, "finished": False}
    run = {
        "id": 123,
        "head_sha": "b" * 40,
        "head_branch": "main",
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "path": ".github/workflows/fhd-para-github-worker.yml",
        "display_title": f"para-workspace-{REQUEST}",
        "repository": {"full_name": "owner/repo"},
    }
    publisher.validate_binding(value, state, run, env)
    for bad in [
        {**run, "run_attempt": 2},
        {**run, "path": ".github/workflows/other.yml"},
        {**run, "id": 321},
    ]:
        with pytest.raises(ValueError, match="binding_mismatch"):
            publisher.validate_binding(value, state, bad, env)
    forged = {**value, "branch": "devfleet/other"}
    with pytest.raises(ValueError, match="original_receipt"):
        publisher.validate_binding(forged, state, run, env)


@pytest.mark.parametrize(
    "control_change",
    [None, "add", "modify", "delete", "rename", "nested", "symlink", "newline"],
)
def test_real_git_bundle_import_never_executes_or_publishes_actions_controls(
    tmp_path, control_change
):
    source = tmp_path / "source"
    source.mkdir()

    def git(*args):
        return subprocess.check_output(
            ["git", *args], cwd=source, stderr=subprocess.DEVNULL
        ).strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@example.test")
    git("config", "user.name", "Test")
    (source / "app").write_text("before")
    workflow = source / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: Trusted CI\non: push\njobs: {}\n")
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD").decode()
    git("checkout", "-b", "devfleet/codex/sub-test")
    (source / "app").write_text("after")
    # Candidate may propose malicious config/scripts; publisher never loads or runs them.
    (source / ".gitconfig").write_text("[core]\n hooksPath = /bad/hooks\n")
    (source / "setup.py").write_text("raise RuntimeError('candidate must never run')\n")
    if control_change == "add":
        workflow.with_name("new.yml").write_text("on: push\njobs: {}\n")
    elif control_change == "modify":
        workflow.write_text("on: push\npermissions: write-all\njobs: {}\n")
    elif control_change == "delete":
        workflow.unlink()
    elif control_change == "rename":
        workflow.rename(source / "renamed-workflow.yml")
    elif control_change == "nested":
        nested = source / "FHD" / ".github" / "workflows" / "ci.yml"
        nested.parent.mkdir(parents=True)
        nested.write_text("on: push\njobs: {}\n")
    elif control_change == "symlink":
        (source / "FHD").mkdir()
        (source / "FHD" / ".github").symlink_to("../.github", target_is_directory=True)
    elif control_change == "newline":
        nested = source / "odd\nname" / ".github" / "workflows" / "ci.yml"
        nested.parent.mkdir(parents=True)
        nested.write_text("on: push\njobs: {}\n")
    git("add", ".")
    git("commit", "-m", "candidate")
    target = git("rev-parse", "HEAD").decode()
    archive = subprocess.check_output(["git", "archive", "--format=tar", target], cwd=source)
    bundle_path = tmp_path / "candidate.bundle"
    git("bundle", "create", str(bundle_path), f"{base}..devfleet/codex/sub-test")
    value = {
        **manifest(),
        "base_sha": base,
        "commit_sha": target,
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
    }
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        if args[0] == "gitleaks":
            return "8.18.4\n" if args[1] == "version" else ""
        args = [source.as_uri() if a == "https://github.com/owner/repo.git" else a for a in args]
        return publisher.run_command(args, **kwargs)

    destination = tmp_path / "publisher"
    destination.mkdir()
    env = publisher.clean_git_env(
        {
            **os.environ,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": "/bad",
        }
    )
    assert "GIT_CONFIG_COUNT" not in env
    if control_change:
        with pytest.raises(ValueError, match="actions_control_change_requires_review"):
            publisher.import_candidate(
                destination, value, bundle_path.read_bytes(), env=env, command=command
            )
        assert not any("checkout" in c or "push" in c for c in calls)
        return
    publisher.import_candidate(
        destination, value, bundle_path.read_bytes(), env=env, command=command
    )
    assert not any("checkout" in c for c in calls)
    assert not (destination / "objects.git" / "setup.py").exists()
    with pytest.raises(ValueError, match="archive_digest"):
        bad = tmp_path / "bad"
        bad.mkdir()
        publisher.import_candidate(
            bad,
            {**value, "archive_sha256": "0" * 64},
            bundle_path.read_bytes(),
            env=env,
            command=command,
        )


@pytest.mark.skipif(not shutil.which("gitleaks"), reason="requires pinned Gitleaks 8.18.4")
@pytest.mark.parametrize(
    "location",
    [
        "clean",
        "added",
        "candidate_ignores",
        "removed_later",
        "message",
        "merge",
        "removed_base",
        "attributes",
        "binary",
    ],
)
def test_real_gitleaks_scans_full_candidate_history_with_trusted_policy(tmp_path, location):
    source = tmp_path / "source"
    source.mkdir()

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=source, stderr=subprocess.PIPE).strip()

    # Synthetic recognizable fixture, assembled so this test itself contains no token.
    secret = "ghp_" + "ABCDefgh0123456789" * 2
    git("init", "-b", "main")
    git("config", "user.email", "test@example.test")
    git("config", "user.name", "Test")
    app = source / "app.py"
    app.write_text(f"token = '{secret}'\n" if location == "removed_base" else "answer = 0\n")
    git("add", ".")
    git("commit", "-m", "trusted base")
    base = git("rev-parse", "HEAD").decode()
    git("checkout", "-b", "devfleet/codex/sub-test")
    app.write_text("answer = 1\n")
    if location in {"added", "candidate_ignores", "removed_later", "attributes"}:
        app.write_text(f"token = '{secret}'  # gitleaks:allow\n")
    if location == "attributes":
        (source / ".gitattributes").write_text("app.py -diff\n")
    elif location == "binary":
        app.write_bytes(b"\0token = '" + secret.encode() + b"'\n")
    message = f"candidate token = {secret}" if location == "message" else "candidate"
    git("add", ".")
    git("commit", "-m", message)
    if location == "candidate_ignores":
        leak_commit = git("rev-parse", "HEAD").decode()
        (source / ".gitleaks.toml").write_text("[allowlist]\nregexes = ['.*']\n")
        (source / ".gitleaksignore").write_text(f"{leak_commit}:app.py:github-pat:1\n")
        (source / ".gitconfig").write_text("[diff]\n external = /must-not-run\n")
        git("add", ".")
        git("commit", "-m", "candidate attempts to suppress scanning")
    elif location == "removed_later":
        app.write_text("answer = 1\n")
        git("add", ".")
        git("commit", "-m", "remove earlier secret")
    elif location == "merge":
        git("checkout", "-b", "side", base)
        (source / "side.py").write_text("answer = 2\n")
        git("add", ".")
        git("commit", "-m", "side branch")
        git("checkout", "devfleet/codex/sub-test")
        git("merge", "--no-ff", "--no-commit", "side")
        app.write_text(f"token = '{secret}'\n")
        git("add", ".")
        git("commit", "-m", "merge resolution introduces a secret")
    target = git("rev-parse", "HEAD").decode()
    archive = subprocess.check_output(["git", "archive", "--format=tar", target], cwd=source)
    bundle = tmp_path / "candidate.bundle"
    git("bundle", "create", str(bundle), f"{base}..devfleet/codex/sub-test")
    value = {
        **manifest(),
        "base_sha": base,
        "commit_sha": target,
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
    }
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        if args[0] == "gitleaks":
            assert set(kwargs["env"]) == {
                "PATH",
                "HOME",
                "GIT_CONFIG_NOSYSTEM",
                "GIT_CONFIG_GLOBAL",
                "GIT_TERMINAL_PROMPT",
            }
        args = [source.as_uri() if a == "https://github.com/owner/repo.git" else a for a in args]
        return publisher.run_command(args, **kwargs)

    destination = tmp_path / "publisher"
    destination.mkdir()
    env = publisher.clean_git_env(
        {
            **os.environ,
            "GH_TOKEN": "fixture-publisher-only",
            "GITLEAKS_CONFIG": str(source / ".gitleaks.toml"),
        }
    )
    if location in {"clean", "removed_base"}:
        publisher.import_candidate(
            destination, value, bundle.read_bytes(), env=env, command=command
        )
        assert any("--pipe" in c for c in calls)
    else:
        with pytest.raises(
            ValueError, match="candidate_secret_scan_unavailable_or_rejected"
        ) as error:
            publisher.import_candidate(
                destination, value, bundle.read_bytes(), env=env, command=command
            )
        assert secret not in str(error.value)
    assert not any("push" in c or "checkout" in c for c in calls)


@pytest.mark.parametrize(
    "failure", ["missing", "wrong_version", "scan_failed", "message_scan_failed"]
)
def test_secret_scan_fails_closed_without_echoing_scanner_output(tmp_path, failure):
    def command(args, **kwargs):
        if args[0] == "gitleaks":
            if failure == "missing":
                raise FileNotFoundError("fixture-private-key")
            if args[1] == "version":
                return "8.18.3" if failure == "wrong_version" else "8.18.4"
            if failure == "scan_failed" or (failure == "message_scan_failed" and "--pipe" in args):
                raise subprocess.CalledProcessError(1, args, output="fixture-private-key")
            return ""
        return "clean commit message"

    with pytest.raises(
        ValueError, match="^candidate_secret_scan_unavailable_or_rejected$"
    ) as error:
        publisher.scan_candidate(tmp_path, "a" * 40, "b" * 40, env={}, command=command)
    assert "fixture-private-key" not in str(error.value)


def test_staged_receipt_waits_for_exact_remote_branch_and_pr(monkeypatch):
    from modstore_server import customer_ticket_github as bridge
    from modstore_server import para_github_runner
    from modstore_server.para_github_runner import verified_code_identity

    monkeypatch.setenv("MODSTORE_GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr(para_github_runner, "resume_worker_ready", lambda workspace: True)

    def github(method, path):
        if "/git/ref/" in path:
            return {"object": {"sha": "c" * 40}}
        if "/actions/runs/" in path:
            return {"head_sha": "b" * 40, "run_attempt": 1}
        return [
            {
                "head": {"sha": "c" * 40, "ref": "devfleet/codex/sub-test"},
                "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
                "body": "Refs #42",
            }
        ]

    monkeypatch.setattr(bridge, "github", github)
    result = verified_code_identity(snapshot(), workspace=WORKSPACE, attempt_id=ATTEMPT)
    assert result["commit_sha"] == "c" * 40
    monkeypatch.setattr(bridge, "github", lambda *a: {"object": {"sha": "e" * 40}})
    with pytest.raises(ValueError, match="不一致"):
        verified_code_identity(snapshot(), workspace=WORKSPACE, attempt_id=ATTEMPT)


@pytest.mark.parametrize("kind", [None, "original_pr_repair", "customer_feedback_repair"])
def test_publisher_reuses_same_remote_sha_and_pr_and_retains_pending_delivery(
    tmp_path,
    monkeypatch,
    kind,
):
    original_pr = kind == "original_pr_repair"
    customer_repair = kind == "customer_feedback_repair"
    value = manifest()
    if original_pr:
        from types import SimpleNamespace

        monkeypatch.syspath_prepend(str(ROOT / "FHD"))
        from scripts.dev import para_pr_repair

        value["base_sha"] = "a" * 40
        chosen = SimpleNamespace(number=42, branch="fix/original", old_sha=value["base_sha"])
        monkeypatch.setattr(publisher, "authorized_original_pr", lambda *a: chosen)

        def checked_diff(git, old, new):
            assert (old, new) == (value["base_sha"], value["commit_sha"])
            return 1

        monkeypatch.setattr(para_pr_repair, "_check_diff", checked_diff)
    data, digest = artifact(value)
    state = {**WORKSPACE, "publication_candidate": value, "finished": False}
    if kind:
        state["kind"] = kind
    if original_pr:
        state.update(kind="original_pr_repair", source_sha=value["base_sha"], pull_request=42)
    run = {
        "id": 123,
        "head_sha": "b" * 40,
        "head_branch": "main",
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "path": ".github/workflows/fhd-para-github-worker.yml",
        "display_title": f"para-workspace-{REQUEST}",
        "repository": {"full_name": "owner/repo"},
    }
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": "b" * 40,
        "GITHUB_REPOSITORY": "owner/repo",
        "PARA_GITHUB_REQUEST_ID": REQUEST,
        "GH_TOKEN": "publisher-test",
        "MODSTORE_PARA_DISPATCH_TOKEN": "management-test",
        "RUNNER_TEMP": str(tmp_path),
    }
    calls = []
    remote = {"exists": False}
    pull = []

    def git(*args, **kw):
        calls.append(args)
        if args[0] == "ls-remote":
            return f"{'c' * 40}\trefs/heads/{value['branch']}" if remote["exists"] else ""
        if args[0] == "push":
            remote["exists"] = True
            return ""
        pytest.fail(f"unexpected Git write: {args}")

    monkeypatch.setattr(
        publisher,
        "import_candidate",
        lambda *a, **kw: (git, "https://github.com/owner/repo.git"),
    )

    def command(args, **kw):
        calls.append(args)
        if args[0] == "node":
            pull.append(
                {
                    "number": 42,
                    "url": "https://github.com/owner/repo/pull/42",
                    "headRefOid": "c" * 40,
                    "headRefName": value["branch"],
                    "baseRefName": "main",
                    "body": "Refs #42",
                    "state": "OPEN",
                }
            )
            return json.dumps(pull[0])
        if args[:3] == ["gh", "pr", "list"]:
            return json.dumps(pull)
        if args[:3] == ["gh", "pr", "view"]:
            return json.dumps(pull[0])
        if args[:2] == ["gh", "api"]:
            if args[2].endswith("/zip"):
                return data
            if "/artifacts?" in args[2]:
                return json.dumps(
                    {
                        "total_count": 1,
                        "artifacts": [
                            {
                                "id": 456,
                                "name": f"para-candidate-{REQUEST}",
                                "digest": digest,
                                "size_in_bytes": len(data),
                                "workflow_run": {"id": 123},
                                "expired": False,
                            }
                        ],
                    }
                )
            return json.dumps(run)
        pytest.fail(f"unexpected command: {args}")

    def opener(*args, **kwargs):
        return io.BytesIO(json.dumps(state).encode())

    if original_pr or customer_repair:
        with pytest.raises(ValueError, match="requires_non_exportable_model_credentials"):
            publisher.publish(env, command=command, opener=opener)
        assert not any(c[0] in {"push", "node"} for c in calls)
        # Already-published results can still be read back without another write.
        remote["exists"] = True
    if customer_repair:
        with pytest.raises(
            ValueError, match="customer_feedback_requires_non_exportable_model_credentials"
        ):
            publisher.publish(env, command=command, opener=opener)
        assert not any(c[0] in {"push", "node"} for c in calls)
        pull.append(
            {
                "number": 42,
                "url": "https://github.com/owner/repo/pull/42",
                "headRefOid": value["commit_sha"],
                "headRefName": value["branch"],
                "baseRefName": "main",
                "body": "Refs #42",
                "state": "OPEN",
            }
        )
    first = publisher.publish(env, command=command, opener=opener)
    second = publisher.publish(env, command=command, opener=opener)
    assert first == second and first["delivered"] is False
    assert first["status"] == (
        "awaiting_original_pr_update" if original_pr else "published_for_review"
    )
    assert first["pull_request_url"] == "https://github.com/owner/repo/pull/42"
    assert sum(c[0] == "push" for c in calls) == (0 if kind else 1)
    assert sum(c[0] == "node" for c in calls) == (0 if kind else 1)
    assert not any("--force" in c or "merge" in c for c in calls)
    with pytest.raises(ValueError, match="redirect_rejected"):
        publisher.NoRedirect().redirect_request(None, None, None, None, None, None)


def test_original_team_waits_for_publication_and_resume_then_verifies_once(incident, monkeypatch):
    from fastapi import HTTPException

    from modstore_server import customer_ticket_github as bridge
    from modstore_server import incident_team_completion as completion
    from modstore_server import incident_team_orchestrator as team
    from modstore_server import models, para_github_runner
    from tests.test_incident_team_continuation import _accepted, _claim, _terminal

    workspace = {
        **WORKSPACE,
        "issue_url": "https://github.com/owner/repo/issues/42",
        "public_title": "Improve product",
        "public_summary": "Approved tests",
    }
    with models.get_session_factory()() as db:
        event = db.get(models.IncidentEvent, incident)
        event.payload_json = json.dumps({"github_workspace": workspace})
        db.commit()
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_API_BASE", "https://para.example.test")
    monkeypatch.setenv("MODSTORE_GITHUB_REPOSITORY", "owner/repo")
    phases = {"published": False, "resumed": False}
    calls = []

    def execute(employee, prompt, runtime, **kw):
        role = runtime["role"]
        calls.append(role)
        if role == "verify":
            assert phases["published"] and phases["resumed"]
            assert runtime["branch"] == "c" * 40
        accepted = _accepted(role)
        accepted["result"]["outputs"][0].update(
            executor="github_actions", planned_devices=["cloud"]
        )
        return accepted

    monkeypatch.setattr(team, "_execute_employee_task_with_timeout", execute)
    monkeypatch.setattr(para_github_runner, "resume_worker_ready", lambda ws: phases["resumed"])

    def github(method, path):
        if "/git/ref/" in path:
            if not phases["published"]:
                raise HTTPException(502, "not yet published")
            return {"object": {"sha": "c" * 40}}
        if "/actions/runs/" in path:
            return {"head_sha": "b" * 40, "run_attempt": 1}
        return [
            {
                "head": {"sha": "c" * 40, "ref": "devfleet/codex/sub-test"},
                "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
                "body": "Refs #42",
            }
        ]

    monkeypatch.setattr(bridge, "github", github)
    team.dispatch_incident_team(incident)
    completion.reconcile_pending_teams(event_id=incident, fetcher=lambda base, tid: _terminal(tid))
    assert calls == ["scout", "fix"]
    fix_attempt = _claim(incident)["team"][1]["attempt_id"]
    evidence = {
        **receipt(),
        "task_id": "p-fix",
        "subtask_id": "s-fix",
        "attempt_id": fix_attempt,
    }
    fixed = {
        **task(),
        "id": "p-fix",
        "subTasks": [
            {
                "id": "s-fix",
                "status": "completed",
                "branch_name": evidence["branch"],
                "logs": [{"content": json.dumps(evidence)}],
            }
        ],
    }

    def fetch(base, tid):
        return fixed if tid == "p-fix" else _terminal(tid)

    completion.reconcile_pending_teams(event_id=incident, fetcher=fetch)
    assert calls == ["scout", "fix"] and _claim(incident)["ok"] is False
    phases["published"] = True
    completion.reconcile_pending_teams(event_id=incident, fetcher=fetch)
    assert calls == [
        "scout",
        "fix",
    ]  # Publisher job itself cannot receive verification work.
    assert _claim(incident)["team"][1]["status"] == "pending"
    phases["resumed"] = True
    completion.reconcile_pending_teams(event_id=incident, fetcher=fetch)
    assert calls == ["scout", "fix", "verify"]
    completion.reconcile_pending_teams(event_id=incident, fetcher=fetch)
    completion.reconcile_pending_teams(event_id=incident, fetcher=fetch)
    assert calls == ["scout", "fix", "verify"] and _claim(incident)["ok"] is True
    assert _claim(incident)["team"][2]["verified_fix_attempt_id"] == fix_attempt
