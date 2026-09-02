#!/usr/bin/env python3
"""前端显式 any 棘轮计数器（技术债度量 SSOT，spec D2-1/D2-4）。

统计跨栈前端源码中类型注解/断言里的显式 ``any`` 出现次数，配合
``FHD/metrics/ts_any_baseline.json`` 基线实现"只减不增"棘轮：
债务回增时 ``--check`` 退出码 1 并列出主要来源文件；清偿后用 ``--bump``
收口基线（只降方向）。

统计范围（相对仓库根）：

* ``FHD/frontend/src``、``FHD/admin-console/src``、``FHD/sunbird-console/src``、
  ``FHD/mods``、``成都修茈科技有限公司/MODstore_deploy/market/src``：
  ``.ts``/``.tsx``/``.js``/``.jsx``/``.vue``
* ``FHD/desktop``、``成都修茈科技有限公司/MODstore_deploy/desktop-shell``：
  仅 ``.ts``/``.tsx`` 顶层 Electron 主进程/渲染模块

排除：生成目录（node_modules/dist/coverage/.vite/build 等）、测试文件
（``*.test.*``/``*.spec.*``/``*_test.*``）与测试目录（``__tests__``/
``test-fixtures``）。

匹配模式（逐行扫描 + 行内区间去重，同一处重叠命中只计一次）：
``: any``、``<any>``、``as any``、``any[]``、``any |``、``| any``、
``Record<string, any>``。

用法::

    python scripts/dev/count_ts_any.py --json        # stdout 输出 {"total":N,"by_file":{path:count}}
    python scripts/dev/count_ts_any.py --check       # CI 门禁：当前 > 基线则退出 1 并列出前 10 来源
    python scripts/dev/count_ts_any.py --bump        # 当前 < 基线时下调基线（只降方向）
    python scripts/dev/count_ts_any.py --top 20      # 显示计数最多的前 20 个文件

退出码：债务回增 ``1``；用法/内部错误 ``2``；正常 ``0``。
仅依赖标准库，兼容 Python 3.9 与 3.11（不用 ``datetime.UTC``）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "FHD" / "metrics" / "ts_any_baseline.json"

# 各扫描根及其允许的源码扩展名（desktop/desktop-shell 只统计 .ts/.tsx）
_ALL_FRONTEND_EXTS = frozenset({".ts", ".tsx", ".js", ".jsx", ".vue"})
_TS_ONLY_EXTS = frozenset({".ts", ".tsx"})
SCAN_ROOTS: list[tuple[str, frozenset[str]]] = [
    ("FHD/frontend/src", _ALL_FRONTEND_EXTS),
    ("FHD/admin-console/src", _ALL_FRONTEND_EXTS),
    ("FHD/sunbird-console/src", _ALL_FRONTEND_EXTS),
    ("FHD/mods", _ALL_FRONTEND_EXTS),
    ("FHD/desktop", _TS_ONLY_EXTS),
    ("成都修茈科技有限公司/MODstore_deploy/market/src", _ALL_FRONTEND_EXTS),
    ("成都修茈科技有限公司/MODstore_deploy/desktop-shell", _TS_ONLY_EXTS),
]

# 排除的生成/辅助目录名（任意层级命中即剪枝）
EXCLUDED_DIR_NAMES = {
    "node_modules",
    "dist",
    "coverage",
    ".vite",
    ".output",
    ".nuxt",
    "build",
    "generated",
    "vendor",
    "htmlcov",
    "__pycache__",
    "__tests__",
    "test-fixtures",
    "fixtures",
}
# 排除的测试文件名标记
TEST_NAME_MARKERS = (".test.", ".spec.", "_test.")

# 显式 any 匹配模式（按任务口径固定）
ANY_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r":\s*any\b",
        r"<any>",
        r"as\s+any\b",
        r"any\[\]",
        r"any\s*\|",
        r"\|\s*any\b",
        r"Record<\s*string\s*,\s*any\s*>",
    )
)


def is_excluded(rel: str) -> bool:
    """按相对路径判断文件是否在统计口径之外。"""
    parts = Path(rel).parts
    name = parts[-1].lower()
    # 测试文件名：*.test.* / *.spec.* / *_test.*
    if any(marker in name for marker in TEST_NAME_MARKERS):
        return True
    # 测试/生成目录：路径中任意中间目录命中即排除
    return any(part in EXCLUDED_DIR_NAMES for part in parts[:-1])


def iter_scan_files():
    """遍历统计范围内的源码文件，产出 (相对路径 posix, 绝对路径)。"""
    for rel_root, exts in SCAN_ROOTS:
        root = REPO_ROOT / rel_root
        if not root.is_dir():
            continue
        # os.walk 自顶向下剪枝，避免进入 node_modules 等大目录
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.suffix.lower() not in exts:
                    continue
                rel = path.relative_to(REPO_ROOT).as_posix()
                if is_excluded(rel):
                    continue
                yield rel, path


def count_line(line: str) -> int:
    """统计单行显式 any 命中数：先收集各模式命中区间，行内重叠去重。

    同一行同一处（区间重叠）的多个模式命中只计一次。
    """
    spans: list[tuple[int, int]] = []
    for pattern in ANY_PATTERNS:
        spans.extend(match.span() for match in pattern.finditer(line))
    if not spans:
        return 0
    spans.sort()
    count = 0
    merged_end = -1
    for start, end in spans:
        if start < merged_end:
            continue  # 与前序命中重叠：同一处，不重复计数
        count += 1
        merged_end = end
    return count


def count_file(path: Path) -> int:
    """统计单个文件的显式 any 数（按行扫描）。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(count_line(line) for line in text.splitlines())


def measure() -> tuple[int, dict[str, int]]:
    """全量测量：返回 (total, by_file)，by_file 按 count 降序排列。"""
    by_file: dict[str, int] = {}
    for rel, path in iter_scan_files():
        hits = count_file(path)
        if hits:
            by_file[rel] = hits
    ordered = dict(sorted(by_file.items(), key=lambda item: (-item[1], item[0])))
    return sum(ordered.values()), ordered


def load_baseline() -> dict:
    if BASELINE.is_file():
        try:
            return json.loads(BASELINE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def cmd_check(total: int, by_file: dict[str, int]) -> int:
    base = load_baseline()
    floor = base.get("any_count")
    if floor is None:
        print(f"ERROR: 缺基线 {BASELINE}（或缺 any_count 字段）", file=sys.stderr)
        return 2
    print(f"[ts-any] 前端显式 any 当前={total}（棘轮基线 {floor}，只减不增）")
    if total > int(floor):
        print(
            f"FAIL: any 计数回增 {total - floor} 处（{floor} -> {total}）。"
            "类型来源优先 gen:items 生成的 API 类型，禁止新增显式 any。",
            file=sys.stderr,
        )
        # 基线仅存总量；此处列出当前计数最多的前 10 个文件作为新增来源定位
        print("当前 any 计数最多的前 10 个文件：", file=sys.stderr)
        for rel, hits in list(by_file.items())[:10]:
            print(f"  {hits:>5}  {rel}", file=sys.stderr)
        return 1
    if total < int(floor):
        print(f"[ts-any] 净减 {int(floor) - total} 处，可运行 --bump 把基线收至 {total}。")
    print("[ts-any] OK — 显式 any 未回增")
    return 0


def cmd_bump(total: int) -> int:
    base = load_baseline()
    floor = base.get("any_count")
    if floor is None:
        print(f"ERROR: 缺基线 {BASELINE}（或缺 any_count 字段）", file=sys.stderr)
        return 2
    if total >= int(floor):
        print(f"[ts-any] 数量未减少（当前 {total}，基线 {floor}），基线不变。")
        return 0
    base["any_count"] = total
    base["updated"] = date.today().isoformat()
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(
        json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[ts-any] 基线已下调 {floor} -> {total}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="门禁：超过基线则退出 1")
    mode.add_argument("--bump", action="store_true", help="数量减少时下调基线（只降方向）")
    parser.add_argument("--json", action="store_true", help='输出 {"total":N,"by_file":{...}}')
    parser.add_argument("--top", type=int, default=0, metavar="N", help="显示前 N 个文件")
    args = parser.parse_args(argv)

    try:
        total, by_file = measure()
    except OSError as exc:
        print(f"[ts-any] ERROR: 测量失败: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"total": total, "by_file": by_file}, ensure_ascii=False))
        return 0
    if args.check:
        return cmd_check(total, by_file)
    if args.bump:
        return cmd_bump(total)

    # 默认：打印当前值与基线 + top N 文件
    base = load_baseline()
    floor = base.get("any_count", "?")
    print(f"[ts-any] 前端显式 any 当前={total}（基线 {floor}）")
    top = args.top if args.top > 0 else 10
    for rel, hits in list(by_file.items())[:top]:
        print(f"  {hits:>5}  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
