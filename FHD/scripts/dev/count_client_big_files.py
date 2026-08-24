#!/usr/bin/env python3
# mypy: disable-error-code="no-any-return"
"""客户端巨型文件棘轮（ratchet）：只减不增地收口 frontend / mobile 大文件债务。

后端 ``app/`` 已有 ``count_big_files.py`` + ``arch_fitness.py`` 双棘轮守护，
但前端与移动端长期无行数门禁。本脚本补齐客户端侧：

* 扫描 ``frontend/src/**/*.{ts,vue}``（排除 ``*.test.ts`` / ``*.spec.ts``）
  与 ``mobile-flutter-poc/lib/**/*.dart`` 的**生产源码**。
* 行数 > ``file_lines_soft_cap``（默认 1000）的文件不得新增或增长。
* 逐文件基线存于 ``scripts/dev/client_big_files_ratchet_baseline.json``，
  只降不升；收口拆分后运行 ``--update-baseline`` 锁定新基线。

用法::

    python scripts/dev/count_client_big_files.py                    # 校验（CI，exit 1 on violation）
    python scripts/dev/count_client_big_files.py --top 10           # 列出 Top N 待拆分文件
    python scripts/dev/count_client_big_files.py --update-baseline  # 收口后锁定新基线（只降）
    python scripts/dev/count_client_big_files.py --update-baseline --force  # 强制（不推荐）

退出码：违规 ``1`` / 正常 ``0`` / 用法错 ``2``。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT_DEFAULT = Path(__file__).resolve().parents[2]
BASELINE_REL = Path("scripts") / "dev" / "client_big_files_ratchet_baseline.json"

# 扫描范围：(相对目录, 后缀集合, 排除后缀)
SCAN_SPECS = [
    ("frontend/src", {".ts", ".vue"}, {".test.ts", ".spec.ts"}),
    ("mobile-flutter-poc/lib", {".dart"}, set()),
]


def _rel(path: Path, repo_root: Path) -> str:
    return str(path.relative_to(repo_root)).replace("\\", "/")


def _line_count(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
    except (OSError, UnicodeDecodeError):
        return 0


def measure(repo_root: Path, cap: int) -> dict:
    oversized: list[dict] = []
    max_lines = 0
    for rel_dir, suffixes, exclude_suffixes in SCAN_SPECS:
        root = repo_root / rel_dir
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            name = path.name
            if not any(name.endswith(s) for s in suffixes):
                continue
            if any(name.endswith(es) for es in exclude_suffixes):
                continue
            rel = _rel(path, repo_root)
            if "__pycache__" in rel or "node_modules" in rel:
                continue
            lines = _line_count(path)
            if lines > cap:
                oversized.append({"file": rel, "lines": lines})
            if lines > max_lines:
                max_lines = lines
    return {
        "oversized": sorted(oversized, key=lambda x: -x["lines"]),
        "count": len(oversized),
        "max_lines": max_lines,
    }


def load_baseline(repo_root: Path) -> dict | None:
    path = repo_root / BASELINE_REL
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_baseline(repo_root: Path, baseline: dict, current: dict) -> Path:
    path = repo_root / BASELINE_REL
    payload = {
        "_note": baseline["_note"],
        "updated": current.get("_updated", baseline.get("updated", "")),
        "oversized_count": current["count"],
        "max_lines": current["max_lines"],
        "file_line_limits": {item["file"]: item["lines"] for item in current["oversized"]},
        "thresholds": baseline["thresholds"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def evaluate(current: dict, baseline: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    progress: list[str] = []
    limits = baseline.get("file_line_limits", {})
    cap = baseline["thresholds"]["file_lines_soft_cap"]
    current_files = {item["file"]: item["lines"] for item in current["oversized"]}
    for rel, lines in current_files.items():
        limit = limits.get(rel)
        if limit is None:
            errors.append(f"新增巨型客户端文件：{rel}（{lines} > {cap} 行）")
        elif lines > limit:
            errors.append(f"巨型客户端文件继续增长：{rel}（{limit} → {lines} 行）")
    removed = sorted(set(limits) - set(current_files))
    if removed:
        progress.append(f"客户端巨型文件债务下降：移除 {len(removed)} 个基线项 ✓")
    return errors, progress


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--top", type=int, metavar="N", help="列出 Top N 待拆分文件")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="把当前实测写为新基线（默认只允许调低；升高需 --force）",
    )
    parser.add_argument("--force", action="store_true", help="允许 --update-baseline 调高基线")
    parser.add_argument(
        "--repo-root", type=Path, default=REPO_ROOT_DEFAULT, help="仓库根（默认自动推断）"
    )
    args = parser.parse_args(argv)

    repo_root: Path = args.repo_root
    if not repo_root.is_dir():
        print(f"ERROR: repo root not a directory: {repo_root}", file=sys.stderr)
        return 2

    baseline = load_baseline(repo_root)
    if baseline is None:
        print(
            f"ERROR: 基线缺失：{BASELINE_REL}。先运行 --update-baseline 生成。",
            file=sys.stderr,
        )
        return 2

    cap = baseline["thresholds"]["file_lines_soft_cap"]
    current = measure(repo_root, cap)

    if args.update_baseline:
        if not args.force:
            raising: list[str] = []
            limits = baseline.get("file_line_limits", {})
            for item in current["oversized"]:
                old = limits.get(item["file"])
                if limits and old is None:
                    raising.append(f"new oversized file {item['file']}")
                elif old is not None and item["lines"] > old:
                    raising.append(f"{item['file']} lines")
            if raising:
                print(
                    "拒绝调高基线（棘轮只减不增）："
                    + ", ".join(raising)
                    + "。如确需放宽请加 --force。",
                    file=sys.stderr,
                )
                return 2
        out = write_baseline(repo_root, baseline, current)
        print(f"[client-big-files] 基线已写入 {out.relative_to(repo_root)}")
        print(f"[client-big-files]   oversized_count = {current['count']}")
        return 0

    if args.top is not None:
        print(f"=== Top {args.top} 巨型客户端文件（>{cap} 行）===")
        for i, item in enumerate(current["oversized"][: args.top], 1):
            print(f"{i:>3}. {item['lines']:>5} 行  {item['file']}")
        return 0

    errors, progress = evaluate(current, baseline)
    print(f"[client-big-files] repo={repo_root}")
    print(
        f"[client-big-files] oversized (>{cap} lines): {current['count']} "
        f"(baseline {baseline['oversized_count']})"
    )
    print(f"[client-big-files] max lines: {current['max_lines']}")
    for p in progress:
        print(f"[client-big-files] PROGRESS: {p}")
    if errors:
        print(f"[client-big-files] {len(errors)} VIOLATION(S):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("[client-big-files] OK — 客户端巨型文件未增长")
    return 0


if __name__ == "__main__":
    sys.exit(main())
