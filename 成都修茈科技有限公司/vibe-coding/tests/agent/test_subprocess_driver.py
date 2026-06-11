"""Cross-platform tests for :class:`SubprocessSandboxDriver`."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from vibe_coding.agent.sandbox import (
    SandboxJob,
    SandboxPolicy,
    SubprocessSandboxDriver,
    create_default_driver,
)


@pytest.fixture(scope="module")
def driver() -> SubprocessSandboxDriver:
    return SubprocessSandboxDriver()


def test_function_success(driver: SubprocessSandboxDriver) -> None:
    res = driver.execute(
        SandboxJob(
            kind="function",
            source_code="def run(value):\n    return {'echo': str(value)}\n",
            function_name="run",
            input_data={"value": "ping"},
        )
    )
    assert res.success
    assert res.driver == "subprocess"
    assert res.output == {"echo": "ping"}


def test_function_timeout(driver: SubprocessSandboxDriver) -> None:
    code = textwrap.dedent(
        """\
        def run():
            n = 0
            while True:
                n += 1
            return {'n': n}
        """
    )
    res = driver.execute(
        SandboxJob(kind="function", source_code=code, function_name="run", input_data={}),
        policy=SandboxPolicy(timeout_s=0.5),
    )
    assert not res.success
    assert res.error_type == "TimeoutError"


def test_function_blocks_unsafe_imports(driver: SubprocessSandboxDriver) -> None:
    code = "def run():\n    import os\n    return {}\n"
    res = driver.execute(
        SandboxJob(kind="function", source_code=code, function_name="run", input_data={})
    )
    assert not res.success
    assert "not allowed" in res.error_message


def test_function_blocks_forbidden_builtin(driver: SubprocessSandboxDriver) -> None:
    code = "def run():\n    eval('1+1')\n    return {}\n"
    res = driver.execute(
        SandboxJob(kind="function", source_code=code, function_name="run", input_data={})
    )
    assert not res.success


def test_function_output_size_capped(driver: SubprocessSandboxDriver) -> None:
    code = "def run():\n    return {'big': 'x' * 99999}\n"
    res = driver.execute(
        SandboxJob(kind="function", source_code=code, function_name="run", input_data={}),
        policy=SandboxPolicy(max_output_size=200),
    )
    assert not res.success


def test_command_runs_in_workspace(driver: SubprocessSandboxDriver, tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    res = driver.execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=[sys.executable, "-c", "import os; print(os.listdir('.'))"],
        ),
        policy=SandboxPolicy(timeout_s=5),
    )
    assert res.success, res.stderr
    assert "hello.txt" in res.stdout


def test_command_timeout(driver: SubprocessSandboxDriver, tmp_path: Path) -> None:
    res = driver.execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=[sys.executable, "-c", "import time; time.sleep(10)"],
        ),
        policy=SandboxPolicy(timeout_s=0.5),
    )
    assert not res.success
    assert res.error_type == "TimeoutError"


def test_command_requires_workspace(driver: SubprocessSandboxDriver) -> None:
    res = driver.execute(
        SandboxJob(kind="command", command=[sys.executable, "-c", "print(1)"])
    )
    assert not res.success
    assert "workspace_dir" in res.error_message


def test_unknown_kind(driver: SubprocessSandboxDriver) -> None:
    job = SandboxJob(kind="function")  # type: ignore[arg-type]
    job.kind = "weird"  # type: ignore[assignment]
    res = driver.execute(job)
    assert not res.success
    assert res.error_type == "ValueError"


def test_default_driver_subprocess_when_forced() -> None:
    drv = create_default_driver(prefer="subprocess")
    assert drv.name == "subprocess"


def test_function_default_policy(driver: SubprocessSandboxDriver) -> None:
    """Calling without an explicit policy uses the dataclass defaults."""
    res = driver.execute(
        SandboxJob(
            kind="function",
            source_code="def run(): return {'ok': True}\n",
            function_name="run",
            input_data={},
        )
    )
    assert res.success
    assert res.duration_ms >= 0.0
