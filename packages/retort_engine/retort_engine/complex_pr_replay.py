from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from retort_engine.pr_dry_run import review_pr_url

DEFAULT_COMPLEX_PR_URLS = (
    "https://github.com/42433422/XCMAX/pull/92",
    "https://github.com/42433422/XCMAX/pull/97",
    "https://github.com/42433422/XCMAX/pull/83",
)

Reviewer = Callable[[str], dict[str, Any]]


def build_complex_pr_replay_report(
    project: str | Path,
    *,
    pr_urls: list[str] | tuple[str, ...] | None = None,
    max_comments: int = 20,
    max_bytes: int = 800000,
    reviewer: Reviewer | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    urls = tuple(pr_urls or DEFAULT_COMPLEX_PR_URLS)
    replayed = []
    review_call = reviewer or (lambda url: review_pr_url(url, max_comments=max_comments, max_bytes=max_bytes))
    for url in urls:
        review = review_call(url)
        summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
        comments = [item for item in (review.get("review") or {}).get("comments") or [] if isinstance(item, dict)]
        files = [item for item in (review.get("review") or {}).get("files") or [] if isinstance(item, dict)]
        language_extensions = sorted({_extension(str(item.get("path") or "")) for item in files if _extension(str(item.get("path") or ""))})
        severity_counts = {severity: sum(1 for item in comments if str(item.get("severity") or "") == severity) for severity in ("high", "medium", "low", "info")}
        file_count = int(summary.get("file_count") or 0)
        hunk_count = int(summary.get("hunk_count") or 0)
        fetched_bytes = int(summary.get("fetched_bytes") or 0)
        reviewed_new_changes = int(((review.get("review") or {}).get("summary") or {}).get("reviewed_new_change_count") or 0)
        complex_enough = file_count >= 3 or hunk_count >= 6 or fetched_bytes >= 10000 or bool(summary.get("truncated"))
        replayed.append(
            {
                "pr_url": str(review.get("pr_url") or url),
                "status": str(review.get("status") or ""),
                "file_count": file_count,
                "hunk_count": hunk_count,
                "comment_count": int(summary.get("comment_count") or 0),
                "reviewed_new_change_count": reviewed_new_changes,
                "fetched_bytes": fetched_bytes,
                "truncated": bool(summary.get("truncated")),
                "language_extensions": language_extensions,
                "severity_counts": severity_counts,
                "complex_enough": complex_enough,
            }
        )
    reviewed = [item for item in replayed if item["status"] == "reviewed"]
    complex_items = [item for item in reviewed if item["complex_enough"]]
    total_comments = sum(int(item["comment_count"]) for item in reviewed)
    total_hunks = sum(int(item["hunk_count"]) for item in reviewed)
    total_files = sum(int(item["file_count"]) for item in reviewed)
    total_reviewed_changes = sum(int(item["reviewed_new_change_count"]) for item in reviewed)
    status = "ready" if len(reviewed) >= 3 and len(complex_items) >= 3 and total_comments >= 10 and total_reviewed_changes >= 100 else "needs_more_evidence"
    return {
        "status": status,
        "project": str(root),
        "summary": {
            "pr_count": len(replayed),
            "reviewed_pr_count": len(reviewed),
            "complex_pr_count": len(complex_items),
            "total_file_count": total_files,
            "total_hunk_count": total_hunks,
            "total_comment_count": total_comments,
            "total_reviewed_new_change_count": total_reviewed_changes,
            "truncated_pr_count": sum(1 for item in reviewed if item["truncated"]),
            "distinct_extension_count": len({ext for item in reviewed for ext in item["language_extensions"]}),
        },
        "pull_requests": replayed,
        "evidence": {
            "reviewer": "retort_engine.pr_dry_run.review_pr_url",
            "urls": list(urls),
            "stores_summaries_only": True,
        },
    }


def _extension(path: str) -> str:
    suffix = Path(path.strip('"')).suffix.lower()
    return suffix[1:] if suffix else ""
