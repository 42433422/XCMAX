#!/usr/bin/env python3
"""Append a deploy event to metrics/deploy_events.jsonl (DORA input)."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(
    *,
    status: str,
    source_workflow: str,
    environment: str = "staging",
    head_branch: str = "main",
    git_sha: str | None = None,
    commit_at: str | None = None,
    restored_at: str | None = None,
    deploy_id: str | None = None,
    metrics_dir: Path,
) -> dict:
    event = {
        "deploy_id": deploy_id or uuid.uuid4().hex[:12],
        "deployed_at": _utc_now(),
        "commit_at": commit_at or _utc_now(),
        "status": status,
        "restored_at": restored_at,
        "source_workflow": source_workflow,
        "head_branch": head_branch,
        "environment": environment,
        "git_sha": git_sha or os.environ.get("GITHUB_SHA", ""),
    }
    out = metrics_dir / "deploy_events.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(json.dumps(event, ensure_ascii=False))
    return event


def main() -> None:
    p = argparse.ArgumentParser(description="Emit deploy event for DORA metrics")
    p.add_argument("--status", required=True, choices=["success", "failed", "rollback"])
    p.add_argument("--source-workflow", required=True)
    p.add_argument("--environment", default=os.environ.get("DEPLOY_ENVIRONMENT", "staging"))
    p.add_argument("--head-branch", default=os.environ.get("GITHUB_REF_NAME", "main"))
    p.add_argument("--git-sha", default=os.environ.get("GITHUB_SHA", ""))
    p.add_argument("--commit-at", default="")
    p.add_argument("--restored-at", default="")
    p.add_argument("--deploy-id", default="")
    p.add_argument(
        "--metrics-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "metrics",
    )
    args = p.parse_args()
    emit(
        status=args.status,
        source_workflow=args.source_workflow,
        environment=args.environment,
        head_branch=args.head_branch,
        git_sha=args.git_sha or None,
        commit_at=args.commit_at or None,
        restored_at=args.restored_at or None,
        deploy_id=args.deploy_id or None,
        metrics_dir=args.metrics_dir,
    )


if __name__ == "__main__":
    main()
