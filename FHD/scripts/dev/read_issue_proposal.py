#!/usr/bin/env python3
# mypy: disable-error-code="no-any-return"
"""从 GitHub issue body 中提取 LLM 提议 JSON。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def extract_proposal_from_issue_body(body: str) -> Dict[str, Any]:
    """从 issue body 中提取 ```json ... ``` 块并解析。"""
    match = re.search(r"```json\s*\n(.*?)\n```", body, re.DOTALL)
    if not match:
        raise ValueError("no JSON code block found in issue body")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in issue body: {e}")


def fetch_issue_body(issue_number: int) -> str:
    """调 gh CLI 获取 issue body。"""
    repo = _repo_from_env()
    cmd = ["gh", "issue", "view", str(issue_number), "--repo", repo, "--json", "body"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh issue view failed: {result.stderr}")
    data = json.loads(result.stdout)
    return data.get("body", "")


def _repo_from_env() -> str:
    repo = __import__("os").environ.get("GITHUB_REPO", "")
    if not repo:
        raise RuntimeError("GITHUB_REPO env var not set")
    return repo


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_number", type=int)
    parser.add_argument("--output", default="proposal.json", help="output JSON path")
    args = parser.parse_args()
    body = fetch_issue_body(args.issue_number)
    proposal = extract_proposal_from_issue_body(body)
    Path(args.output).write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote proposal to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
