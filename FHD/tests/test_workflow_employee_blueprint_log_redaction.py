from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI

REPO_ROOT = Path(__file__).resolve().parents[2]
BLUEPRINTS = (
    "xcagi-workflow-employee-label-print",
    "xcagi-workflow-employee-real-phone",
    "xcagi-workflow-employee-receipt-confirm",
    "xcagi-workflow-employee-shipment-mgmt",
)


def _load_blueprint(mod_name: str):
    path = (
        REPO_ROOT / "成都修茈科技有限公司" / "FHD" / "mods" / mod_name / "backend" / "blueprints.py"
    )
    spec = importlib.util.spec_from_file_location(
        f"test_{mod_name.replace('-', '_')}_blueprints",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mod_name", BLUEPRINTS)
def test_workflow_employee_failure_does_not_log_or_return_exception_secret(
    mod_name: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = _load_blueprint(mod_name)
    secret = "customer-token-do-not-log"

    class _FailingEmployee:
        @staticmethod
        def run(_payload, _ctx):
            raise RuntimeError(secret)

    monkeypatch.setattr(module, "_load_employee_module", lambda *_args: _FailingEmployee)
    caplog.set_level(logging.INFO)

    result = asyncio.run(module._dispatch_run(mod_name, "employee", "employee", {}))

    assert result["success"] is False
    assert result["error"] == "employee run failed"
    assert secret not in caplog.text
    assert secret not in str(result)


@pytest.mark.parametrize("mod_name", BLUEPRINTS)
def test_workflow_employee_registration_log_omits_caller_mod_id(
    mod_name: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = _load_blueprint(mod_name)
    caller_mod_id = "tenant-secret-mod-id"
    caplog.set_level(logging.INFO)

    module.register_fastapi_routes(FastAPI(), caller_mod_id)

    assert "workflow employee mod registered" in caplog.text
    assert caller_mod_id not in caplog.text
