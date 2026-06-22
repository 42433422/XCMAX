"""test-files 域适配器：lint tests/ 目录的文件命名规范。

检查规则（与 guard_temp_scripts.py 一致）：
1. 禁止临时文件：_fail*.txt, fix_*.py, check_*.py, final_*.py, *.v1_backup
2. 禁止裸诊断脚本：_find_zero.py, _analyze_coverage.py
3. 测试文件应匹配 test_*.py 或 *_test.py（仅警告，不阻断）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))
from scripts.dev.ssot_plugins.base import ROOT  # noqa: E402

TESTS_ROOT = ROOT / "tests"

FORBIDDEN_BASENAMES = {"_find_zero.py", "_analyze_coverage.py"}
TEMP_PREFIXES = ("fix_", "check_", "final_")
FAIL_RE = re.compile(r"^_fail.*\.txt$")
BACKUP_RE = re.compile(r"\.v1_backup$")


def _is_forbidden(rel: Path) -> str | None:
    """返回违规原因，None 表示合规。"""
    name = rel.name
    if name in FORBIDDEN_BASENAMES:
        return f"禁止的诊断脚本: {name}"
    if FAIL_RE.match(name):
        return f"临时失败标记: {name}"
    if BACKUP_RE.search(name):
        return f"备份文件: {name}"
    if name.endswith(".py") and any(name.startswith(p) for p in TEMP_PREFIXES):
        return f"临时脚本前缀: {name}"
    return None


def check_drift() -> int:
    """只读检查：tests/ 目录无禁止文件。"""
    if not TESTS_ROOT.is_dir():
        print(f"test-files: tests 目录不存在 {TESTS_ROOT}", flush=True)
        return 2

    violations: list[str] = []
    for path in TESTS_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(TESTS_ROOT)
        reason = _is_forbidden(rel)
        if reason:
            violations.append(f"{rel}: {reason}")

    if violations:
        print(f"test-files: {len(violations)} 个违规文件", flush=True)
        for v in violations:
            print(f"  - {v}", flush=True)
        return 1

    print(f"test-files: OK（{TESTS_ROOT.name}/ 无禁止文件）", flush=True)
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("test-files: lint 模式无 sync", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
