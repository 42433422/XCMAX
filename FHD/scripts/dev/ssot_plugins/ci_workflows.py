"""ci-workflows 域适配器：对实现源与根 workflow 做全内容渲染对比。

注意：本文件既被当作模块 import（from .base import ...），
也被当作脚本直接运行（注册表 check 命令 python .../ci_workflows.py check）。
故用绝对 import + sys.path 兜底，兼容两种调用方式。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 脚本直跑时补全包路径；模块 import 时 sys.path 已由调用方设置
_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

from scripts.dev.ssot_plugins.base import run_command  # noqa: E402

REPO_ROOT = _FHD_ROOT.parent
PUBLISHER = REPO_ROOT / "scripts" / "dev" / "publish_ci_workflows_to_root.py"


def check_drift() -> int:
    """只读全内容检查。返回 0=一致，1=渲染内容漂移。"""
    if not PUBLISHER.is_file():
        print(f"ci-workflows: publisher 不存在: {PUBLISHER}", file=sys.stderr)
        return 1
    return run_command(["python", str(PUBLISHER), "--check"], cwd=REPO_ROOT)


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        return run_command(
            ["python", str(PUBLISHER), "--apply"],
            cwd=REPO_ROOT,
        )
    return 2


if __name__ == "__main__":
    # 支持 `python .../ci_workflows.py check` 直接调用（注册表 check 命令路径）
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
