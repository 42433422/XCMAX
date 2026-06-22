#!/usr/bin/env python3
"""version 域 sync 脚本：从 VERSION.md 派生版本号到所有锚点文件。

与 verify_version_anchors.py 共享 ANCHORS 列表，保证"检测的锚点 = 同步的锚点"。

用法:
  python scripts/dev/version_sync.py             # dry-run：打印将改的文件，不写盘
  python scripts/dev/version_sync.py --apply     # 真写
  python scripts/dev/version_sync.py --version 10.0.1 --apply  # 指定版本（默认从 VERSION.md 读）

退出码: 0=一致/已同步 1=有改动需写盘（dry-run） 2=配置错误 3=执行错误
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# 复用 verify_version_anchors.py 的锚点定义，保证 check/sync 同源
from scripts.dev.verify_version_anchors import (  # noqa: E402
    ANCHORS,
    _canonical_version,
)


def _replace_version_in_text(text: str, pattern: str, new_version: str) -> tuple[str, bool]:
    """用正则把匹配到的版本号替换为 new_version，保留前后缀。

    只替换第一个匹配（count=1），与 verify_version_anchors.py 的 re.search 行为一致，
    避免 `python_version = "3.11"` 被 `version = "..."` pattern 误匹配。
    返回 (新文本, 是否有改动)。
    """
    changed = False

    def _repl(m: re.Match) -> str:
        nonlocal changed
        old = m.group(1)
        if old == new_version:
            return m.group(0)
        changed = True
        # 把 group(1) 替换为新版本，保留 group(0) 的前后缀
        return m.group(0).replace(old, new_version)

    new_text = re.sub(pattern, _repl, text, count=1)
    return new_text, changed


def sync(apply: bool, override_version: str | None = None) -> int:
    """执行同步。

    apply=True 真写盘，apply=False 只打印将做的改动。
    override_version 指定时跳过 VERSION.md 解析（慎用）。
    """
    if override_version:
        canonical = override_version
    else:
        try:
            canonical = _canonical_version()
        except (FileNotFoundError, ValueError) as e:
            print(f"错误：无法解析 VERSION.md 的 canonical version：{e}", file=sys.stderr)
            return 2

    print(f"目标版本：{canonical}（来源：{'--version' if override_version else 'VERSION.md'}）")
    print(f"模式：{'--apply（真写）' if apply else 'dry-run（不写盘）'}")
    print("-" * 60)

    changes: list[str] = []
    errors: list[str] = []
    for rel_path, pattern in ANCHORS:
        full_path = REPO_ROOT / rel_path
        if not full_path.is_file():
            errors.append(f"{rel_path}: 文件不存在")
            continue
        try:
            text = full_path.read_text(encoding="utf-8")
        except OSError as e:
            errors.append(f"{rel_path}: 读取失败 {e}")
            continue

        new_text, changed = _replace_version_in_text(text, pattern, canonical)
        if not changed:
            print(f"  ✓ {rel_path}: 已是 {canonical}")
            continue
        changes.append(rel_path)
        if apply:
            try:
                full_path.write_text(new_text, encoding="utf-8")
                print(f"  ✏ {rel_path}: 已写入 {canonical}")
            except OSError as e:
                errors.append(f"{rel_path}: 写入失败 {e}")
        else:
            print(f"  ! {rel_path}: 将改为 {canonical}")

    print("-" * 60)
    if errors:
        print(f"错误（{len(errors)}）：")
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 3

    if not changes:
        print(f"✓ 所有 {len(ANCHORS)} 个锚点均已同步到 {canonical}")
        return 0

    if apply:
        print(f"✓ 已同步 {len(changes)} 个文件到 {canonical}")
        return 0
    print(f"! {len(changes)} 个文件待同步（dry-run，未写盘。加 --apply 真写。）")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从 VERSION.md 派生版本号到所有锚点文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="真写（默认 dry-run）")
    parser.add_argument(
        "--version",
        help="指定版本号（默认从 VERSION.md 解析；慎用，可能造成与 SSOT 不一致）",
    )
    args = parser.parse_args(argv)
    return sync(apply=args.apply, override_version=args.version)


if __name__ == "__main__":
    raise SystemExit(main())
