"""SSOT plugin 适配器集成测。

验证每个适配器能正确调用现有脚本并返回退出码。
不 mock 现有脚本（真实集成），但用真实注册表。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_mods_adapter_run_check():
    """mods 适配器调用 mods_ssot.py check。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.mods import run

    d = find_domain(load_registry(), "mods")
    code = run("check", d, dry_run=True)
    # 真实环境可能 0（一致）或 1（漂移），不应是 2/3（配置/执行错）
    assert code in (0, 1)


def test_ci_workflows_adapter_run_check():
    """ci_workflows 适配器对根 workflow 做全内容渲染检查。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.ci_workflows import run

    d = find_domain(load_registry(), "ci-workflows")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_coverage_adapter_run_check():
    """coverage 域登记三层真相，并由 metadata check 守护。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry

    d = find_domain(load_registry(), "coverage")
    assert d["truth_layers"]["threshold"]
    assert d["truth_layers"]["measurement"]["policy"] == "ephemeral-required-in-ci-producer-jobs"
    assert d["truth_layers"]["publication"]["snapshot"].endswith("coverage-dual-summary.json")
    assert d["check"] == "python scripts/ci/check_coverage_ssot.py"


def test_version_adapter_run_check():
    """version 适配器调用 verify_version_anchors.py。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.version import run

    d = find_domain(load_registry(), "version")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_docs_ssot_adapter_run_check():
    """docs_ssot 适配器执行严格 lint 和自动清单漂移检查。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.docs_ssot import run

    d = find_domain(load_registry(), "docs-ssot")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_test_files_adapter_run_check():
    """test_files 适配器 lint tests/ 目录。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.test_files import run

    d = find_domain(load_registry(), "test-files")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_deploy_scripts_adapter_run_check():
    """deploy_scripts 适配器 lint scripts/deploy/。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.deploy_scripts import run

    d = find_domain(load_registry(), "deploy-scripts")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_deps_adapter_run_check():
    """deps 适配器比较 pyproject vs requirements*.txt。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.deps import run

    d = find_domain(load_registry(), "deps")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_error_codes_adapter_run_check():
    """error_codes 适配器 lint error_codes.py 自洽性。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.error_codes import run

    d = find_domain(load_registry(), "error-codes")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_all_adapters_conform_to_protocol():
    """所有 enabled 域的 check 命令可被 shlex 解析。"""
    import shlex

    from scripts.dev.ssot_plugins.base import load_registry

    for d in load_registry(enabled_only=True):
        cmd = d.get("check")
        assert cmd, f"{d['name']} 缺 check 命令"
        argv = shlex.split(cmd)
        assert len(argv) >= 1, f"{d['name']} check 命令解析为空"
