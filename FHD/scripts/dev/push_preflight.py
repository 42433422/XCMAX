#!/usr/bin/env python3
"""修复代理 push / 开 PR 前的便宜自检：CHANGELOG Unreleased、能力中心漂移、净删除。

只复用 CI 已有门禁的同一口径（changelog-gate 路径表、build_capability_center --check、
check_net_deletion），约 10 秒出结论，避免推完才在 CI 红。先 commit 再在 FHD/ 下运行::

    python scripts/dev/push_preflight.py          # 只检查
    python scripts/dev/push_preflight.py --fix    # 能力中心漂移时就地重生成（之后须 commit）

退出码：0=可以 push；1=有项未过（按提示处理后重跑）；2=用法或环境错误。
净增时按仓库惯例显式 --update --force --reason 并随 PR 提交；本脚本不替你抬基线，
只拦截没写新原因的静默抬升。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent
GATE_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "fhd-changelog-gate.yml"
)  # CI 实际运行的根仓副本
CHANGELOG = "FHD/CHANGELOG.md"
BASELINE = "FHD/metrics/line_baseline.json"
CAPABILITY_BUILDER = REPO_ROOT / "成都修茈科技有限公司" / "scripts" / "build_capability_center.py"
CAPABILITY_OUTPUTS = (
    "成都修茈科技有限公司/capabilities",
    "成都修茈科技有限公司/data/capabilities.json",
)


def _git(*args: str) -> str:
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"[preflight] git {' '.join(args)} 失败：{proc.stderr.strip()}")
    return proc.stdout


def product_patterns(workflow_text: str) -> list[str]:
    """fhd-changelog-gate.yml 的 pull_request.paths，与 CI 同口径。"""
    return re.findall(r'^\s+-\s+"(FHD/[^"]+)"\s*$', workflow_text, re.M)


def unreleased_range(changelog_text: str) -> tuple[int, int] | None:
    """「## Unreleased」节的 1 起始行号区间（含首尾）；没有该节返回 None。"""
    lines = changelog_text.splitlines()
    start = next((i for i, ln in enumerate(lines, 1) if ln.startswith("## Unreleased")), None)
    if start is None:
        return None
    end = next(
        (i - 1 for i, ln in enumerate(lines, 1) if i > start and ln.startswith("## ")), len(lines)
    )
    return start, end


def added_line_numbers(diff_u0: str) -> list[int]:
    """从 `git diff -U0` 输出取新增的非空行在新文件中的行号。"""
    numbers: list[int] = []
    current = 0
    for ln in diff_u0.splitlines():
        hunk = re.match(r"^@@ -\S+ \+(\d+)(?:,\d+)? @@", ln)
        if hunk:
            current = int(hunk.group(1))
        elif ln.startswith("+") and not ln.startswith("+++"):
            if ln[1:].strip():
                numbers.append(current)
            current += 1
    return numbers


def check_changelog(base: str, branch: str) -> tuple[bool, str]:
    if branch.startswith("autonomy/"):
        return True, "autonomy/* 分支豁免（与 CI 一致）"
    patterns = product_patterns(GATE_WORKFLOW.read_text(encoding="utf-8"))
    changed = [p for p in _git("diff", "--name-only", base).splitlines() if p]
    product = [p for p in changed if any(fnmatch(p, pat) for pat in patterns)]
    if not product:
        return True, "未改产品代码路径，不要求 CHANGELOG"
    span = unreleased_range((REPO_ROOT / CHANGELOG).read_text(encoding="utf-8"))
    added = added_line_numbers(_git("diff", "-U0", base, "--", CHANGELOG))
    if span and any(span[0] < n <= span[1] for n in added):
        return True, "CHANGELOG.md「## Unreleased」已有新增说明"
    return False, (
        f"改了产品代码（如 {product[0]}），但 {CHANGELOG} 的「## Unreleased」节没有新增说明："
        "补一行写给非技术读者的变更说明再 commit"
    )


def check_capability_center(fix: bool) -> tuple[bool, str]:
    def run(*extra: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(CAPABILITY_BUILDER), *extra]
        return subprocess.run(cmd, cwd=str(FHD_ROOT), capture_output=True, text=True)

    first = run("--check")
    if first.returncode == 0:
        return True, "能力中心页面与目录一致"
    detail = (first.stdout + first.stderr).strip().splitlines()[-1:] or ["无输出"]
    if not fix:
        return False, f"能力中心漂移（{detail[0]}）：加 --fix 重生成后 commit 这些页面"
    if run().returncode != 0 or run("--check").returncode != 0:
        return False, "能力中心重生成后仍不一致：多为证据缺失，须人工处理，勿手改页面"
    touched = _git("status", "--porcelain", "--", *CAPABILITY_OUTPUTS).rstrip()
    return False, "已重生成能力中心页面，commit 后重跑本自检：\n" + (touched or "（无文件变化）")


def check_net_deletion(base: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, str(FHD_ROOT / "scripts" / "dev" / "check_net_deletion.py"), "--json"],
        cwd=str(FHD_ROOT),
        capture_output=True,
        text=True,
    )
    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False, f"净删除检查无法运行：{proc.stderr.strip()[:200]}"
    try:
        old = json.loads(_git("show", f"{base}:{BASELINE}"))
    except (SystemExit, ValueError):
        old = {}
    new = json.loads((REPO_ROOT / BASELINE).read_text(encoding="utf-8"))
    raised = int(info["baseline"]) > int(old.get("lines", info["baseline"]))
    if raised and (not str(new.get("note") or "").strip() or new.get("note") == old.get("note")):
        return (
            False,
            "line_baseline 被抬升但 note 没写新原因：禁止静默抬升，按下方命令带 --reason 重做",
        )
    if not info["ok"]:
        return False, (
            f"净增 {info['delta']} 行（当前 {info['current']} / 基线 {info['baseline']}）。"
            "不要删无关代码凑数；按仓库惯例在 FHD/ 下运行 "
            'python scripts/dev/check_net_deletion.py --update --force --reason "<中文、评审可见：改了什么、各增多少行、谁批准>"，'
            f"把 {BASELINE} 随本 PR 一起 commit，并在 PR 正文写明"
        )
    if raised:
        return (
            True,
            f"基线已显式抬升 {old.get('lines')} → {info['baseline']}（note 已写原因，PR 正文须同步说明）",
        )
    return True, f"净删除 OK（差 {info['delta']:+d} 行）"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="对比基线（默认 origin/main）")
    parser.add_argument("--fix", action="store_true", help="能力中心漂移时就地重生成")
    args = parser.parse_args(argv)
    base = _git("merge-base", "HEAD", args.base).strip()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    results = [
        ("changelog", *check_changelog(base, branch)),
        ("capability-center", *check_capability_center(args.fix)),
        ("net-deletion", *check_net_deletion(base)),
    ]
    for name, ok, msg in results:
        print(f"[preflight] {name:<18} {'OK  ' if ok else 'FAIL'} {msg}")
    failed = [name for name, ok, _ in results if not ok]
    print(
        "[preflight] 全部通过，可以 push / 开 PR"
        if not failed
        else f"[preflight] 未过：{', '.join(failed)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
