#!/usr/bin/env python3
# mypy: disable-error-code="no-any-return"
"""coverage_ramp stub 配额棘轮：stub 文件数量只减不增。

``tests/**/test_coverage_ramp_*.py`` 是行覆盖率填充 stub（pyproject markers 自承
"断言弱、杀变体能力低；非行为契约测试"），由 conftest 按文件名前缀自动打
``coverage_ramp`` 标记。它们抬高行覆盖率口径但不构成行为契约，因此数量必须
只减不增——新增 stub 即配额违规。

统计口径与 ``tests/conftest.py`` 的打标规则严格一致：
``basename.startswith("test_coverage_ramp_")`` 的 ``.py`` 文件（排除 __pycache__）。

基线存于 ``metrics/coverage_ramp_baseline.json``：

* ``--check``：数量增加 → 失败（退出码 1）；数量减少 → 通过并提示可 ``--bump`` 收口
* ``--bump`` ：只降方向更新基线（数量减少时下调基线；数量不变/增加均不写入）

退出码：配额违规 ``1``；用法/内部错误 ``2``；正常 ``0``。

用法::

    python scripts/dev/count_coverage_ramp_stubs.py --check   # CI 门禁
    python scripts/dev/count_coverage_ramp_stubs.py --bump    # 删除 stub 后收口基线
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = FHD_ROOT / "tests"
BASELINE = FHD_ROOT / "metrics" / "coverage_ramp_baseline.json"

STUB_PREFIX = "test_coverage_ramp_"


def count_stubs() -> list[Path]:
    """返回当前 stub 文件列表（与 conftest 打标口径一致）。"""
    return sorted(
        p
        for p in TESTS_DIR.rglob(f"{STUB_PREFIX}*.py")
        if "__pycache__" not in p.parts and p.name.startswith(STUB_PREFIX)
    )


def load_baseline() -> dict:
    if BASELINE.is_file():
        try:
            return json.loads(BASELINE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def cmd_check() -> int:
    stubs = count_stubs()
    base = load_baseline()
    floor = base.get("stub_count")
    if floor is None:
        print(f"ERROR: 缺基线 {BASELINE}（或缺 stub_count 字段）", file=sys.stderr)
        return 2
    cur = len(stubs)
    print(f"[ramp-quota] coverage_ramp stub 数量={cur}（配额基线 {floor}，只减不增）")
    if cur > floor:
        print(
            f"FAIL: 新增 {cur - floor} 个 coverage_ramp stub（{floor} -> {cur}）。"
            "行覆盖率必须通过行为测试提升，禁止再加水 stub；"
            "确需新增请先在 docs/adr/ 立 ADR 并人工调整基线。",
            file=sys.stderr,
        )
        for p in stubs:
            print(f"  stub: {p.relative_to(FHD_ROOT).as_posix()}", file=sys.stderr)
        return 1
    if cur < floor:
        print(f"[ramp-quota] stub 净减 {floor - cur} 个，可运行 --bump 把基线收至 {cur}。")
    print("[ramp-quota] OK — stub 配额未超标")
    return 0


def cmd_bump() -> int:
    stubs = count_stubs()
    base = load_baseline()
    floor = base.get("stub_count")
    if floor is None:
        print(f"ERROR: 缺基线 {BASELINE}（或缺 stub_count 字段）", file=sys.stderr)
        return 2
    cur = len(stubs)
    if cur >= int(floor):
        print(f"[ramp-quota] 数量未减少（当前 {cur}，基线 {floor}），基线不变。")
        return 0
    base["stub_count"] = cur
    base["updated"] = date.today().isoformat()
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ramp-quota] 基线已下调 {floor} -> {cur}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="门禁：stub 数量增加则失败（退出码1）")
    mode.add_argument("--bump", action="store_true", help="数量减少时下调基线（只降方向）")
    args = parser.parse_args(argv)
    if args.check:
        return cmd_check()
    if args.bump:
        return cmd_bump()
    return 2


if __name__ == "__main__":
    sys.exit(main())
