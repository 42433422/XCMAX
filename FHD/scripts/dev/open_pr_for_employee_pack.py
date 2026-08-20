#!/usr/bin/env python3
# mypy: disable-error-code="no-any-return"
"""创建分支 + commit + push + 开 PR。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def create_branch_commit_pr(
    *,
    files_dir: Path,
    branch_name: str,
    proposal: Dict[str, Any],
) -> str:
    """创建分支 + 添加文件 + commit + push + 开 PR。返回 PR URL。"""
    repo = os.environ.get("GITHUB_REPO", "")
    if not repo:
        raise RuntimeError("GITHUB_REPO env var not set")

    pack_name = proposal.get("employee_pack", {}).get("name", "unnamed")
    target_dir = (
        Path("成都修茈科技有限公司/MODstore_deploy/catalog_data/files") / f"{pack_name}@1.0.0"
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    # 复制文件
    import shutil

    for f in files_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, target_dir / f.name)

    # git 操作
    _run(["git", "checkout", "-b", branch_name])
    _run(["git", "add", str(target_dir)])
    _run(
        [
            "git",
            "commit",
            "-m",
            f"feat(employee_pack): add {pack_name}\n\nProposal-ID: {proposal.get('proposal_id')}",
        ]
    )
    _run(["git", "push", "origin", branch_name])

    # 开 PR
    pr_url = _run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            repo,
            "--head",
            branch_name,
            "--base",
            "main",
            "--title",
            f"[ai-implement] {pack_name}",
            "--body",
            f"Auto-implemented employee pack from proposal {proposal.get('proposal_id')}",
            "--label",
            "ai-implemented",
        ]
    )
    if pr_url.returncode != 0:
        raise RuntimeError(f"gh pr create failed: {pr_url.stderr}")
    return pr_url.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-dir", required=True)
    parser.add_argument("--branch-name", required=True)
    parser.add_argument("--proposal", required=True)
    args = parser.parse_args()
    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    pr_url = create_branch_commit_pr(
        files_dir=Path(args.files_dir),
        branch_name=args.branch_name,
        proposal=proposal,
    )
    print(pr_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
