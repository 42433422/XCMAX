"""SSOT plugin 基础设施单测。"""

from __future__ import annotations

import sys
from pathlib import Path

# 让 tests 能 import scripts.dev.ssot_plugins
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_load_registry_returns_domains():
    """load_registry 解析 ssot.yaml 返回域列表。"""
    from scripts.dev.ssot_plugins.base import load_registry

    domains = load_registry(ROOT / "config" / "ssot.yaml")
    assert len(domains) == 16
    names = [d["name"] for d in domains]
    assert (
        "mods" in names
        and "version" in names
        and "service-topology" in names
        and "account-identity" in names
    )


def test_load_registry_enabled_filter():
    """enabled_only=True 只返回 enabled 域。"""
    from scripts.dev.ssot_plugins.base import load_registry

    domains = load_registry(ROOT / "config" / "ssot.yaml", enabled_only=True)
    assert len(domains) == 16  # 全部 16 域已启用
    assert all(d.get("enabled", True) for d in domains)


def test_run_command_returns_exit_code():
    """run_command 执行命令并返回退出码。"""
    from scripts.dev.ssot_plugins.base import run_command

    code = run_command(["python", "-c", "import sys; sys.exit(0)"], cwd=ROOT)
    assert code == 0
    code = run_command(["python", "-c", "import sys; sys.exit(3)"], cwd=ROOT)
    assert code == 3
