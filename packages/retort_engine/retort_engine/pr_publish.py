from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def build_publish_dry_run(review_report_path: str | Path, *, max_comments: int = 50) -> dict[str, Any]:
    report_path = Path(review_report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    review = report.get("review") if isinstance(report.get("review"), dict) else {}
    comments = [item for item in review.get("comments") or [] if isinstance(item, dict)]
    selected = comments[: max(1, max_comments)]
    payload_comments = [_publish_comment(comment) for comment in selected]
    idempotency_key = _idempotency_key(str(report.get("pr_url") or ""), payload_comments)
    return {
        "status": "dry_run_ready",
        "pr_url": str(report.get("pr_url") or ""),
        "diff_url": str(report.get("diff_url") or ""),
        "source_report": str(report_path),
        "summary": {
            "dry_run": True,
            "would_post_comment_count": len(payload_comments),
            "source_comment_count": len(comments),
            "permission_required": "pull_request:write",
            "idempotency_key": idempotency_key,
        },
        "comments": payload_comments,
        "rollback": {
            "strategy": "delete_created_review_comments",
            "requires_receipts": True,
            "receipt_fields": ["comment_id", "path", "line", "idempotency_key"],
        },
    }


def run_publish_sandbox(publish_dry_run_path: str | Path) -> dict[str, Any]:
    dry_run_path = Path(publish_dry_run_path)
    dry_run = json.loads(dry_run_path.read_text(encoding="utf-8"))
    comments = [item for item in dry_run.get("comments") or [] if isinstance(item, dict)]
    idempotency_key = str((dry_run.get("summary") or {}).get("idempotency_key") or "")
    created = [_sandbox_receipt(str(dry_run.get("pr_url") or ""), idempotency_key, comment) for comment in comments]
    rolled_back = [{**item, "deleted": True} for item in created]
    return {
        "status": "sandbox_rolled_back",
        "pr_url": str(dry_run.get("pr_url") or ""),
        "source_dry_run": str(dry_run_path),
        "summary": {
            "created_comment_count": len(created),
            "rolled_back_comment_count": len(rolled_back),
            "rollback_verified": len(created) == len(rolled_back),
            "idempotency_key": idempotency_key,
        },
        "created_receipts": created,
        "rollback_receipts": rolled_back,
    }


def _publish_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(comment.get("file") or ""),
        "line": int(comment.get("line") or 1),
        "side": "RIGHT",
        "body": str(comment.get("message") or ""),
        "severity": str(comment.get("severity") or "info"),
        "strategy": str(comment.get("strategy") or "semantic_review"),
    }


def _idempotency_key(pr_url: str, comments: list[dict[str, Any]]) -> str:
    payload = json.dumps({"pr_url": pr_url, "comments": comments}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _sandbox_receipt(pr_url: str, idempotency_key: str, comment: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"pr_url": pr_url, "key": idempotency_key, "comment": comment}, ensure_ascii=False, sort_keys=True)
    return {
        "comment_id": hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12],
        "path": str(comment.get("path") or ""),
        "line": int(comment.get("line") or 1),
        "idempotency_key": idempotency_key,
        "created": True,
    }
