#!/usr/bin/env python3
"""统一 changed-path 分类器（change classifier · SSOT）。

**唯一职责**：把「一次 PR/推送改了哪些路径」翻译成各检查的 run/skip 决策。
所有 workflow（CI / macOS / Windows / mobile / Nightly）必须调用本脚本，**禁止**再在
各 workflow 的 YAML 里各写一套 bash 正则（那正是要消灭的重复与漂移源）。

用法（workflow 内，PR 上下文）::

    - id: paths
      if: github.event_name == 'pull_request'
      working-directory: .            # 视 workflow 默认目录而定
      run: python scripts/dev/change_classifier.py --category backend --base "${{ github.event.pull_request.base.sha }}" --head "${{ github.event.pull_request.head.sha }}"

随后用 ``if: steps.paths.outputs.run != 'false'`` 守卫重活步骤：
- 检测步骤被跳过（push/schedule/dispatch）→ ``run`` 为空 → 步骤照常执行（全量）。
- PR 命中/未命中 → ``run=true|false``。

决策语义（两类）：
  * ``skip_if_all_irrelevant``（backend / frontend / release）：
    仅当**所有**改动都落在该检查的「无关目录」时才 ``run=false``；出现任何
    无法归类或相关的文件即 ``run=true``（**fail-open**，宁多跑不漏跑）。
  * ``run_if_any_relevant``（codeql_python / codeql_javascript / macos /
    windows / mobile / docs / runtime_contract）：仅当**存在**命中相关
    glob 的改动时才 ``run=true``。

任何 spec 都可带 ``exclude_*``（与 ``prefixes`` / ``suffixes`` / ``contains`` 一一对应）：
命中 exclude 的路径**不算**该分类的相关改动。用于「Windows 专属产物不得算作 macOS
改动」这类跨平台互斥——保证 **Windows 改动不会拉起 macOS 重测试**（反之亦然）。
exclude 只影响 ``run_if_any_relevant`` 的相关性判定，不改变 fail-open 口径。

任何异常（取不到 diff、参数缺失、非 PR）一律 ``run=true``，绝不因分类器自身
问题而漏跑检查。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# —— SSOT：目录前缀 / 文件名后缀 规则。改这里即改全局，workflow 无需改动 ——
IRRELEVANT = {
    "backend": {
        "prefixes": [
            "docs/",
            "FHD/docs/",
            "FHD/frontend/",
            "FHD/admin-console/",
            "成都修茈科技有限公司/",
            "FHD/mobile-flutter-poc/",
            "FHD/desktop/",
            "FHD/desktop-shell/",
            "FHD/tools/",
            "FHD/package/",
            "FHD/scripts/package/",
        ],
        "suffixes": [".md"],
        # 只放行经命名规则约束的只读历史快照；其他 metrics 文件仍触发完整测试。
        "regexes": [
            r"FHD/metrics/dora-[0-9]{8}\.json",
            r"FHD/metrics/slo-production/[0-9]{8}T[0-9]{6}Z-[0-9]+-[0-9]+\.json",
        ],
    },
    "frontend": {
        "prefixes": [
            "docs/",
            "FHD/docs/",
            "FHD/app/",
            "FHD/tests/",
            "FHD/alembic/",
            "FHD/config/",
            "成都修茈科技有限公司/",
            "FHD/mobile-flutter-poc/",
            "FHD/desktop/",
            "FHD/desktop-shell/",
            "FHD/tools/",
            "FHD/package/",
            "FHD/scripts/package/",
        ],
        "suffixes": [".md"],
        # 只放行经命名规则约束的只读历史快照；其他 metrics 文件仍触发完整测试。
        "regexes": [
            r"FHD/metrics/dora-[0-9]{8}\.json",
            r"FHD/metrics/slo-production/[0-9]{8}T[0-9]{6}Z-[0-9]+-[0-9]+\.json",
        ],
    },
}
# release-gate 与 backend 同域（都是 FHD 后端发布契约）。
IRRELEVANT["release"] = IRRELEVANT["backend"]

RELEVANT = {
    "codeql_python": {
        "prefixes": [".github/codeql/"],
        "suffixes": [".py", ".pyi"],
        "exact": [".github/workflows/codeql.yml"],
        "contains": ["requirements", "pyproject.toml"],
    },
    "codeql_javascript": {
        "prefixes": [".github/codeql/", "FHD/frontend/", "FHD/admin-console/"],
        "suffixes": [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue"],
        "exact": [".github/workflows/codeql.yml"],
        "contains": ["package.json", "package-lock.json"],
    },
    # macOS 专项重检查（desktop/runtime、updater、打包脚本、签名/公证、安装包/OTA）。
    # exclude_*：Windows 专属产物（.ps1、windows/win32 命名、Authenticode）不算 macOS 改动。
    "macos": {
        "prefixes": [
            "FHD/desktop/",
            "FHD/desktop-shell/",
            "FHD/package/",
            "FHD/scripts/package/",
            "FHD/scripts/deploy/",
            "FHD/scripts/autonomy/",
            "FHD/tools/",
        ],
        "suffixes": [".entitlements", ".plist"],
        "exact": [
            ".github/workflows/desktop-macos-smoke.yml",
            ".github/workflows/fhd-mac-control-contract.yml",
            ".github/workflows/fhd-release-desktop.yml",
            ".github/workflows/fhd-release-desktop-mac-ota.yml",
            ".github/workflows/fhd-sign-and-publish-testing-feed.yml",
            ".github/workflows/fhd-publish-macos-download-center.yml",
            ".github/workflows/fhd-publish-local-mac-feed.yml",
            ".github/workflows/fhd-desktop-manifest-drift-check.yml",
            ".github/workflows/fhd-release-orchestrator.yml",
        ],
        "contains": ["updater", "notariz", "codesign", "signing"],
        "exclude_contains": ["windows", "win32", "authenticode"],
        "exclude_suffixes": [".ps1"],
    },
    # Windows 专属检查（打包/发布脚本、electron-builder 签名钩子、安装包证据）。
    "windows": {
        "prefixes": ["FHD/desktop/build/"],
        "suffixes": [".ps1"],
        "exact": [".github/workflows/fhd-ci-cd.yml"],
        "contains": ["windows", "win32", "authenticode"],
    },
    # 移动端（Flutter 唯一交付主线）。
    "mobile": {
        "prefixes": ["FHD/mobile-flutter-poc/", "FHD/mobile/"],
        "suffixes": [".dart"],
        "exact": [".github/workflows/fhd-ci-mobile-flutter.yml"],
        "contains": ["flutter"],
    },
    # 文档改动（docs-only PR 的显式口径；也可给纯文档检查做正向门）。
    "docs": {
        "prefixes": ["docs/", "FHD/docs/"],
        "suffixes": [".md", ".mdx", ".rst"],
        "exact": [],
        "contains": [],
    },
    "runtime_contract": {
        "prefixes": [
            "FHD/scripts/autonomy/runtime_tools/",
            "FHD/app/application/shipment_excel_etl_security.py",
            "FHD/tests/test_application/test_shipment_excel_etl_production_ready.py",
        ],
        "suffixes": [],
        "exact": [".github/workflows/fhd-mac-control-contract.yml"],
        "contains": [],
    },
}

CATEGORY_MODE = {
    "backend": "skip_if_all_irrelevant",
    "frontend": "skip_if_all_irrelevant",
    "release": "skip_if_all_irrelevant",
    "codeql_python": "run_if_any_relevant",
    "codeql_javascript": "run_if_any_relevant",
    "macos": "run_if_any_relevant",
    "windows": "run_if_any_relevant",
    "mobile": "run_if_any_relevant",
    "docs": "run_if_any_relevant",
    "runtime_contract": "run_if_any_relevant",
}


def _changed_files(base: str, head: str) -> list[str]:
    """返回 base..head 间改动文件（仓库根相对路径）。取不到则返回 []。"""
    # 保留重命名的旧路径删除，避免业务文件移入快照白名单后漏跑原所属检查。
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--no-renames", "--name-only", base, head],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _matches(path: str, spec: dict) -> bool:
    if path in spec.get("exact", ()):
        return True
    if any(path.startswith(p) for p in spec.get("prefixes", ())):
        return True
    if any(path.endswith(s) for s in spec.get("suffixes", ())):
        return True
    if any(re.fullmatch(pattern, path) for pattern in spec.get("regexes", ())):
        return True
    return any(c in path for c in spec.get("contains", ()))


def _excluded(path: str, spec: dict) -> bool:
    """命中 exclude_* 的路径不算该分类的相关改动（跨平台互斥）。"""
    if any(path.startswith(p) for p in spec.get("exclude_prefixes", ())):
        return True
    if any(path.endswith(s) for s in spec.get("exclude_suffixes", ())):
        return True
    return any(c in path for c in spec.get("exclude_contains", ()))


def decide(category: str, changed: list[str]) -> bool:
    """返回该检查是否应执行重活。fail-open：无改动/非 PR → True。"""
    mode = CATEGORY_MODE.get(category)
    if mode is None:
        raise SystemExit(f"unknown category: {category}")
    if not changed:
        return True  # 非 PR 或取不到 diff → 跑全量
    if mode == "run_if_any_relevant":
        spec = RELEVANT[category]
        return any(_matches(p, spec) and not _excluded(p, spec) for p in changed)
    spec = IRRELEVANT[category]
    return not all(_matches(p, spec) for p in changed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--category", choices=sorted(CATEGORY_MODE))
    scope.add_argument(
        "--all", action="store_true", help="一次读取 diff 并输出全部分类"
    )
    parser.add_argument("--base", default="", help="base SHA/ref（PR 用 base.sha）")
    parser.add_argument("--head", default="", help="head SHA/ref（PR 用 head.sha）")
    parser.add_argument("--json", action="store_true", help="打印机器可读结果")
    parser.add_argument("--source-sha", default="", help="核对实际 checkout 的源码 SHA")
    parser.add_argument("--report", type=Path, help="保存分类及源码身份 JSON")
    args = parser.parse_args(argv)
    if args.source_sha and not args.all:
        parser.error("--source-sha requires --all")

    changed = _changed_files(args.base, args.head) if args.base and args.head else []
    if args.all:
        source = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if args.source_sha and source != args.source_sha:
            parser.error("classification source SHA differs from the tested checkout")
        decisions = {category: decide(category, changed) for category in CATEGORY_MODE}
        report = {
            "schema": 1,
            "source_sha": source,
            "base_sha": args.base,
            "pr_head_sha": args.head,
            "run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
            "changed_count": len(changed),
            "decisions": decisions,
            "reason": "changed_paths"
            if changed
            else "empty_or_unavailable_diff_run_all",
        }
        outputs = {"valid": "true", "source_sha": source}
        for category, run in decisions.items():
            outputs[category] = str(run).lower()
            outputs[f"{category}_skip"] = str(not run).lower()
    else:
        run = decide(args.category, changed)
        report = {"category": args.category, "run": run, "changed_count": len(changed)}
        outputs = {"run": str(run).lower(), "skip": str(not run).lower()}

    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded + "\n", encoding="utf-8")
    if args.json or args.all:
        print(encoded)

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            for key, value in outputs.items():
                fh.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
