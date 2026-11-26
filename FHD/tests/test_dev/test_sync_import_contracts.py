"""Exercise the actual Import Linter contracts with isolated dependency mutations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _lint(root: Path, *contracts: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            "--config",
            str(ROOT / "pyproject.toml"),
            "--no-cache",
            "--no-logo",
            *[arg for contract in contracts for arg in ("--contract", contract)],
        ],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _package(root: Path, name: str, source: str = "") -> Path:
    path = root
    for part in name.split("."):
        path /= part
        path.mkdir(exist_ok=True)
        (path / "__init__.py").touch()
    module = path / "__init__.py"
    module.write_text(source)
    return module


@pytest.mark.parametrize("violation", [None, "direct_driver", "reverse_dependency"])
def test_sync_contracts_allow_dal_but_reject_bypasses(tmp_path, violation):
    for package in (
        "app",
        "app/db",
        "app/domain",
        "app/domain/shared_services",
        "app/application",
        "app/services",
        # The real contract names these entrypoints. The isolated tree must
        # contain them or import-linter aborts before it can keep or break
        # the sync contracts.
        "app/fastapi_routes",
        "app/fastapi_app",
    ):
        directory = tmp_path / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("")
    service = "from app.db.xcmax_sync import SyncDb\n"
    dao = "import sqlite3\nclass SyncDb: pass\n"
    if violation == "direct_driver":
        service += "import sqlite3\n"
    if violation == "reverse_dependency":
        dao += "from app.helpers import action\n"
    # debt19: import-linter contract targets domain.shared_services (not app.services)
    (tmp_path / "app/domain/shared_services/xcmax_sync_service.py").write_text(service)
    (tmp_path / "app/db/xcmax_sync.py").write_text(dao)
    (tmp_path / "app/helpers.py").write_text("from app.application.service import action\n")
    (tmp_path / "app/application/service.py").write_text("def action(): pass\n")
    result = _lint(tmp_path, "sync-service-uses-dal", "sync-dal-stays-low-level")
    assert result.returncode == (0 if violation is None else 1), result.stdout + result.stderr
    assert ("2 kept, 0 broken" if violation is None else "1 kept, 1 broken") in result.stdout


@pytest.mark.parametrize(
    "contract_id,source",
    [
        ("approval-domain-no-infrastructure", "app.domain.approval"),
        ("workflow-domain-ports-independent", "app.domain.workflow"),
        ("workflow-application-ports-independent", "app.application.workflow.ports"),
        ("workflow-application-ports-independent", "app.application.workflow.workflow_types"),
        ("product-domain-no-entrypoints", "app.domain.product"),
        ("runtime-result-rules-independent", "app.domain.task_lifecycle.agent_runtime_results"),
    ],
)
@pytest.mark.parametrize(
    "violation", [None, "absolute", "relative", "indirect", "missing", "syntax"]
)
def test_domain_and_port_contracts_reject_reverse_dependencies(
    tmp_path, contract_id, source, violation
):
    contracts = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["importlinter"][
        "contracts"
    ]
    contract = next(item for item in contracts if item["id"] == contract_id)
    assert not contract.get("ignore_imports")
    assert not contract.get("allow_indirect_imports")
    for module in contract["source_modules"] + contract["forbidden_modules"] + ["app.neutral"]:
        if not module.startswith("app."):
            continue
        _package(tmp_path, module)
    source_file = tmp_path.joinpath(*source.split("."), "__init__.py")
    source_file.write_text("from decimal import Decimal\n")
    if violation == "absolute":
        source_file.write_text("import app.infrastructure\n")
    elif violation == "relative":
        source_file.write_text(f"from {'.' * len(source.split('.'))} import infrastructure\n")
    elif violation == "indirect":
        source_file.write_text("from app import neutral\n")
        (tmp_path / "app/neutral/__init__.py").write_text("import app.infrastructure\n")
    elif violation == "missing":
        source_file.unlink()
    elif violation == "syntax":
        source_file.write_text("def broken(:\n")
    result = _lint(tmp_path, contract_id)
    if violation in {"missing", "syntax"}:
        assert result.returncode != 0, result.stdout + result.stderr
        return
    assert result.returncode == (0 if violation is None else 1), result.stdout + result.stderr
    assert ("1 kept, 0 broken" if violation is None else "0 kept, 1 broken") in result.stdout


@pytest.mark.parametrize("sdk", ["langgraph", "langgraph_sdk"])
@pytest.mark.parametrize(
    "importer, allowed",
    [
        ("app.infrastructure.workflow.checkpoint_bridge", True),
        ("app.infrastructure.workflow.langgraph_execution", True),
        ("app.infrastructure.workflow.langgraph_runtime", True),
        ("app.infrastructure.workflow.unrelated_worker", False),
        ("app.application.controller", False),
        ("app.di.registry", False),
    ],
)
def test_langgraph_imports_require_an_explicit_workflow_module(tmp_path, sdk, importer, allowed):
    for module in ("checkpoint_bridge", "langgraph_execution", "langgraph_runtime"):
        _package(tmp_path, f"app.infrastructure.workflow.{module}")
    _package(tmp_path, importer, f"from {sdk}.types import Runtime\n")
    contract = (
        "no-langgraph-outside-infra-workflow"
        if sdk == "langgraph"
        else "host-does-not-use-remote-langgraph-sdk"
    )
    result = _lint(tmp_path, contract)
    expected = 0 if sdk == "langgraph" and allowed else 1
    assert result.returncode == expected, result.stdout + result.stderr
    assert ("1 kept, 0 broken" if expected == 0 else "0 kept, 1 broken") in result.stdout


@pytest.mark.parametrize("violation", [None, "outside_bridge", "stale_exception"])
def test_workflow_neuro_bridge_keeps_only_existing_imports(tmp_path, violation):
    _package(tmp_path, "app.neuro_bus.bus")
    _package(tmp_path, "app.neuro_bus.events.events_base")
    bridge = "import app.neuro_bus.bus\nimport app.neuro_bus.events.events_base\n"
    if violation == "stale_exception":
        bridge = "import app.neuro_bus.bus\n"
    _package(tmp_path, "app.infrastructure.workflow.neuro_bus_bridge", bridge)
    _package(
        tmp_path,
        "app.infrastructure.workflow.other",
        "import app.neuro_bus.bus\n" if violation == "outside_bridge" else "",
    )
    result = _lint(tmp_path, "neuro-bus-only-in-infra-workflow-bridge")
    assert result.returncode == (0 if violation is None else 1), result.stdout + result.stderr


@pytest.mark.parametrize("violation", [None, "absolute", "relative"])
def test_application_uses_workflow_composition_root(tmp_path, violation):
    _package(tmp_path, "app.infrastructure.workflow")
    _package(tmp_path, "app.di.registry", "import app.infrastructure.workflow\n")
    source = "import app.di.registry\n"
    if violation == "absolute":
        source = "import app.infrastructure.workflow\n"
    elif violation == "relative":
        source = "from ...infrastructure import workflow\n"
    _package(tmp_path, "app.application.consumer", source)
    result = _lint(tmp_path, "application-must-not-import-infra-workflow")
    assert result.returncode == (0 if violation is None else 1), result.stdout + result.stderr


@pytest.mark.parametrize("source", ["receipts", "receipt_projection"])
@pytest.mark.parametrize("violation", [False, True])
def test_receipt_readback_does_not_import_coordinator_helpers(tmp_path, source, violation):
    _package(tmp_path, "app.domain.task_lifecycle.agent_runtime_results")
    _package(tmp_path, "app.application.agent_runtime.xiaox_runtime")
    _package(
        tmp_path,
        "app.application.agent_runtime.gateway",
        "import app.application.agent_runtime.xiaox_runtime\n",
    )
    for module in ("receipts", "receipt_projection"):
        _package(tmp_path, f"app.infrastructure.xiaox.{module}")
    _package(
        tmp_path,
        f"app.infrastructure.xiaox.{source}",
        "from app.application.agent_runtime.xiaox_runtime import _classify\n"
        if violation
        else "import app.domain.task_lifecycle.agent_runtime_results\nimport app.application.agent_runtime.gateway\n",
    )
    result = _lint(tmp_path, "receipt-readback-no-coordinator-internals")
    assert result.returncode == int(violation), result.stdout + result.stderr


def test_architecture_job_runs_contracts_without_waiving_failures():
    source = yaml.safe_load((ROOT / ".github/workflows/ci-cd.yml").read_text())
    steps = source["jobs"]["arch-fitness"]["steps"]
    step = next(step for step in steps if step.get("name") == "Check architecture import contracts")
    assert step["run"] == "lint-imports --config pyproject.toml --no-cache"
    assert not step.get("continue-on-error")


@pytest.mark.parametrize("missing", [None, "dev_requirement", "import-linter", "grimp"])
def test_architecture_installer_uses_frozen_versions_and_requires_evidence(tmp_path, missing):
    source = yaml.safe_load((ROOT / ".github/workflows/ci-cd.yml").read_text())
    step = next(
        step
        for step in source["jobs"]["arch-fitness"]["steps"]
        if step.get("name") == "Install architecture contract checker from dependency SSOT"
    )
    lines = step["run"].strip().splitlines()
    assert lines[0] == "python - <<'PYTHON'" and lines[-1] == "PYTHON"
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dev = config["project"]["optional-dependencies"]["dev"]
    requirement = next(value for value in dev if value.startswith("import-linter"))
    (tmp_path / "pyproject.toml").write_text(
        "[project.optional-dependencies]\ndev = "
        + repr([] if missing == "dev_requirement" else [requirement])
        + "\n"
    )
    packages = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    versions = {
        p["name"]: p["version"] for p in packages if p["name"] in {"import-linter", "grimp"}
    }
    (tmp_path / "uv.lock").write_text(
        "\n".join(
            f'[[package]]\nname = "{name}"\nversion = "{version}"\n'
            for name, version in versions.items()
            if name != missing
        )
    )
    installer = tmp_path / "architecture_installer.py"
    installer.write_text("\n".join(lines[1:-1]) + "\n")
    call_path = tmp_path / "pip-call.json"
    (tmp_path / "pip.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path('pip-call.json').write_text(json.dumps({"
        "'executable': sys.executable, 'args': sys.argv[1:]}))\n"
    )
    result = subprocess.run(
        [sys.executable, str(installer)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "PIP_NO_INDEX": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    if missing:
        assert result.returncode != 0, result.stdout + result.stderr
        assert (
            "AssertionError" if missing == "dev_requirement" else "StopIteration"
        ) in result.stderr
        assert not call_path.exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(call_path.read_text()) == {
            "executable": sys.executable,
            "args": [
                "install",
                *(f"{name}=={versions[name]}" for name in ("import-linter", "grimp")),
            ],
        }


def test_checker_is_present_in_both_dev_manifests_and_frozen_lock():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    requirement = next(
        value
        for value in config["project"]["optional-dependencies"]["dev"]
        if value.startswith("import-linter")
    )
    assert requirement in (ROOT / "ops/deploy/requirements-dev.txt").read_text().splitlines()
    packages = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    assert {"grimp", "import-linter"} <= {package["name"] for package in packages}
    project = next(package for package in packages if package["name"] == config["project"]["name"])
    assert "import-linter" in {
        dependency["name"] for dependency in project["optional-dependencies"]["dev"]
    }
