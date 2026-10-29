"""Actual app factory/auth/worker/readback/restart on isolated pre-enrolled files."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DRIVER = Path(__file__).parents[1] / "fixtures/catalog_factory_runtime.py"


def _env(root, fast_start="1"):
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(root),
        "TMPDIR": str(root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "SECRET_KEY": "synthetic-catalog-startup-key-at-least-32-bytes",
        "DATABASE_URL": f"sqlite:///{root / 'host.sqlite'}",
        "VECTOR_DB_URL": f"sqlite:///{root / 'host.sqlite'}",
        "XCAGI_DATA_DIR": str(root / "control"),
        "WORKSPACE_ROOT": str(root / "workspaces"),
        "XCAGI_MODS_ROOT": str(root / "mods"),
        "XCAGI_OWNED_SOURCE_PROFILE": "guarded-host-v1",
        "XCAGI_DESKTOP_MODE": "0",
        "XCAGI_PRODUCT_SKU": "enterprise",
        "XCAGI_DESKTOP_FAST_START": fast_start,
        "XCAGI_DEBUG": "0",
        "XCAGI_AGENT_RUN_REQUIRE_DURABLE": "1",
        "XCAGI_AGENT_TASK_WORKERS": "1",
        "FHD_ENV": "test",
        "XCAGI_NEURO_INTENT": "0",
        "XCAGI_EMPLOYEE_SCHEDULER": "0",
        "CACHE_REDIS_URL": "",
        "CELERY_BROKER_URL": "memory://",
        "CELERY_RESULT_BACKEND": "cache+memory://",
        "DD_TRACE_ENABLED": "false",
        "OTEL_SDK_DISABLED": "true",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "maintenance.auto",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "gc.auto",
        "GIT_CONFIG_VALUE_1": "0",
    }


def _run(root, mode, env):
    result = subprocess.run(
        [sys.executable, "-B", str(DRIVER), mode, str(root)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (root / f"{mode}.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, f"{mode}: {result.stdout[-1000:]}\n{result.stderr[-7000:]}"


@pytest.mark.parametrize("fast_start", ["0", "1"])
def test_real_factory_auth_dispatch_save_readback_and_fresh_process_restart(tmp_path, fast_start):
    env = _env(tmp_path, fast_start)
    _run(tmp_path, "seed", env)
    _run(tmp_path, "save", env)
    _run(tmp_path, "restart", env)
    saved = json.loads((tmp_path / "save-proof.json").read_text())
    restarted = json.loads((tmp_path / "restart-proof.json").read_text())
    assert restarted == saved, "restart must return the immutable original receipt"


def test_real_reader_contention_waits_before_fresh_ledger_claim(tmp_path):
    env = _env(tmp_path)
    _run(tmp_path, "seed", env)
    _run(tmp_path, "contention", env)
    assert (tmp_path / "worker-source-lock-attempt.txt").read_text() == "observed\n"
    _run(tmp_path, "restart", env)


@pytest.mark.parametrize("damage", ["missing_host", "missing_marker", "invalid_profile"])
def test_invalid_guarded_factory_does_not_create_repair_or_seed_storage(tmp_path, damage):
    env = _env(tmp_path)
    if damage != "missing_host":
        _run(tmp_path, "seed", env)
    if damage == "missing_marker":
        (tmp_path / "control/config/owned-source-protocol.json").unlink()
    elif damage == "invalid_profile":
        env["XCAGI_OWNED_SOURCE_PROFILE"] = "untrusted-profile"
    before = {
        str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tmp_path.rglob("*")
        if p.is_file() and p.suffix != ".log"
    }
    _run(tmp_path, "reject", env)
    after = {
        str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tmp_path.rglob("*")
        if p.is_file() and p.suffix != ".log"
    }
    assert after == before, "rejected startup changed pre-existing synthetic authority/storage"
