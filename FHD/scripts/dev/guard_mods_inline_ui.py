"""
``mods/*/frontend/views/**`` 内联 UI 体量守卫。

背景
----
各 mod 自带一套 vue 视图，重复内联 ``<style>`` 与 UI 原语（数据表/弹窗/按钮/状态标签等）。
宿主前端 ``frontend/src/components/`` 已有共享原语（DataTable / Modal / ConfirmDialog /
InputDialog / AppDialogHost / PaneResizeHandle 等），mods 视图可通过 ``@/...`` 别名导入复用。
本脚本用于量化和提醒"内联样式体量过大"的视图，引导逐步迁移到宿主原语。

行为
----
扫描 ``mods/*/frontend/views/**/*.vue``，统计每个视图：

- 非空 ``<style>`` 块数量（含 ``scoped`` 与普通块）
- 非空样式行数（块内非空、非纯注释行）

- 默认模式：输出 ``::warning::``（GitHub Actions 注解）提醒内联样式体量超过阈值的视图，退出码 0。
- ``--report``：输出各视图内联样式体量排行（不检查阈值）。
- ``--check``：对超过阈值的视图输出警告（**不阻断**，仅供 review 提示），退出码恒为 0。

用法：:

    python scripts/dev/guard_mods_inline_ui.py
    python scripts/dev/guard_mods_inline_ui.py --report
    python scripts/dev/guard_mods_inline_ui.py --check
    python scripts/dev/guard_mods_inline_ui.py --threshold 300
    python scripts/dev/guard_mods_inline_ui.py --repository-root <FHD>

退出码：恒为 ``0``（本守卫仅提醒，不接入失败门禁）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 默认内联样式体量提醒阈值（单文件非空 style 行数）。
DEFAULT_THRESHOLD = 300

_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL)
_EMPTY_OR_COMMENT_LINE_RE = re.compile(r"^\s*(/\*.*?\*/\s*)?$")


def _iter_view_files(repo_root: Path) -> list[Path]:
    views_root = repo_root / "mods"
    if not views_root.is_dir():
        return []
    return sorted(p for p in views_root.glob("*/frontend/views/**/*.vue") if p.is_file())


def _count_style_blocks(source: str) -> int:
    return len(_STYLE_BLOCK_RE.findall(source))


def _count_style_lines(source: str) -> int:
    """统计所有 <style> 块内的非空、非纯注释行数。"""
    total = 0
    for body in _STYLE_BLOCK_RE.findall(source):
        for line in body.splitlines():
            if not line.strip():
                continue
            if _EMPTY_OR_COMMENT_LINE_RE.match(line):
                continue
            total += 1
    return total


def _relative(repo_root: Path, file: Path) -> str:
    try:
        return file.relative_to(repo_root).as_posix()
    except ValueError:
        return file.as_posix()


def scan(repo_root: Path) -> list[tuple[Path, int, int]]:
    """返回 [(view_path, style_block_count, style_line_count), ...]，按样式行数降序。"""
    results: list[tuple[Path, int, int]] = []
    for f in _iter_view_files(repo_root):
        source = f.read_text(encoding="utf-8", errors="replace")
        results.append((f, _count_style_blocks(source), _count_style_lines(source)))
    results.sort(key=lambda t: t[2], reverse=True)
    return results


def _report(repo_root: Path, results: list[tuple[Path, int, int]]) -> None:
    print("[guard-mods-inline-ui] views_root=mods/*/frontend/views")
    print(
        f"[guard-mods-inline-ui] {len(results)} 个 .vue 视图，按非空 <style> 行数排行（块数 / 行数）："
    )
    for f, blocks, lines in results:
        print(f"  {_relative(repo_root, f):<72} blocks={blocks:<3} lines={lines}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="检查模式：对内联样式体量超过阈值的视图输出 ::warning::（不阻断，退出码恒为 0）",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="输出各视图内联样式体量排行（不检查阈值）",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"内联样式行数提醒阈值（默认 {DEFAULT_THRESHOLD}）",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="仓库根（默认自动推断为 FHD）",
    )
    args = parser.parse_args(argv)

    repo_root: Path = args.repository_root
    if not (repo_root / "mods").is_dir():
        print(f"ERROR: mods 目录不存在: {repo_root / 'mods'}", file=sys.stderr)
        return 2

    results = scan(repo_root)

    if args.report:
        _report(repo_root, results)
        return 0

    over = [t for t in results if t[2] > args.threshold]
    if not over:
        print(
            f"[guard-mods-inline-ui] OK — 无视图内联样式行数超过阈值 {args.threshold}"
            f"（共 {len(results)} 个视图）"
        )
        return 0

    for f, blocks, lines in over:
        rel = _relative(repo_root, f)
        print(
            f"::warning::[guard-mods-inline-ui] {rel} 内联样式体量偏大"
            f"（{lines} 行 / {blocks} 块，阈值 {args.threshold}），建议复用宿主共享原语"
        )

    print(
        f"[guard-mods-inline-ui] {len(over)} 个视图内联样式体量超过阈值 {args.threshold}"
        "（--check 仅提醒，不失败）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())