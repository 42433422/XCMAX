"""mods 域适配器：转发到 mods_ssot.py。"""
from __future__ import annotations

from typing import Any

from .base import ROOT, run_command


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    """action: check | sync。dry_run 仅对 sync 生效。"""
    if action == "check":
        return run_command(["python", "scripts/dev/mods_ssot.py", "check"], cwd=ROOT)
    if action == "sync":
        cmd = ["python", "scripts/dev/mods_ssot.py", "sync"]
        if dry_run:
            cmd.append("--dry-run")
        return run_command(cmd, cwd=ROOT)
    return 2
