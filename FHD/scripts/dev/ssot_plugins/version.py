"""version 域适配器：check 转发到 verify_version_anchors.py，sync 转发到 version_sync.py。

两者共享 ANCHORS 列表，保证"检测的锚点 = 同步的锚点"。
"""
from __future__ import annotations

from typing import Any

from .base import ROOT, run_command


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return run_command(["python", "scripts/dev/verify_version_anchors.py"], cwd=ROOT)
    if action == "sync":
        # version_sync.py 默认 dry-run，--apply 真写
        cmd = ["python", "scripts/dev/version_sync.py"]
        if not dry_run:
            cmd.append("--apply")
        return run_command(cmd, cwd=ROOT)
    return 2
