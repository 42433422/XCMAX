"""Actual Para task execution emits a metered edit and the original Git bundle."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi import Request

from modstore_server import strategic_portfolio as p
from tests import test_strategic_remote_bridge as report_tests
from tests import test_strategic_workspace_bridge as work_tests
from tests.test_strategic_remote_opencode import provider

database = work_tests.database
configured = work_tests.configured
workspace = work_tests.workspace


@pytest.fixture
def wire_workspace(request, monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=source, text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.test")
    (source / "docs").mkdir()
    (source / "docs/delivery.txt").write_text("ordinary export before repair\n")
    git("add", "docs/delivery.txt")
    git("commit", "-m", "ordinary fixture")
    sha = git("rev-parse", "HEAD")
    monkeypatch.setattr(work_tests, "SOURCE", sha)
    monkeypatch.setattr(report_tests, "SOURCE", sha)
    state = request.getfixturevalue("workspace")
    state.source = source
    state.source_sha = sha
    return state


@pytest.mark.skipif(
    not os.environ.get("PARA_TEST_OPENCODE_BINARY"),
    reason="requires the pinned OpenCode 1.19.6 and ws lock",
)
@pytest.mark.parametrize("executor_exists", [True, False], ids=["real_sdk", "missing_executor"])
def test_existing_actions_real_para_task_opencode_sdk_sql_and_candidate(
    wire_workspace, monkeypatch, tmp_path, executor_exists
):
    state = wire_workspace
    work_tests.attach(state)
    assert state.collect()["event_id"]
    identity = work_tests.task(state)
    seen = provider(
        monkeypatch,
        state,
        tool_name="write",
        tool_arguments={"filePath": "docs/delivery.txt", "content": "ordinary export repaired\n"},
        output_text="The approved report export was repaired.",
    )
    monkeypatch.setattr(
        "modstore_server.maintenance_loop.para_client._fetch_para_task_state",
        lambda _base, key: state.tasks[key],
    )
    reports = []

    @state.app.post("/api/devices/me/task-report")
    async def task_report(request: Request):
        assert request.headers["authorization"] == "Bearer fixture-device-token"
        value = await request.json()
        reports.append(value)
        task = state.tasks[value["task_id"]]
        task["status"] = value["status"]
        task["subTasks"][0].update(status=value["status"], logs=[{"content": value["content"]}])
        return {"ok": True}

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    server = uvicorn.Server(uvicorn.Config(state.app, log_level="error", lifespan="off", ws="none"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    binary = Path(os.environ["PARA_TEST_OPENCODE_BINARY"])
    assert (
        binary.parents[2] / "ws/package.json"
    ).exists(), "install the existing GitHub worker lock"
    evidence, candidate = tmp_path / "evidence", tmp_path / "candidate"
    child_env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "42",
        "GITHUB_SHA": state.source_sha,
        "GITHUB_REPOSITORY": work_tests.REPO,
        "PARA_GITHUB_STAGE": "execute",
        "PARA_GITHUB_REQUEST_ID": state.request_id,
        "PARA_GITHUB_EVIDENCE_DIR": str(evidence),
        "PARA_GITHUB_CANDIDATE_DIR": str(candidate),
        "MODSTORE_PARA_DISPATCH_TOKEN": work_tests.TOKEN,
        "DEVFLEET_FORCE_OPENCODE": "1",
        "PARA_PLATFORM_POOL": "1",
        "DEVFLEET_DEVICE_TOKEN": "fixture-device-token",
        "DEVFLEET_API_URL": "https://para.example.test",
        "DEVFLEET_WORKSPACE_ROOT": str(tmp_path / "workspaces"),
        "DEVFLEET_OPENCODE_AGENT": str(
            binary if executor_exists else binary.with_name("missing-opencode-executor")
        ),
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "NODE_PATH": str(binary.parents[2]),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{state.source}.insteadOf",
        "GIT_CONFIG_VALUE_0": f"https://github.com/{work_tests.REPO}.git",
    }
    (tmp_path / "home").mkdir()
    task = {
        key: identity[key]
        for key in (
            "task_id",
            "subtask_id",
            "title",
            "description",
            "repo_url",
            "base_branch",
            "work_branch",
            "auto_merge",
        )
    }
    config = tmp_path / "controller.json"
    config.write_text(json.dumps({"env": child_env, "task": task}))
    root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            [
                "node",
                str(Path(__file__).parent / "fixtures/strategic_workspace_wire.mjs"),
                str(config),
            ],
            env={
                "PATH": os.environ["PATH"],
                "WORKSPACE_LOOPBACK": f"http://127.0.0.1:{sock.getsockname()[1]}",
                "WORKSPACE_RUNTIME_TOOLS": str(root / "FHD/scripts/autonomy/runtime_tools"),
                "NODE_PATH": str(binary.parents[2]),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        if executor_exists:
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            assert result.returncode != 0
            assert "requested_executor_unavailable" in result.stderr
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
    if not executor_exists:
        assert not seen
        assert reports[-1]["status"] == "failed"
        assert not (candidate / "manifest.json").exists()
        assert not p.portfolio_status(state.decision_id)["tasks"]["a"]["calls"]
        workspace_file = tmp_path / "workspaces/task-fix-sub-fix/docs/delivery.txt"
        assert workspace_file.read_text() == "ordinary export before repair\n"
        return
    assert len(seen) == 2
    assert reports[-1]["status"] == "completed"
    manifest = json.loads((candidate / "manifest.json").read_text())
    assert (
        manifest["base_sha"] == state.source_sha and manifest["publication"] == "artifact_pending"
    )
    saved = p.portfolio_status(state.decision_id)["tasks"]["a"]
    assert saved["status"] == "running"
    calls = list(saved["calls"].values())
    assert len({call["caller_binding"]["grant_id"] for call in calls}) == 1
    assert all(call["status"] == "settled" and call["actual_tokens"] == 128 for call in calls)
    proof = tmp_path / "readback"
    subprocess.run(["git", "clone", str(state.source), str(proof)], check=True, capture_output=True)
    subprocess.run(
        ["git", "fetch", str(candidate / "candidate.bundle"), manifest["branch"]],
        cwd=proof,
        check=True,
        capture_output=True,
    )
    actual = subprocess.check_output(
        ["git", "show", manifest["commit_sha"] + ":docs/delivery.txt"], cwd=proof, text=True
    )
    assert actual == "ordinary export repaired\n"
    assert json.loads((evidence / "execution.json").read_text())["finished"] is False
