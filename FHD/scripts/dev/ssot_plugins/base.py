"""SSOT plugin 基础设施：注册表加载 + 命令执行。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]


def load_registry(path: Path | None = None, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    """加载 ssot.yaml 注册表，返回域列表。

    Args:
        path: ssot.yaml 路径，默认 FHD/config/ssot.yaml
        enabled_only: True 时只返回 enabled 域（缺省 enabled 视为 True）
    """
    if path is None:
        path = ROOT / "config" / "ssot.yaml"
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    domains = data.get("domains", [])
    if enabled_only:
        domains = [d for d in domains if d.get("enabled", True)]
    return domains


def _normalize_cmd(cmd: list[str]) -> list[str]:
    """将 cmd[0]=='python' 替换为当前解释器，跨环境兼容（CI 有 python，macOS 仅 python3）。"""
    if cmd and cmd[0] == "python":
        return [sys.executable] + cmd[1:]
    return cmd


def run_command(cmd: list[str], *, cwd: Path | None = None, silent: bool = False) -> int:
    """执行命令，返回退出码。silent=True 时吞掉 stdout/stderr（用于 drift JSON 输出）。"""
    if cwd is None:
        cwd = ROOT
    if silent:
        return subprocess.call(
            _normalize_cmd(cmd), cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    return subprocess.call(_normalize_cmd(cmd), cwd=str(cwd))


def find_domain(domains: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """按 name 查找域配置。"""
    for d in domains:
        if d["name"] == name:
            return d
    return None
