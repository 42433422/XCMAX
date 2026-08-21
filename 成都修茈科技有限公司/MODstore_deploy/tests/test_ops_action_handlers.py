"""ops_action_handlers：白名单、审批 dry-run、只读路径。"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

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


def test_nginx_reload_requires_approval_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_ssh_rejects_unknown_host_keys(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_dir = tmp_path / "ssh_keys"
    key_dir.mkdir()
    key_file = key_dir / "ops-key"
    key_file.write_text("test", encoding="utf-8")
    monkeypatch.setattr(ops, "_ssh_keys_dir", lambda: key_dir)

    calls: list[str] = []

    class FakeStream:
        channel = SimpleNamespace(recv_exit_status=lambda: 0)

        def read(self) -> bytes:
            return b""

    class FakeClient:
        def load_system_host_keys(self) -> None:
            calls.append("load")

        def set_missing_host_key_policy(self, policy: object) -> None:
            calls.append(type(policy).__name__)

        def connect(self, *args: object, **kwargs: object) -> None:
            calls.append("connect")

        def exec_command(self, *args: object, **kwargs: object):
            return None, FakeStream(), FakeStream()

        def close(self) -> None:
            calls.append("close")

    class RejectPolicy:
        pass

    fake_paramiko = SimpleNamespace(SSHClient=FakeClient, RejectPolicy=RejectPolicy)
    monkeypatch.setitem(sys.modules, "paramiko", fake_paramiko)

    result = ops._run_ssh(
        {"hostname": "example.com", "user": "ops", "key_path": str(key_file)},
        ["true"],
        timeout=5,
        capture_max=100,
    )

    assert result == (0, "", "")
    assert calls[:3] == ["load", "RejectPolicy", "connect"]
