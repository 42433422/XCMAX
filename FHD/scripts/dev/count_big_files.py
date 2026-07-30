#!/usr/bin/env python3
"""巨型文件棘轮（ratchet）：只减不增地收口 FHD/app 大文件债务。

守护两条基线（配合 architecture/REFACTOR_DECOMPOSITION_PLAN.md）：

1. ``app/**/*.py`` 行数 > ``file_lines_soft_cap``（默认 800）的文件 —— 巨型文件**不得新增或增长**。
   新代码应按职责拆分（router 拆 domain、app_service 拆 helper、巨型 schema 拆子模块）。
2. 单文件 ``@router.`` 装饰器数 > ``routes_per_file_soft_cap``（默认 20）的文件 ——
   路由数**不得增长**，并应聚合到 domain 子模块（绞杀者式收口）。

白名单在 ``scripts/dev/big_files_ratchet_baseline.json`` 的 ``allowlist`` 中维护，
典型场景：纯数据 schema、生成产物、bootstrap DDL 等天然不可拆的巨型文件。

用法::

    python scripts/dev/count_big_files.py                    # 校验（CI，exit 1 on violation）
    python scripts/dev/count_big_files.py --json             # JSON 输出
    python scripts/dev/count_big_files.py --top 10           # 列出 Top N 待拆分文件
    python scripts/dev/count_big_files.py --update-baseline  # 收口后锁定新基线（只降）
    python scripts/dev/count_big_files.py --update-baseline --force   # 强制更新（不推荐）

退出码：违规 ``1`` / 正常 ``0`` / 用法错 ``2``。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT_DEFAULT = Path(__file__).resolve().parents[2]
BASELINE_REL = Path("scripts") / "dev" / "big_files_ratchet_baseline.json"
APP_REL = Path("app")

ROUTER_PATTERN = re.compile(r"@router\.(get|post|put|delete|patch|websocket)\b", re.MULTILINE)


def _rel(path: Path, repo_root: Path) -> str:
    return str(path.relative_to(repo_root)).replace("\\", "/")


def _is_allowlisted(rel: str, allowlist: list[str]) -> bool:
    return any(rel == suffix or rel.endswith(suffix) for suffix in allowlist)


def measure(repo_root: Path, allowlist: list[str], file_lines_cap: int, routes_cap: int) -> dict:
    """实测两个指标，返回结构化结果。"""
    app_dir = repo_root / APP_REL
    if not app_dir.is_dir():
        return {
            "big_files_over_cap": [],
            "big_router_files_over_cap": [],
            "big_files_count": 0,
            "big_router_count": 0,
            "max_file_lines": 0,
            "max_routes_per_file": 0,
        }

    big_files: list[dict] = []
    big_router_files: list[dict] = []
    max_lines = 0
    max_routes = 0

    for py in sorted(app_dir.rglob("*.py")):
        rel = _rel(py, repo_root)
        if "__pycache__" in rel or "/migrations/" in rel:
            continue
        if _is_allowlisted(rel, allowlist):
            continue

        try:
            content = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        if lines > file_lines_cap:
            big_files.append({"file": rel, "lines": lines})
        if lines > max_lines:
            max_lines = lines

        routes = len(ROUTER_PATTERN.findall(content))
        if routes > routes_cap:
            big_router_files.append({"file": rel, "routes": routes})
        if routes > max_routes:
            max_routes = routes

    return {
        "big_files_over_cap": sorted(big_files, key=lambda x: -x["lines"]),
        "big_router_files_over_cap": sorted(big_router_files, key=lambda x: -x["routes"]),
        "big_files_count": len(big_files),
        "big_router_count": len(big_router_files),
        "max_file_lines": max_lines,
        "max_routes_per_file": max_routes,
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
        "big_files_over_800_lines": current["big_files_count"],
        "big_router_files_over_20_routes": current["big_router_count"],
        "max_file_lines": current["max_file_lines"],
        "max_routes_per_file": current["max_routes_per_file"],
        "file_line_limits": {item["file"]: item["lines"] for item in current["big_files_over_cap"]},
        "router_route_limits": {
            item["file"]: item["routes"] for item in current["big_router_files_over_cap"]
        },
        "allowlist": baseline["allowlist"],
        "thresholds": baseline["thresholds"],
        "last_measured_commit": baseline.get("last_measured_commit", ""),
        "last_measured_date": baseline.get("last_measured_date", ""),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def evaluate(current: dict, baseline: dict) -> tuple[list[str], list[str]]:
    """返回 (errors, progress)。errors 非空即失败。"""
    errors: list[str] = []
    progress: list[str] = []

    file_limits = baseline.get("file_line_limits", {})
    current_files = {item["file"]: item["lines"] for item in current["big_files_over_cap"]}
    if file_limits:
        for rel, lines in current_files.items():
            limit = file_limits.get(rel)
            if limit is None:
                errors.append(
                    f"新增巨型文件：{rel}（{lines} > "
                    f"{baseline['thresholds']['file_lines_soft_cap']} 行）"
                )
            elif lines > limit:
                errors.append(f"巨型文件继续增长：{rel}（{limit} → {lines} 行）")
        removed = sorted(set(file_limits) - set(current_files))
        if removed:
            progress.append(f"app/ 巨型文件债务下降：移除 {len(removed)} 个基线项 ✓")
    elif current["big_files_count"] > baseline["big_files_over_800_lines"]:
        errors.append("app/ 巨型文件数增加；请生成逐文件 V2 基线。")

    route_limits = baseline.get("router_route_limits", {})
    current_routers = {
        item["file"]: item["routes"] for item in current["big_router_files_over_cap"]
    }
    if route_limits:
        for rel, routes in current_routers.items():
            limit = route_limits.get(rel)
            if limit is None:
                errors.append(
                    f"新增巨型 router：{rel}（{routes} > "
                    f"{baseline['thresholds']['routes_per_file_soft_cap']} 路由）"
                )
            elif routes > limit:
                errors.append(f"巨型 router 继续增长：{rel}（{limit} → {routes} 路由）")
        removed = sorted(set(route_limits) - set(current_routers))
        if removed:
            progress.append(f"app/ 巨型 router 债务下降：移除 {len(removed)} 个基线项 ✓")
    elif current["big_router_count"] > baseline["big_router_files_over_20_routes"]:
        errors.append("app/ 巨型 router 文件数增加；请生成逐文件 V2 基线。")

    return errors, progress


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出实测与判定")
    parser.add_argument("--top", type=int, metavar="N", help="列出 Top N 待拆分文件（按行数排序）")
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

    allowlist = baseline.get("allowlist", [])
    file_lines_cap = baseline["thresholds"]["file_lines_soft_cap"]
    routes_cap = baseline["thresholds"]["routes_per_file_soft_cap"]

    current = measure(repo_root, allowlist, file_lines_cap, routes_cap)

    if args.update_baseline:
        if not args.force:
            raising: list[str] = []
            if current["big_files_count"] > baseline["big_files_over_800_lines"]:
                raising.append("big_files_over_800_lines")
            if current["big_router_count"] > baseline["big_router_files_over_20_routes"]:
                raising.append("big_router_files_over_20_routes")
            for item in current["big_files_over_cap"]:
                old = baseline.get("file_line_limits", {}).get(item["file"])
                if baseline.get("file_line_limits") and old is None:
                    raising.append(f"new oversized file {item['file']}")
                elif old is not None and item["lines"] > old:
                    raising.append(f"{item['file']} lines")
            for item in current["big_router_files_over_cap"]:
                old = baseline.get("router_route_limits", {}).get(item["file"])
                if baseline.get("router_route_limits") and old is None:
                    raising.append(f"new oversized router {item['file']}")
                elif old is not None and item["routes"] > old:
                    raising.append(f"{item['file']} routes")
            if raising:
                print(
                    "拒绝调高基线（棘轮只减不增）："
                    + ", ".join(raising)
                    + "。如确需放宽请加 --force。",
                    file=sys.stderr,
                )
                return 2
        out = write_baseline(repo_root, baseline, current)
        print(f"[big-files-ratchet] 基线已写入 {out.relative_to(repo_root)}")
        print(f"[big-files-ratchet]   big_files_over_800_lines = {current['big_files_count']}")
        print(
            f"[big-files-ratchet]   big_router_files_over_20_routes = {current['big_router_count']}"
        )
        return 0

    if args.top is not None:
        n = args.top
        print(f"=== Top {n} 巨型文件（>{file_lines_cap} 行）===")
        for i, item in enumerate(current["big_files_over_cap"][:n], 1):
            print(f"{i:>3}. {item['lines']:>5} 行  {item['file']}")
        print(f"\n=== Top {n} 巨型 router 文件（>{routes_cap} 路由）===")
        for i, item in enumerate(current["big_router_files_over_cap"][:n], 1):
            print(f"{i:>3}. {item['routes']:>3} 路由  {item['file']}")
        return 0

    errors, progress = evaluate(current, baseline)

    if args.json:
        print(
            json.dumps(
                {
                    "current": {
                        "big_files_count": current["big_files_count"],
                        "big_router_count": current["big_router_count"],
                        "max_file_lines": current["max_file_lines"],
                        "max_routes_per_file": current["max_routes_per_file"],
                    },
                    "baseline": {
                        "big_files_over_800_lines": baseline["big_files_over_800_lines"],
                        "big_router_files_over_20_routes": baseline[
                            "big_router_files_over_20_routes"
                        ],
                    },
                    "errors": errors,
                    "progress": progress,
                    "ok": not errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if errors else 0

    print(f"[big-files-ratchet] repo={repo_root}")
    print(
        f"[big-files-ratchet] big files (>{file_lines_cap} lines): {current['big_files_count']} "
        f"(baseline {baseline['big_files_over_800_lines']})"
    )
    print(
        f"[big-files-ratchet] big router files (>{routes_cap} routes): {current['big_router_count']} "
        f"(baseline {baseline['big_router_files_over_20_routes']})"
    )
    print(
        f"[big-files-ratchet] max file lines: {current['max_file_lines']} | "
        f"max routes per file: {current['max_routes_per_file']}"
    )
    for p in progress:
        print(f"[big-files-ratchet] PROGRESS: {p}")
    if errors:
        print(f"[big-files-ratchet] {len(errors)} VIOLATION(S):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("[big-files-ratchet] OK — 巨型文件未增长")
    return 0


if __name__ == "__main__":
    sys.exit(main())
