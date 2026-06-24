"""service-topology SSOT 派生守卫：5 目标无漂移 + 源 schema 合法。

自包含（subprocess，不 import app），不触发 app.services 的预存循环导入。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
SCRIPT = FHD / "scripts" / "dev" / "service_topology_ssot.py"
SOURCE = FHD / "config" / "service_topology.yaml"


def test_service_topology_targets_in_sync():
    """5 个派生产物与 service_topology.yaml 一致；漂移则失败并提示重生成。"""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "check"],
        cwd=str(FHD),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "service-topology 派生漂移，请运行 "
        "python scripts/dev/service_topology_ssot.py generate --apply\n"
        + result.stdout
        + result.stderr
    )


def test_service_topology_source_schema():
    """源文件必填字段齐全、端口在合法范围、public_urls 每条有 const_name。"""
    import yaml

    data = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    public = data.get("public") or {}
    assert public.get("host"), "public.host 不能为空"
    assert public.get("scheme") in {"http", "https"}, "public.scheme 必须为 http/https"

    services = data.get("services") or {}
    assert services, "至少声明一个服务"
    for sid, svc in services.items():
        for key in ("listen_port", "nginx_upstream_port"):
            port = (svc or {}).get(key)
            if port is not None:
                assert isinstance(port, int) and 1 <= port <= 65535, f"{sid}.{key} 端口非法: {port}"

    for item in data.get("public_urls") or []:
        assert item.get("const_name"), "public_urls 条目缺 const_name"


def test_service_topology_generate_is_idempotent():
    """连跑两次 generate --apply 后 check 仍为 0（确定性输出，无抖动）。"""
    for _ in range(2):
        subprocess.run(
            [sys.executable, str(SCRIPT), "generate", "--apply"],
            cwd=str(FHD),
            capture_output=True,
            text=True,
        )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "check"],
        cwd=str(FHD),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
