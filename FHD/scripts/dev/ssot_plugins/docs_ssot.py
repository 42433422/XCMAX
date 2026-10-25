"""docs-ssot 域适配器：转发到 docs_ssot_lint.py。"""

from __future__ import annotations

from typing import Any

from .base import ROOT, run_command


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        # gate / ssot_cli check 与 ci-cd docs-ssot 步骤对齐：告警即失败。
        return run_command(["python", "scripts/dev/docs_ssot_lint.py", "--strict"], cwd=ROOT)
    return 2
