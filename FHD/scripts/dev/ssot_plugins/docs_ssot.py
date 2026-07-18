"""docs-ssot 域适配器：严格声明 lint + 自动生成清单漂移检查。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

from scripts.dev.ssot_plugins.base import ROOT, run_command  # noqa: E402


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        lint_code = run_command(["python", "scripts/dev/docs_ssot_lint.py", "--strict"], cwd=ROOT)
        inventory_code = run_command(
            ["python", "scripts/dev/generate_ssot_framework.py", "--check"], cwd=ROOT
        )
        return 1 if lint_code or inventory_code else 0
    if action == "sync":
        return run_command(
            ["python", "scripts/dev/generate_ssot_framework.py", "--apply"], cwd=ROOT
        )
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=action != "sync"))
