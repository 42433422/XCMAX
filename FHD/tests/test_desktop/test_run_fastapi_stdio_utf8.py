"""Windows bootstrap keeps UTF-8 pipes and supports windowed Python's absent streams."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from XCAGI import run_fastapi


class _FakeStream:
    def __init__(self, name: str, calls: list[tuple[str, str]]):
        self.name = name
        self._calls = calls

    def reconfigure(self, encoding: str = "") -> None:
        self._calls.append((self.name, encoding))


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_force_stdio_utf8_preserves_existing_streams(monkeypatch, platform):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(run_fastapi.sys, "platform", platform)
    monkeypatch.setattr(run_fastapi.sys, "stdout", _FakeStream("stdout", calls))
    monkeypatch.setattr(run_fastapi.sys, "stderr", _FakeStream("stderr", calls))

    run_fastapi._force_stdio_utf8()

    assert calls == ([("stdout", "utf-8"), ("stderr", "utf-8")] if platform == "win32" else [])


def test_force_stdio_utf8_survives_streams_without_reconfigure(monkeypatch, tmp_path):
    class Plain:
        pass

    monkeypatch.setattr(run_fastapi.sys, "platform", "win32")
    monkeypatch.setattr(run_fastapi.sys, "stdout", Plain())
    monkeypatch.setattr(run_fastapi.sys, "stderr", Plain())

    run_fastapi._force_stdio_utf8(str(tmp_path))


@pytest.mark.parametrize("missing", ["stdout", "stderr", "both"])
@pytest.mark.parametrize("pipe_present", [True, False])
def test_windowed_bootstrap_real_uvicorn_logging_and_traceback(tmp_path, missing, pipe_present):
    code = """
import logging, os, sys, uvicorn
from XCAGI import run_fastapi
sys.platform = 'win32'
sys.frozen = True
if sys.argv[2] in ('stdout', 'both'): sys.stdout = None
if sys.argv[2] in ('stderr', 'both'): sys.stderr = None
if sys.argv[3] == 'False':
 if sys.stdout is None: os.close(1)
 if sys.stderr is None: os.close(2)
run_fastapi._force_stdio_utf8(sys.argv[1])
run_fastapi._bootstrap_stage('synthetic-phase')
uvicorn.Config('unused:app').configure_logging()
logging.getLogger('uvicorn.error').warning('bootstrap 中文日志')
print('XCAGI_MIGRATION_BACKUP=synthetic-backup.db', flush=True)
raise RuntimeError('synthetic initialization failure')
"""
    root = tmp_path / "user data"
    env = {**os.environ, "XCAGI_DATA_DIR": str(tmp_path / "wrong-env")}
    env["PYTHONPATH"] = str(Path(run_fastapi.__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-c", code, str(root), missing, str(pipe_present)],
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=20,
    )
    log_file = root / "logs" / "backend-bootstrap.log"
    log = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    output = log + result.stdout + result.stderr
    assert result.returncode == 1 and "Unable to configure formatter" not in output
    assert "bootstrap 中文日志" in output and "synthetic initialization failure" in output
    assert "XCAGI_MIGRATION_BACKUP=synthetic-backup.db" in output
    assert "synthetic-phase" in output
    assert bool(log) == (not pipe_present)
    if pipe_present:
        assert "XCAGI_MIGRATION_BACKUP=" in result.stdout
    assert not (tmp_path / "wrong-env").exists()
