"""工具子进程沙箱：环境清洗与 POSIX 资源限制。"""

import os
from unittest.mock import Mock

import pytest

from app.application.agent_orchestrator import tool_process

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX resource limits only")


def test_scrubbed_env_drops_sensitive_keys_and_keeps_baseline():
    environ = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/tester",
        "TMPDIR": "/tmp",
        "XCAGI_TOOL_MEMORY_MB": "512",
        "XCAGI_API_KEY": "internal-config",
        "OPENAI_API_KEY": "sk-live",
        "github_token": "ghp_x",
        "DB_PASSWORD": "pw",
        "APP_SECRET": "s",
        "TLS_PRIVATE_KEY": "k",
        "SESSION_COOKIE": "c",
    }

    assert tool_process._scrubbed_env(environ) == {
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/tester",
        "TMPDIR": "/tmp",
        "XCAGI_TOOL_MEMORY_MB": "512",
        "XCAGI_API_KEY": "internal-config",
    }


def test_scrubbed_env_reads_inherited_environ(monkeypatch):
    monkeypatch.setenv("XCAGI_TOOL_CPU_SECONDS", "30")
    monkeypatch.setenv("SERVICE_ACCESS_TOKEN", "t")
    monkeypatch.setenv("HOME", "/root")

    scrubbed = tool_process._scrubbed_env()

    assert "SERVICE_ACCESS_TOKEN" not in scrubbed
    assert scrubbed["XCAGI_TOOL_CPU_SECONDS"] == "30"
    assert scrubbed["HOME"] == "/root"


def _record_limits(monkeypatch):
    import resource

    calls = {}

    def fake_setrlimit(which, limits):
        calls[which] = limits

    monkeypatch.setattr(resource, "getrlimit", lambda _which: (resource.RLIM_INFINITY,) * 2)
    monkeypatch.setattr(resource, "setrlimit", fake_setrlimit)
    return resource, calls


@posix_only
def test_resource_limits_use_defaults(monkeypatch):
    for name in ("XCAGI_TOOL_CPU_SECONDS", "XCAGI_TOOL_MEMORY_MB", "XCAGI_TOOL_MAX_FILES"):
        monkeypatch.delenv(name, raising=False)
    resource, calls = _record_limits(monkeypatch)

    tool_process._apply_resource_limits()

    assert calls[resource.RLIMIT_CPU][0] == 60
    assert calls[resource.RLIMIT_AS][0] == 2048 * 1024 * 1024
    assert calls[resource.RLIMIT_NOFILE][0] == 256


@posix_only
def test_resource_limits_follow_env_overrides(monkeypatch):
    monkeypatch.setenv("XCAGI_TOOL_CPU_SECONDS", "15")
    monkeypatch.setenv("XCAGI_TOOL_MEMORY_MB", "256")
    monkeypatch.setenv("XCAGI_TOOL_MAX_FILES", "64")
    resource, calls = _record_limits(monkeypatch)

    tool_process._apply_resource_limits()

    assert calls[resource.RLIMIT_CPU][0] == 15
    assert calls[resource.RLIMIT_AS][0] == 256 * 1024 * 1024
    assert calls[resource.RLIMIT_NOFILE][0] == 64


@posix_only
def test_invalid_env_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("XCAGI_TOOL_MEMORY_MB", "not-a-number")
    monkeypatch.setenv("XCAGI_TOOL_MAX_FILES", "-8")
    monkeypatch.delenv("XCAGI_TOOL_SANDBOX", raising=False)
    resource, calls = _record_limits(monkeypatch)

    tool_process._apply_resource_limits()

    assert calls[resource.RLIMIT_AS][0] == 2048 * 1024 * 1024
    assert calls[resource.RLIMIT_NOFILE][0] == 256


@posix_only
def test_resource_limit_failures_are_not_fatal(monkeypatch):
    import resource

    monkeypatch.setattr(resource, "getrlimit", lambda _which: (resource.RLIM_INFINITY,) * 2)
    monkeypatch.setattr(resource, "setrlimit", Mock(side_effect=OSError("denied")))

    tool_process._apply_resource_limits()


@posix_only
def test_sandbox_can_be_disabled(monkeypatch):
    monkeypatch.setenv("XCAGI_TOOL_SANDBOX", "0")
    import resource

    calls = []
    monkeypatch.setattr(resource, "getrlimit", lambda _which: (resource.RLIM_INFINITY,) * 2)
    monkeypatch.setattr(resource, "setrlimit", lambda *a: calls.append(a))

    tool_process._apply_resource_limits()

    assert calls == []


def test_env_scrub_is_opt_in(monkeypatch):
    monkeypatch.delenv("XCAGI_TOOL_SANDBOX_SCRUB_ENV", raising=False)
    assert tool_process._env_scrub_enabled() is False
    monkeypatch.setenv("XCAGI_TOOL_SANDBOX_SCRUB_ENV", "1")
    assert tool_process._env_scrub_enabled() is True
