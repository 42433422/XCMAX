#!/usr/bin/env python3
"""净删除棘轮门禁：全仓「代码 + 文档」总行数只减不增。

背景：仓库长期「只生成、不删除」，文档与代码持续膨胀，AI 读错与路径漂移随之增加。
本脚本把「每个迭代必须有净删除行数（代码和文档都算）」固化为一条棘轮：以
``FHD/metrics/line_baseline.json`` 记录全仓代码+文档总行数，门禁要求当前值
**不大于**基线，任何净增都会失败。

口径（可复核、确定性）：
  * 统计范围：``git ls-files`` 跟踪的「代码 + 文档」后缀文件（见 CODE_DOC_SUFFIXES）。
  * 排除：依赖锁文件、生成物、构建产物、依赖目录、指标/报告目录（见下方常量）。
  * 计数：按字节统计 ``\\n`` 数量（末行无换行则 +1），不做语义解析。

用法::

    python scripts/dev/check_net_deletion.py            # 门禁：当前必须 <= 基线
    python scripts/dev/check_net_deletion.py --json     # 机器可读输出
    python scripts/dev/check_net_deletion.py --update   # 棘轮下调基线（净删除后执行）
    python scripts/dev/check_net_deletion.py --update --force --reason "..."   # 显式抬升

退出码: 0=通过 1=净增（含 `--update` 试图抬升而未加 --force） 2=用法错。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent
BASELINE = FHD_ROOT / "metrics" / "line_baseline.json"

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2

# 「代码 + 文档」= 会被人工审阅、需要维护的行数。
CODE_DOC_SUFFIXES = {
    # 文档
    ".md", ".mdx", ".rst", ".txt", ".adoc",
    # 代码
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte",
    ".java", ".kt", ".kts", ".dart", ".go", ".rs", ".rb", ".php", ".cs", ".swift",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".scala", ".m", ".mm",
    # 脚本 / 配置 / SQL
    ".sh", ".bash", ".zsh", ".ps1", ".sql", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".json",
}

DOC_SUFFIXES = {".md", ".mdx", ".rst", ".adoc"}

# 依赖目录 / 构建产物 / 虚拟环境：非人工维护代码。
SKIP_DIR_NAMES = {
    "node_modules", "dist", "build", "coverage", "htmlcov", ".venv", "venv",
    "__pycache__", ".next", ".nuxt", ".dart_tool", "Pods", "DerivedData",
    "site-packages", "vendor", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

# 锁文件与生成物：由工具产出，不应计入人工维护行数。
SKIP_FILE_NAMES = {
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "uv.lock", "Gemfile.lock", "Cargo.lock", "composer.lock",
    "Pipfile.lock", "flake.lock",
}

# 指标 / 遥测 / 报告目录：随 CI 与运行时持续追加，非代码或文档。
SKIP_PATH_PREFIXES = (
    "FHD/metrics/", "metrics/", "reports/", "test_reports/", "FHD/reports/",
    # 以下为生成物 / 第三方 / dump，非人工维护，逐项说明：
    "FHD/third_party/",                          # vendored 第三方源码
    "FHD/docs/legal/",                           # 软著申请用的整份源码 dump
    "FHD/contracts/",                            # 由 schema 生成的契约快照
    "FHD/dataset_rag/",                          # 数据集文件
    "成都修茈科技有限公司/corp-butler/assets/",    # 前端打包产物
)

# 生成物横幅：文件头部声明自动生成即不计入。
GENERATED_BANNER_RE = re.compile(
    r"(DO NOT EDIT|auto-?generated|@generated|自动生成|代码生成|此文件由.*生成)",
    re.IGNORECASE,
)
_BANNER_BYTES = 2048


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _tracked_files() -> list[str]:
    return [p for p in _git("ls-files", "-z").split("\0") if p]


def _is_counted(rel: str) -> bool:
    if any(rel.startswith(pref) for pref in SKIP_PATH_PREFIXES):
        return False
    name = Path(rel).name
    if name.lower().startswith("."):
        return False
    if ".generated." in rel or name in SKIP_FILE_NAMES:
        return False
    if Path(rel).suffix.lower() not in CODE_DOC_SUFFIXES:
        return False
    return not any(seg in SKIP_DIR_NAMES for seg in rel.split("/")[:-1])


def _count_lines(abs_path: Path) -> int:
    try:
        data = abs_path.read_bytes()
    except OSError:
        return 0
    if not data:
        return 0
    return data.count(b"\n") + (1 if not data.endswith(b"\n") else 0)


def _has_generated_banner(abs_path: Path) -> bool:
    """文件头部声明「自动生成 / DO NOT EDIT」即视为生成物，不计入人工维护行数。"""
    try:
        with abs_path.open("rb") as fh:
            head = fh.read(_BANNER_BYTES)
    except OSError:
        return False
    try:
        text = head.decode("utf-8", errors="ignore")
    except (LookupError, ValueError):
        return False
    return GENERATED_BANNER_RE.search(text) is not None


def count_lines() -> tuple[int, int, dict[str, int]]:
    """返回 (总行数, 文档行数, 按顶层目录的行数拆解)。"""
    total = 0
    doc_lines = 0
    by_top: dict[str, int] = {}
    for rel in _tracked_files():
        if not _is_counted(rel):
            continue
        abs_path = REPO_ROOT / rel
        if _has_generated_banner(abs_path):
            continue
        n = _count_lines(abs_path)
        if n == 0:
            continue
        total += n
        if Path(rel).suffix.lower() in DOC_SUFFIXES:
            doc_lines += n
        top = rel.split("/")[0]
        by_top[top] = by_top.get(top, 0) + n
    return total, doc_lines, by_top


def _load_baseline() -> dict:
    if not BASELINE.is_file():
        raise SystemExit(f"缺少基线文件：{BASELINE}（先运行 --update 建立）")
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _write_baseline(lines: int, note: str) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(
        json.dumps(
            {"lines": lines, "updated": date.today().isoformat(), "note": note},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def cmd_check(as_json: bool) -> int:
    total, doc_lines, by_top = count_lines()
    base = _load_baseline()
    limit = int(base["lines"])
    delta = total - limit
    ok = delta <= 0

    if as_json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "current": total,
                    "baseline": limit,
                    "delta": delta,
                    "doc_lines": doc_lines,
                    "code_lines": total - doc_lines,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK if ok else EXIT_FAIL

    print(f"[net-deletion] 代码+文档 当前 {total} 行 / 基线 {limit} 行（差 {delta:+d}）")
    print(f"[net-deletion] 其中文档 {doc_lines} 行 / 代码 {total - doc_lines} 行")
    if ok:
        print(f"[net-deletion] OK：本迭代净删除 {-delta} 行（基线可下调 {total}）。")
        return EXIT_OK

    print("[net-deletion] 失败：净增了代码/文档行数。本迭代必须有净删除行数。")
    print("[net-deletion] 增量最大的顶层目录：")
    for top, n in sorted(by_top.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {top:<40} {n:>8} 行")
    print("[net-deletion] 处置：删除等量以上死代码/死文档，或（需评审可见）--update --force --reason。")
    return EXIT_FAIL


def cmd_update(force: bool, reason: str) -> int:
    total, _, _ = count_lines()
    if not BASELINE.is_file():
        _write_baseline(total, reason or "初始建立基线")
        print(f"[net-deletion] 已建立基线：{total} 行")
        return EXIT_OK
    base = int(_load_baseline()["lines"])
    if total <= base:
        _write_baseline(total, reason or "棘轮下调")
        print(f"[net-deletion] 基线下调：{base} → {total}（净删除 {base - total} 行）")
        return EXIT_OK
    if not force:
        print(
            f"[net-deletion] 拒绝抬升基线：当前 {total} > 基线 {base}（+{total - base} 行）。"
            "先净删除，或显式 --force --reason。",
            file=sys.stderr,
        )
        return EXIT_FAIL
    if not reason.strip():
        print("[net-deletion] --force 抬升必须给出 --reason。", file=sys.stderr)
        return EXIT_USAGE
    _write_baseline(total, reason.strip())
    print(f"[net-deletion] 基线抬升：{base} → {total}（+{total - base} 行）；原因：{reason.strip()}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--update", action="store_true", help="把基线棘轮下调到当前值")
    parser.add_argument("--force", action="store_true", help="允许抬升基线（必须配 --reason）")
    parser.add_argument("--reason", default="", help="抬升基线的理由")
    args = parser.parse_args(argv)

    if args.update:
        return cmd_update(args.force, args.reason)
    if args.force or args.reason:
        parser.error("--force/--reason 仅在 --update 时有效")
    return cmd_check(args.json)


if __name__ == "__main__":
    raise SystemExit(main())
