"""error-codes 域适配器：lint error_codes.py 的自洽性。

检查规则：
1. 常量值唯一（无重复 code）
2. 常量名 == 常量值（当前模式：UNAUTHORIZED = "UNAUTHORIZED"）
3. 全部 UPPER_SNAKE_CASE
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))
from scripts.dev.ssot_plugins.base import ROOT  # noqa: E402

SSOT_FILE = ROOT / "app" / "http" / "error_codes.py"
UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _extract_constants() -> list[tuple[str, str, int]]:
    """从 error_codes.py 提取模块级常量 (name, value, lineno)。"""
    if not SSOT_FILE.is_file():
        return []
    tree = ast.parse(SSOT_FILE.read_text(encoding="utf-8"))
    consts: list[tuple[str, str, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                    if isinstance(node.value.value, str):
                        consts.append((target.id, node.value.value, node.lineno))
    return consts


def check_drift() -> int:
    """只读检查：error_codes.py 自洽性。"""
    if not SSOT_FILE.is_file():
        print(f"error-codes: SSOT 文件不存在 {SSOT_FILE}", flush=True)
        return 2

    consts = _extract_constants()
    if not consts:
        print("error-codes: 未找到任何常量", flush=True)
        return 1

    errors: list[str] = []
    seen_values: dict[str, str] = {}

    for name, value, lineno in consts:
        # 规则 1：常量名 == 常量值
        if name != value:
            errors.append(f"L{lineno}: 常量名 {name} != 值 {value}")
        # 规则 2：UPPER_SNAKE_CASE
        if not UPPER_SNAKE_RE.match(name):
            errors.append(f"L{lineno}: {name} 不符合 UPPER_SNAKE_CASE")
        # 规则 3：值唯一
        if value in seen_values:
            errors.append(f"L{lineno}: 值 {value} 重复（首次在 {seen_values[value]}）")
        else:
            seen_values[value] = f"L{lineno} {name}"

    if errors:
        print(f"error-codes: {len(errors)} 个问题", flush=True)
        for e in errors:
            print(f"  - {e}", flush=True)
        return 1

    print(f"error-codes: OK（{len(consts)} 个常量自洽）", flush=True)
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("error-codes: lint 模式无 sync", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
