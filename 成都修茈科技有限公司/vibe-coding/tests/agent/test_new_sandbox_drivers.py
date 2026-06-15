"""Tests for :class:`WebContainerSandboxDriver`, :class:`CloudSandboxDriver`,
:class:`MockSandboxDriver` and :func:`create_cloud_driver`.

The first two are HTTP-bridge drivers, so the tests stub
``urllib.request.urlopen`` to avoid hitting the network. The mock driver
is fully in-memory.
"""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from vibe_coding.agent.sandbox import (
    CloudSandboxDriver,
    E2BBackend,
    HTTPCloudBackend,
    MockSandboxDriver,
    SandboxJob,
    SandboxPolicy,
    SandboxResult,
    WebContainerBridge,
    WebContainerSandboxDriver,
    create_cloud_driver,
)


# ----------------------------------------------------- helpers


class _FakeResponse:
    def __init__(self, body: str | bytes, status: int = 200) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


@contextmanager
def _patched_urlopen(handler):
    captured: list[Any] = []

    def fake_urlopen(req, timeout=None, context=None):  # noqa: ARG001
        captured.append(req)
        return handler(req)

    with patch("urllib.request.urlopen", fake_urlopen):
        yield captured


# ----------------------------------------------------- mock driver


def test_mock_driver_records_jobs_and_returns_scripted_response() -> None:
    drv = MockSandboxDriver.passing(stdout="ok", output={"x": 1})
    res = drv.execute(SandboxJob(kind="function", function_name="run"))
    assert res.success is True
    assert res.stdout == "ok"
    assert res.output == {"x": 1}
    assert len(drv.calls) == 1
    drv.assert_called_with_function("run")


def test_mock_driver_handler_overrides_static_response() -> None:
    seen: list[str] = []

    def handler(job: SandboxJob, policy: SandboxPolicy) -> SandboxResult:
        seen.append(job.function_name)
        return SandboxResult(success=False, driver="x", error_message="nope")

    drv = MockSandboxDriver(handler=handler)
    res = drv.execute(SandboxJob(kind="function", function_name="boom"))
    assert res.success is False
    assert res.error_message == "nope"
    assert seen == ["boom"]


def test_mock_driver_assert_command_fails_loud() -> None:
    drv = MockSandboxDriver.passing()
    drv.execute(SandboxJob(kind="command", command=["ruff", "check"], workspace_dir="/tmp"))
    drv.assert_called_with_command("ruff")
    with pytest.raises(AssertionError):
        drv.assert_called_with_command("mypy")


def test_mock_failing_factory() -> None:
    drv = MockSandboxDriver.failing(stderr="oh no", exit_code=2)
    res = drv.execute(SandboxJob(kind="function"))
    assert res.success is False
    assert res.exit_code == 2
    assert res.error_message == "oh no"


# ----------------------------------------------------- webcontainer


def test_webcontainer_unavailable_when_health_fails() -> None:
    bridge = WebContainerBridge(base_url="http://127.0.0.1:9/api/sandbox")
    drv = WebContainerSandboxDriver(bridge)

    def handler(req):  # noqa: ARG001
        raise OSError("connection refused")

    with _patched_urlopen(handler):
        assert drv.is_available() is False
    res = drv.execute(SandboxJob(kind="command", command=["x"], workspace_dir="/tmp"))
    assert res.success is False
    assert res.error_type == "DriverUnavailable"


def test_webcontainer_executes_command_through_bridge() -> None:
    bridge = WebContainerBridge(base_url="http://127.0.0.1:8765/api/sandbox")
    drv = WebContainerSandboxDriver(bridge)

    state = {"calls": 0}

    def handler(req):
        state["calls"] += 1
        if state["calls"] == 1:
            assert req.full_url.endswith("/health")
            return _FakeResponse("ok")
        assert req.full_url.endswith("/exec")
        body = json.loads(req.data.decode("utf-8"))
        assert body["kind"] == "command"
        assert body["command"] == ["vitest", "run"]
        return _FakeResponse(
            json.dumps(
                {
                    "success": True,
                    "stdout": "ok\n",
                    "stderr": "",
                    "exit_code": 0,
                    "duration_ms": 12.5,
                }
            )
        )

    with _patched_urlopen(handler):
        res = drv.execute(
            SandboxJob(
                kind="command",
                command=["vitest", "run"],
                workspace_dir="/tmp",
            ),
            SandboxPolicy(timeout_s=10),
        )
    assert res.success is True
    assert res.stdout.startswith("ok")


# ----------------------------------------------------- cloud http backend


def test_http_cloud_backend_proxies_command(tmp_path) -> None:  # noqa: ARG001
    backend = HTTPCloudBackend(base_url="https://exec.example.com")

    def handler(req):
        if req.full_url.endswith("/health"):
            return _FakeResponse("ok")
        body = json.loads(req.data.decode("utf-8"))
        assert body["kind"] == "command"
        return _FakeResponse(
            json.dumps(
                {
                    "success": True,
                    "stdout": "hi",
                    "exit_code": 0,
                }
            )
        )

    drv = CloudSandboxDriver(backend)
    with _patched_urlopen(handler):
        res = drv.execute(
            SandboxJob(kind="command", command=["echo", "hi"], workspace_dir="/tmp"),
            SandboxPolicy(timeout_s=5),
        )
    assert res.success is True
    assert res.stdout == "hi"
    assert res.driver.startswith("cloud:")


def test_http_cloud_backend_function_round_trip() -> None:
    backend = HTTPCloudBackend(base_url="https://exec.example.com")

    def handler(req):
        if req.full_url.endswith("/health"):
            return _FakeResponse("ok")
        body = json.loads(req.data.decode("utf-8"))
        assert body["kind"] == "function"
        assert body["function_name"] == "run"
        return _FakeResponse(
            json.dumps({"success": True, "output": {"x": body["input_data"]["x"] * 2}})
        )

    drv = CloudSandboxDriver(backend)
    with _patched_urlopen(handler):
        res = drv.execute(
            SandboxJob(
                kind="function",
                source_code="def run(x): return {'x': x*2}",
                function_name="run",
                input_data={"x": 21},
            )
        )
    assert res.success is True
    assert res.output == {"x": 42}


def test_cloud_driver_failed_command_propagates() -> None:
    backend = HTTPCloudBackend(base_url="https://exec.example.com")

    def handler(req):
        if req.full_url.endswith("/health"):
            return _FakeResponse("ok")
        return _FakeResponse(
            json.dumps(
                {"success": False, "stderr": "no such command", "exit_code": 127}
            )
        )

    drv = CloudSandboxDriver(backend)
    with _patched_urlopen(handler):
        res = drv.execute(
            SandboxJob(kind="command", command=["nope"], workspace_dir="/tmp")
        )
    assert res.success is False
    assert res.exit_code == 127


# ----------------------------------------------------- factory


def test_create_cloud_driver_resolves_e2b_when_key_set(monkeypatch) -> None:
    monkeypatch.setenv("E2B_API_KEY", "key")
    drv = create_cloud_driver(backend="e2b")
    assert isinstance(drv, CloudSandboxDriver)
    assert isinstance(drv.backend, E2BBackend)


def test_create_cloud_driver_falls_back_to_http() -> None:
    drv = create_cloud_driver(backend="http", base_url="https://exec.example.com")
    assert isinstance(drv, CloudSandboxDriver)
    assert isinstance(drv.backend, HTTPCloudBackend)


def test_create_cloud_driver_raises_without_choice(monkeypatch) -> None:
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_cloud_driver(backend="auto")
