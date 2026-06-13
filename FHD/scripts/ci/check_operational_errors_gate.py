#!/usr/bin/env python3
"""CI gate: 守护异常处理 SSOT（2026-06-13 技术债清偿）。

校验两件事：

1. 旧符号 ``OPERATIONAL_ERRORS`` 不得在 ``app/`` 中复活。它已拆分为
   ``INFRA_TRANSIENT`` / ``DATA_SHAPE`` / ``RECOVERABLE_ERRORS``
   （见 ``app/utils/operational_errors.py``）。

2. ``app/utils/operational_errors.py`` 仍导出三个 SSOT 名称，避免
   被误删导致全仓 ``except RECOVERABLE_ERRORS`` 崩塌。

非零退出即代表门禁失败。CI 与本地均可运行：

    python scripts/ci/check_operational_errors_gate.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "app"
SSOT_MODULE = APP_DIR / "utils" / "operational_errors.py"

FORBIDDEN_SYMBOL = re.compile(r"\bOPERATIONAL_ERRORS\b")
REQUIRED_EXPORTS = ("INFRA_TRANSIENT", "DATA_SHAPE", "RECOVERABLE_ERRORS")

# SSOT 模块自身允许在 docstring 里提及历史名；其余源码不得出现。
ALLOWLIST = {SSOT_MODULE}


def _iter_app_py_files() -> list[Path]:
    return [
        p
        for p in APP_DIR.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def check_no_legacy_symbol() -> list[str]:
    offenders: list[str] = []
    for path in _iter_app_py_files():
        if path in ALLOWLIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if FORBIDDEN_SYMBOL.search(line):
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    return offenders


def check_ssot_exports() -> list[str]:
    problems: list[str] = []
    if not SSOT_MODULE.exists():
        return [f"缺失 SSOT 模块: {SSOT_MODULE.relative_to(REPO_ROOT)}"]
    text = SSOT_MODULE.read_text(encoding="utf-8")
    for name in REQUIRED_EXPORTS:
        if not re.search(rf"^{name}\b", text, flags=re.MULTILINE):
            problems.append(f"SSOT 模块缺少导出: {name}")
    return problems


def main() -> int:
    offenders = check_no_legacy_symbol()
    export_problems = check_ssot_exports()

    if not offenders and not export_problems:
        print("[operational-errors-gate] OK：异常 SSOT 完整，无旧符号复活。")
        return 0

    if offenders:
        print("[operational-errors-gate] 检测到已废弃的 OPERATIONAL_ERRORS（请改用 "
              "INFRA_TRANSIENT / DATA_SHAPE / RECOVERABLE_ERRORS）：")
        for line in offenders:
            print(f"  - {line}")
    if export_problems:
        print("[operational-errors-gate] SSOT 导出校验失败：")
        for line in export_problems:
            print(f"  - {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
