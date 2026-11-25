"""回归保护：后端 CI 的依赖必须钉住会导致门禁翻红的浮动版本。

事故（2026-09-25，WO-0f1b3d12bab4）：`CI - Backend Python / modstore-backend-test`
在 **零代码变更** 的 main 上由绿转红。

两次 run 的依赖集合逐项比对后，**唯一**差异是：

    绿灯 313655b20（09-24，mypy 步骤 success）：greenlet-3.5.6 + sqlalchemy-2.0.54
    红灯 d34c354d1（09-25，mypy 步骤 failure，56 条错误）：sqlalchemy-2.1.0

mypy 在两次 run 中都是 2.3.1，不是变量（首轮曾误判为 mypy，CI 实测证伪）。
因此本测试锁两件事：

1. sqlalchemy 必须有显式上界（把已知会翻红的 2.1.x 挡在门外）；
2. lint/gate 类工具与 black/isort 同规则精确固定，避免工具发版静默改判定。

出界即红。sqlalchemy 2.1 的类型迁移是独立立项，不在本门禁内放宽。
"""

from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEPLOY = _REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"
_PYPROJECT = _DEPLOY / "pyproject.toml"

# sqlalchemy 2.1.0 收紧 Query 类型推断，使 ~30 个既有模块被判 56 条错误
_SQLALCHEMY_MAX_EXCLUSIVE = (2, 1)


def _requirement(name: str) -> str:
    text = _PYPROJECT.read_text(encoding="utf-8")
    match = re.search(rf'^\s*"{re.escape(name)}[^"]*",', text, re.MULTILINE)
    assert match, f"{_PYPROJECT} 未声明 {name} 依赖"
    return match.group(0).strip().strip(",").strip('"')


def test_sqlalchemy_has_upper_bound() -> None:
    requirement = _requirement("sqlalchemy")
    assert "<" in requirement, (
        f"sqlalchemy 未设上界（{requirement}）：2.1.0 收紧 Query 类型推断会把既有"
        f"模块判红，而代码零变更。必须显式排除已知会翻红的版本。"
    )
    bound = re.search(r"<\s*(\d+)\.(\d+)", requirement)
    assert bound, f"sqlalchemy 上界不可解析：{requirement}"
    assert (int(bound.group(1)), int(bound.group(2))) <= _SQLALCHEMY_MAX_EXCLUSIVE, (
        f"sqlalchemy 上界 {requirement} 放行了已知会翻红的 2.1.x 及以上"
    )


@pytest.mark.parametrize("tool", ["mypy", "black", "isort"])
def test_lint_tools_are_exactly_pinned(tool: str) -> None:
    requirement = _requirement(tool)
    assert "==" in requirement, (
        f"{tool} 未精确固定（{requirement}）：lint/gate 类工具必须与 black/isort 同规则"
        f"钉死，否则工具发新版会在零代码变更的 main 上改变判定"
    )


_PIN_TOOL = _REPO_ROOT / "FHD/scripts/dev/check_requirements_lock.py"
_INSTALL_WORKFLOWS = [
    ("FHD/.github/workflows/ci-cd.yml", "FHD"),
    ("FHD/.github/workflows/release-gate-ci.yml", "FHD"),
    ("FHD/.github/workflows/test.yml", "FHD"),
    ("FHD/.github/workflows/mac-control-contract.yml", "FHD"),
    (
        "成都修茈科技有限公司/MODstore_deploy/.github/workflows/ci-backend-python.yml",
        "成都修茈科技有限公司/MODstore_deploy",
    ),
    (".github/workflows/customer-delivery-e2e.yml", "."),
    (".github/workflows/e2e-playwright-reusable.yml", "FHD"),
]
_TEST_VERSIONS = {"pytest": "9.1.1", "pytest-cov": "7.1.0", "coverage": "7.15.1"}
_VALID_LOCK = "".join(
    f'[[package]]\nname = "{name}"\nversion = "{version}"\n'
    for name, version in _TEST_VERSIONS.items()
)
_LOCK_CASES = {
    "valid": _VALID_LOCK,
    "missing": None,
    "malformed": "[broken",
    "absent": '[[package]]\nname = "other"\nversion = "1.0"\n',
    "ambiguous": '[[package]]\nname="pytest"\nversion="9.1.1"\n' * 2,
    "empty": '[[package]]\nname="pytest"\nversion=""\n',
    "invalid": '[[package]]\nname="pytest"\nversion="9.1.1; other"\n',
    "nonsensical": '[[package]]\nname="pytest"\nversion="9garbage"\n',
    "prerelease": '[[package]]\nname="pytest"\nversion="9.1.1rc1"\n',
}
_REPORT_LOCK_CASES = {
    "missing_coverage": _VALID_LOCK.split('[[package]]\nname = "coverage"')[0],
    "missing_pytest_cov": _VALID_LOCK.replace(
        '[[package]]\nname = "pytest-cov"\nversion = "7.1.0"\n', ""
    ),
    "ambiguous_coverage": _VALID_LOCK + '[[package]]\nname="coverage"\nversion="7.17.5"\n',
    "unsafe_coverage": _VALID_LOCK.replace("7.15.1", "7.15.1; other"),
}


def test_pytest_pin_uses_canonical_lock_without_mutating_it() -> None:
    lock = _REPO_ROOT / "FHD/uv.lock"
    before = lock.read_bytes()
    tool = runpy.run_path(str(_PIN_TOOL))
    pin = tool["locked_pytest_requirement"]()
    result = subprocess.check_output([sys.executable, str(_PIN_TOOL), "--pytest-pin"], text=True)
    version = next(
        p["version"] for p in tomllib.loads(before.decode())["package"] if p["name"] == "pytest"
    )
    assert result.strip() == pin == f"pytest=={version}"
    assert lock.read_bytes() == before


def test_report_toolchain_pins_use_the_same_unmodified_canonical_lock() -> None:
    lock = _REPO_ROOT / "FHD/uv.lock"
    before = lock.read_bytes()
    packages = tomllib.loads(before.decode())["package"]
    expected = [
        f"{name}=={next(p['version'] for p in packages if p['name'] == name)}"
        for name in _TEST_VERSIONS
    ]
    result = subprocess.check_output(
        [sys.executable, str(_PIN_TOOL), "--test-toolchain-pins"], text=True
    )
    assert result.split() == expected
    assert lock.read_bytes() == before


@pytest.mark.parametrize("tool", _TEST_VERSIONS)
def test_locked_report_tool_satisfies_development_declarations(tool: str) -> None:
    fhd = _REPO_ROOT / "FHD"
    packages = tomllib.loads((fhd / "uv.lock").read_text())["package"]
    version = next(package["version"] for package in packages if package["name"] == tool)
    for line in (fhd / "ops/deploy/requirements-dev.txt").read_text().splitlines():
        declaration = line.partition("#")[0].strip()
        if not declaration:
            continue
        requirement = Requirement(declaration)
        if canonicalize_name(requirement.name) == tool:
            assert version in requirement.specifier, (
                f"{requirement} conflicts with the canonical uv.lock pin {tool}=={version}"
            )


@pytest.mark.parametrize(
    "workflow,cwd,lock_case",
    [(workflow, cwd, case) for workflow, cwd in _INSTALL_WORKFLOWS for case in _LOCK_CASES]
    + [("FHD/.github/workflows/ci-cd.yml", "FHD", case) for case in _REPORT_LOCK_CASES],
)
def test_actual_ci_installs_use_pin_and_stop_before_pip_on_bad_lock(
    tmp_path: Path, workflow: str, cwd: str, lock_case: str
) -> None:
    workspace = tmp_path / "repo with spaces"
    tool = workspace / "FHD/scripts/dev/check_requirements_lock.py"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(_PIN_TOOL.read_bytes())
    payload = {**_LOCK_CASES, **_REPORT_LOCK_CASES}[lock_case]
    if payload is not None:
        (workspace / "FHD/uv.lock").write_text(payload)
    workdir = workspace / cwd
    workdir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "installs.jsonl"
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    wrapper = f"""#!{sys.executable}
import json, os, pathlib, shutil, sys
if len(sys.argv) > 1 and sys.argv[1].endswith("check_requirements_lock.py"):
    os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
if sys.argv[1:3] == ["-m", "venv"]:
    target = pathlib.Path(sys.argv[3]) / "bin/python"
    target.parent.mkdir(parents=True)
    shutil.copyfile(__file__, target)
    target.chmod(0o755)
with open(os.environ["INSTALL_LOG"], "a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
if "--format=json" in sys.argv:
    print("[]")
"""
    for name in ("python", "pip", "uv"):
        path = fakebin / name
        path.write_text(wrapper)
        path.chmod(0o755)
    (fakebin / "pip.py").write_text(
        "import json, os, sys\n"
        'with open(os.environ["INSTALL_LOG"], "a") as stream:\n'
        '    stream.write(json.dumps(sys.argv[1:]) + "\\n")\n'
    )
    env = {**os.environ, "GITHUB_WORKSPACE": str(workspace), "INSTALL_LOG": str(log)}
    env["PATH"] = str(fakebin) + os.pathsep + env["PATH"]
    env["PYTHONPATH"] = str(fakebin)
    jobs = yaml.safe_load((_REPO_ROOT / workflow).read_text())["jobs"]
    installs = [
        step
        for job in jobs.values()
        for step in job.get("steps", [])
        if any(flag in step.get("run", "") for flag in ("--pytest-pin", "--test-toolchain-pins"))
    ]
    assert len(installs) == (
        3 if workflow.endswith("/ci-cd.yml") else 2 if "ci-backend-python" in workflow else 1
    )
    for step in installs:
        log.unlink(missing_ok=True)
        if step.get("shell") == "python":
            script = tmp_path / "workflow_install.py"
            script.write_text(step["run"])
            command = [sys.executable, str(script)]
        else:
            command = ["bash", "-c", step["run"]]
        result = subprocess.run(command, cwd=workdir, env=env, capture_output=True)
        assert (result.returncode == 0) == (lock_case == "valid"), result.stderr.decode()
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        if lock_case == "valid":
            test_installs = [
                args
                for args in calls
                if "install" in args
                and any(
                    "requirements-dev.txt" in arg or "web,dev" in arg or arg == ".[server-api]"
                    for arg in args
                )
            ]
            assert test_installs and all("pytest==9.1.1" in args for args in test_installs)
            if workflow.endswith("/ci-cd.yml"):
                assert all(
                    f"{name}=={version}" in args
                    for args in test_installs
                    for name, version in _TEST_VERSIONS.items()
                )
            for args in test_installs:
                if ".[server-api]" in args:
                    assert args[args.index("-r") + 1] == "requirements-server-api.txt"
        else:
            assert not calls, "A bad or missing lock must stop before any installer runs"


@pytest.mark.parametrize(
    "workflow,names,target",
    [
        (
            "FHD/.github/workflows/ci-cd.yml",
            ("backend-quality", "backend-test-shard", "release-verify"),
            '--system --python "$(command -v python)"',
        ),
        (
            "FHD/.github/workflows/test.yml",
            ("backend-smoke",),
            '--system --python "$(command -v python)"',
        ),
        (
            ".github/workflows/e2e-playwright-reusable.yml",
            ("playwright",),
            "--python .venv/bin/python",
        ),
    ],
)
def test_uv_installer_preserves_dependency_inputs_and_checks_the_target_interpreter(
    workflow, names, target
) -> None:
    jobs = yaml.safe_load((_REPO_ROOT / workflow).read_text())["jobs"]
    for name in names:
        steps = jobs[name]["steps"]
        setup = next(
            step for step in steps if step.get("uses", "").startswith("astral-sh/setup-uv@")
        )
        assert setup["with"]["enable-cache"] is True
        assert set(setup["with"]["cache-dependency-glob"].splitlines()) == {
            "FHD/requirements-server-api.txt",
            "FHD/ops/deploy/requirements-dev.txt",
            "FHD/uv.lock",
            "FHD/pyproject.toml",
            "FHD/packages/**/pyproject.toml",
        }
        python = next(step for step in steps if step.get("uses") == "actions/setup-python@v7")
        assert "cache" not in python["with"]
        command = next(
            step["run"]
            for step in steps
            if any(
                flag in step.get("run", "") for flag in ("--pytest-pin", "--test-toolchain-pins")
            )
        )
        install = f"uv pip install {target}"
        check = f"uv pip check {target}"
        pin_flag, pins = (
            ("--test-toolchain-pins", '"${test_requirements[@]}"')
            if workflow.endswith("/ci-cd.yml")
            else ("--pytest-pin", '"$pytest_pin"')
        )
        assert (
            install + f" -r requirements-server-api.txt -r ops/deploy/requirements-dev.txt {pins}"
            in command
        )
        assert command.index(pin_flag) < command.index(install) < command.index(check)
        assert "--upgrade pip" not in command


def test_pip_runtime_install_supplies_all_vendored_sources() -> None:
    fhd = _REPO_ROOT / "FHD"
    project = tomllib.loads((fhd / "pyproject.toml").read_text())
    requirements = (fhd / "requirements-server-api.txt").read_text().splitlines()
    for name, source in project["tool"]["uv"]["sources"].items():
        path = source["path"]
        assert f"-e ./{path}" in requirements
        package = tomllib.loads((fhd / path / "pyproject.toml").read_text())["project"]
        assert f"{name}=={package['version']}" in project["project"]["dependencies"]
    for name in ("build-backend.sh", "build-backend.ps1"):
        script = (fhd / "scripts/package" / name).read_text()
        installs = [
            line for line in script.splitlines() if "pip install" in line and ' -e ".[' in line
        ]
        assert installs, name
        assert all("-r requirements-server-api.txt" in line for line in installs)
        if name.endswith(".sh"):
            assert 'BACKEND_EXTRAS="server-api"' in script
            assert 'BACKEND_EXTRAS="server-api,computer-use"' in script
            assert all('".[${BACKEND_EXTRAS}]"' in line for line in installs)
        else:
            assert any('".[server-api]"' in line for line in installs)
            assert any('".[server-api,computer-use]"' in line for line in installs)
    jobs = yaml.safe_load((_REPO_ROOT / ".github/workflows/fhd-alembic-ssot.yml").read_text())[
        "jobs"
    ]
    install = next(
        step["run"]
        for job in jobs.values()
        for step in job.get("steps", [])
        if step.get("name") == "Install FHD runtime deps"
    )
    assert 'pip install -r requirements-server-api.txt -e ".[server-api]"' in install
