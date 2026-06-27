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
