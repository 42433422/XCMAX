"""Exercise both directions of the migrated sync slice's import contracts."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("violation", [None, "direct_driver", "reverse_dependency"])
def test_sync_contracts_allow_dal_but_reject_bypasses(tmp_path, violation):
    for package in ("app", "app/db", "app/services", "app/application"):
        directory = tmp_path / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("")
    service = "from app.db.xcmax_sync import SyncDb\n"
    dao = "import sqlite3\nclass SyncDb: pass\n"
    if violation == "direct_driver":
        service += "import sqlite3\n"
    if violation == "reverse_dependency":
        dao += "from app.helpers import action\n"
    (tmp_path / "app/services/xcmax_sync_service.py").write_text(service)
    (tmp_path / "app/db/xcmax_sync.py").write_text(dao)
    (tmp_path / "app/helpers.py").write_text("from app.application.service import action\n")
    (tmp_path / "app/application/service.py").write_text("def action(): pass\n")
    environment = {**os.environ, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            "--config",
            str(ROOT / "pyproject.toml"),
            "--no-cache",
            "--no-logo",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == (0 if violation is None else 1), result.stdout + result.stderr
    assert ("2 kept, 0 broken" if violation is None else "1 kept, 1 broken") in result.stdout


def test_architecture_job_runs_contracts_without_waiving_failures():
    source = yaml.safe_load((ROOT / ".github/workflows/ci-cd.yml").read_text())
    steps = source["jobs"]["arch-fitness"]["steps"]
    step = next(
        step for step in steps if step.get("name") == "Check sync data-access import contracts"
    )
    assert step["run"] == "lint-imports --config pyproject.toml --no-cache"
    assert not step.get("continue-on-error")


def test_checker_is_present_in_both_dev_manifests_and_frozen_lock():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    requirement = next(
        value
        for value in config["project"]["optional-dependencies"]["dev"]
        if value.startswith("import-linter")
    )
    assert requirement in (ROOT / "deploy/requirements-dev.txt").read_text().splitlines()
    packages = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    assert {"grimp", "import-linter"} <= {package["name"] for package in packages}
    project = next(package for package in packages if package["name"] == config["project"]["name"])
    assert "import-linter" in {
        dependency["name"] for dependency in project["optional-dependencies"]["dev"]
    }
