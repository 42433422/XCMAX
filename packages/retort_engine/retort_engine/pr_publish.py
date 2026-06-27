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
    publishable = [item for item in comments if item.get("publishable", True) is not False and str(item.get("file") or item.get("path") or "")]
    selected = _dedupe_comments(publishable)[: max(1, max_comments)]
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
            "publishable_source_comment_count": len(publishable),
            "deduped_comment_count": len(selected),
            "skipped_unpublishable_count": max(0, len(comments) - len(publishable)),
            "skipped_duplicate_count": max(0, len(publishable) - len(selected)),
            "permission_required": "pull_request:write",
            "idempotency_key": idempotency_key,
            "idempotent": True,
        },
        "comments": payload_comments,
        "rollback": {
            "strategy": "delete_created_review_comments",
            "requires_receipts": True,
            "receipt_fields": ["comment_id", "path", "line", "idempotency_key"],
        },
    }


def run_publish_sandbox(
    publish_dry_run_path: str | Path,
    *,
    permissions: dict[str, bool] | None = None,
    fail_rollback_ids: set[str] | None = None,
) -> dict[str, Any]:
    dry_run_path = Path(publish_dry_run_path)
    dry_run = json.loads(dry_run_path.read_text(encoding="utf-8"))
    comments = [item for item in dry_run.get("comments") or [] if isinstance(item, dict)]
    idempotency_key = str((dry_run.get("summary") or {}).get("idempotency_key") or "")
    permission_state = permissions or {"pull_request_write": True}
    if not permission_state.get("pull_request_write", False):
        return {
            "status": "sandbox_permission_denied",
            "pr_url": str(dry_run.get("pr_url") or ""),
            "source_dry_run": str(dry_run_path),
            "summary": {
                "created_comment_count": 0,
                "rolled_back_comment_count": 0,
                "rollback_verified": True,
                "permission_denied": True,
                "idempotency_key": idempotency_key,
            },
            "created_receipts": [],
            "rollback_receipts": [],
            "evidence": {"degraded_without_write": True, "required_permission": "pull_request_write"},
        }
    created = [_sandbox_receipt(str(dry_run.get("pr_url") or ""), idempotency_key, comment) for comment in comments]
    failed = fail_rollback_ids or set()
    rolled_back = [{**item, "deleted": item["comment_id"] not in failed, "rollback_error": "simulated_delete_failed" if item["comment_id"] in failed else ""} for item in created]
    rollback_verified = bool(len(created) == len(rolled_back) and all(item.get("deleted") for item in rolled_back))
    return {
        "status": "sandbox_rolled_back" if rollback_verified else "sandbox_rollback_failed",
        "pr_url": str(dry_run.get("pr_url") or ""),
        "source_dry_run": str(dry_run_path),
        "summary": {
            "created_comment_count": len(created),
            "rolled_back_comment_count": sum(1 for item in rolled_back if item.get("deleted")),
            "rollback_verified": rollback_verified,
            "permission_denied": False,
            "idempotency_key": idempotency_key,
        },
        "created_receipts": created,
        "rollback_receipts": rolled_back,
    }


def _publish_comment(comment: dict[str, Any]) -> dict[str, Any]:
    payload = comment.get("publish_payload") if isinstance(comment.get("publish_payload"), dict) else {}
    return {
        "path": str(payload.get("path") or comment.get("file") or comment.get("path") or ""),
        "line": int(payload.get("line") or comment.get("line") or 1),
        "side": str(payload.get("side") or "RIGHT"),
        "body": str(payload.get("body") or comment.get("message") or comment.get("body") or ""),
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


def _dedupe_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen: set[tuple[str, int, str]] = set()
    for comment in comments:
        payload = _publish_comment(comment)
        key = (str(payload.get("path") or ""), int(payload.get("line") or 0), str(payload.get("body") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(comment)
    return deduped
