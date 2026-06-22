"""coverage 域适配器：转发到 coverage_ratchet.py。"""
from __future__ import annotations

from typing import Any

from .base import ROOT, run_command


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return run_command(["python", "scripts/dev/coverage_ratchet.py", "--check"], cwd=ROOT)
    if action == "sync":
        # ratchet bump 需显式，sync 不自动 bump
        return run_command(["python", "scripts/dev/coverage_ratchet.py", "--bump"], cwd=ROOT)
    return 2
