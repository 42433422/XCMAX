"""SSOT plugin 基础设施单测。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

# 让 tests 能 import scripts.dev.ssot_plugins
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REGISTRY_PATH = ROOT / "config" / "ssot.yaml"


def _registry_domains() -> list[dict]:
    with REGISTRY_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data["domains"]


def test_load_registry_returns_domains():
    """load_registry 解析 ssot.yaml 返回域列表。"""
    from scripts.dev.ssot_plugins.base import load_registry

    domains = load_registry(REGISTRY_PATH)
    assert len(domains) == len(_registry_domains())
    names = [d["name"] for d in domains]
    assert {"mods", "version", "db-schema", "service-topology"}.issubset(names)


def test_load_registry_enabled_filter():
    """enabled_only=True 只返回 enabled 域。"""
    from scripts.dev.ssot_plugins.base import load_registry

    domains = load_registry(REGISTRY_PATH, enabled_only=True)
    expected_enabled = [d for d in _registry_domains() if d.get("enabled", True)]
    assert len(domains) == len(expected_enabled)
    # service-topology 域必须已登记且 enabled
    assert "service-topology" in [d["name"] for d in domains]
    assert all(d.get("enabled", True) for d in domains)


def test_run_command_returns_exit_code():
    """run_command 执行命令并返回退出码。"""
    from scripts.dev.ssot_plugins.base import run_command

    code = run_command(["python", "-c", "import sys; sys.exit(0)"], cwd=ROOT)
    assert code == 0
    code = run_command(["python", "-c", "import sys; sys.exit(3)"], cwd=ROOT)
    assert code == 3
