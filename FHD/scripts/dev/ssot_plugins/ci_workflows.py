"""ci-workflows 域适配器。

publish 脚本无 --check 模式且会写文件；MVP check 采用只读 header 检查：
验证根仓每个 fhd-*.yml / modstore-*.yml 含 "# CI SSOT: generated from" 头。
完整内容漂移检测留待后续（需 publish 支持 --dry-run）。

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

REPO_ROOT = _FHD_ROOT.parent  # 仓根（publish 脚本在 scripts/dev/ 而非 FHD/scripts/dev/）
GENERATED_PREFIX = "fhd-"
EXTRA_GENERATED = ("modstore-",)  # 这些前缀的根 workflow 应为生成件


def _is_generated_workflow(path: Path) -> bool:
    """判断根仓 workflow 是否应为生成件（按命名约定）。"""
    name = path.name
    if name.startswith(GENERATED_PREFIX):
        return True
    return any(name.startswith(p) for p in EXTRA_GENERATED)


def check_drift() -> int:
    """只读检查：生成件 workflow 应含 CI SSOT 头。返回 0=一致 1=漂移。"""
    root_wfs = REPO_ROOT / ".github" / "workflows"
    if not root_wfs.is_dir():
        print("ci-workflows: 根 .github/workflows/ 不存在", file=sys.stderr)
        return 1
    drift = 0
    for yml in sorted(root_wfs.glob("*.yml")):
        if not _is_generated_workflow(yml):
            continue
        text = yml.read_text(encoding="utf-8") if yml.stat().st_size else ""
        first_line = text.splitlines()[0] if text else ""
        if "CI SSOT" not in first_line and "generated from" not in first_line:
            print(f"ci-workflows: {yml.name} 缺 CI SSOT 生成头（应为生成件）", file=sys.stderr)
            drift = 1
    if drift == 0:
        print("ci-workflows: OK（生成件 header 检查通过）")
    return drift


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        return run_command(
            ["python", "scripts/dev/publish_ci_workflows_to_root.py"],
            cwd=REPO_ROOT,
        )
    return 2


if __name__ == "__main__":
    # 支持 `python .../ci_workflows.py check` 直接调用（注册表 check 命令路径）
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
