#!/usr/bin/env python3
"""提取某次发布关闭的工单（GitHub issue）编号。

扫描 ``--from-ref..--to-ref`` 范围内的合并提交消息，提取
``Closes #123`` / ``Fixes #123`` / ``Resolves #123`` 关联网，
输出逗号分隔或 JSON 数组，供 generate-download-manifest.py 写入
``linked_issues``，让市场端验收判定能把回执结果回写到原工单。

范围外或提取不到时不算错误（输出空列表，退出码 0）——
是否携带 linked_issues 不阻塞发布本身。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

_CLOSE_RE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE)


def _git_log_messages(from_ref: str, to_ref: str) -> list[str]:
    cmd = ["git", "log", "--format=%B%x00", f"{from_ref}..{to_ref}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if proc.returncode != 0:
        print(f"[warn] git log failed: {proc.stderr.strip()[:300]}", file=sys.stderr)
        return []
    return [msg for msg in proc.stdout.split("\x00") if msg.strip()]


def _gh_compare_messages(from_ref: str, to_ref: str, repo: str) -> list[str]:
    """浅克隆环境兜底：经 GitHub compare API 取提交消息。"""
    cmd = [
        "gh",
        "api",
        f"repos/{repo}/compare/{from_ref}...{to_ref}",
        "--jq",
        ".commits[].commit.message",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if proc.returncode != 0:
        print(f"[warn] gh compare failed: {proc.stderr.strip()[:300]}", file=sys.stderr)
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def extract_linked_issues(from_ref: str, to_ref: str, repo: str = "") -> list[int]:
    messages = _git_log_messages(from_ref, to_ref)
    if not messages and repo:
        messages = _gh_compare_messages(from_ref, to_ref, repo)
    issues: set[int] = set()
    for message in messages:
        for match in _CLOSE_RE.finditer(message):
            number = int(match.group(1))
            if number > 0:
                issues.add(number)
    return sorted(issues)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="from_ref", required=True)
    parser.add_argument("--to", dest="to_ref", required=True)
    parser.add_argument("--repo", default="", help="gh api 兜底所用 owner/repo")
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    args = parser.parse_args()

    issues = extract_linked_issues(args.from_ref, args.to_ref, repo=args.repo)
    if args.format == "json":
        print(json.dumps(issues))
    else:
        print(",".join(str(n) for n in issues))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
