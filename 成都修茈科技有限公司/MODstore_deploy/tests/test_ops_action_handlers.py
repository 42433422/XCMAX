"""ops_action_handlers：白名单、审批 dry-run、只读路径。"""

from __future__ import annotations

import subprocess

import pytest

from modstore_server.integrations import ops_action_handlers as ops


def test_unknown_command_writes_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict] = []

    def _rec(**kw: object) -> None:
        recorded.append(dict(kw))  # type: ignore[arg-type]

    monkeypatch.setattr(ops, "_write_audit", _rec)
    out = ops.dispatch_ops_handler(
        "shell_exec",
        {"shell_exec": {"command_id": "not-in-registry"}},
        {},
        "brief",
        "nginx-config-engineer",
        1,
    )
    assert out["ok"] is False
    assert recorded and recorded[0].get("exit_code") == -1


def test_employee_not_allowed_for_command(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict] = []

    monkeypatch.setattr(ops, "_write_audit", lambda **kw: recorded.append(dict(kw)))  # type: ignore[misc]

    out = ops.dispatch_ops_handler(
        "shell_exec",
        {"shell_exec": {"command_id": "nginx-syntax-check"}},
        {},
        "x",
        "log-monitor-incident",
        1,
    )
    assert out["ok"] is False
    assert "not allowed" in (out.get("error") or "").lower()
    assert recorded and recorded[0].get("exit_code") == -1


def test_nginx_reload_requires_approval_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict] = []

    monkeypatch.setattr(ops, "_write_audit", lambda **kw: recorded.append(dict(kw)))  # type: ignore[misc]

    out = ops.dispatch_ops_handler(
        "shell_exec",
        {"shell_exec": {"command_id": "nginx-reload"}},
        {},
        "reload",
        "nginx-config-engineer",
        1,
    )
    assert out.get("dry_run") is True
    assert out.get("approval_required") is True
    assert recorded and recorded[0].get("approval_required") is True


def test_read_pytest_lastfailed_runs(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(root))
    cache = root / "MODstore_deploy" / ".pytest_cache" / "v" / "cache"
    cache.mkdir(parents=True)
    (cache / "lastfailed").write_text("tests/test_x.py::test_foo", encoding="utf-8")

    recorded: list[dict] = []
    monkeypatch.setattr(ops, "_write_audit", lambda **kw: recorded.append(dict(kw)))  # type: ignore[misc]

    out = ops.dispatch_ops_handler(
        "shell_exec",
        {"shell_exec": {"command_id": "read-pytest-lastfailed"}},
        {},
        "check",
        "log-monitor-incident",
        1,
    )
    assert out.get("ok") is True
    assert "test_x" in (out.get("stdout") or "")
    assert recorded and recorded[0].get("exit_code") == 0


def test_ops_path_allowed() -> None:
    assert ops.ops_path_allowed("nginx-xiu-ci.conf")
    assert ops.ops_path_allowed("MODstore_deploy/.pytest_cache/v/cache/lastfailed")
    assert not ops.ops_path_allowed("../etc/passwd")
    assert not ops.ops_path_allowed("evil.py")


def test_subprocess_timeout_exit(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))

    def _timeout(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(subprocess, "run", _timeout)

    recorded: list[dict] = []
    monkeypatch.setattr(ops, "_write_audit", lambda **kw: recorded.append(dict(kw)))  # type: ignore[misc]

    out = ops.dispatch_ops_handler(
        "shell_exec",
        {"shell_exec": {"command_id": "grep-cursor-logs", "timeout": 2}},
        {},
        "g",
        "log-monitor-incident",
        1,
    )
    assert out.get("exit_code") == -1
    assert recorded
