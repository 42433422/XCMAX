from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from retort_engine.pr_dry_run import review_pr_url

DEFAULT_HOLDOUT_PR_URLS = (
    "https://github.com/psf/requests/pull/7505",
    "https://github.com/pallets/flask/pull/6013",
    "https://github.com/expressjs/express/pull/7265",
    "https://github.com/go-gorm/gorm/pull/7798",
    "https://github.com/fastapi/fastapi/pull/15852",
    "https://github.com/encode/django-rest-framework/pull/9978",
    "https://github.com/axios/axios/pull/11028",
    "https://github.com/vuejs/core/pull/15005",
    "https://github.com/rust-lang/cargo/pull/17139",
    "https://github.com/tokio-rs/tokio/pull/8226",
    "https://github.com/spring-projects/spring-framework/pull/36899",
    "https://github.com/dotnet/runtime/pull/129914",
    "https://github.com/pytest-dev/pytest/pull/14646",
    "https://github.com/pydantic/pydantic/pull/13343",
    "https://github.com/prisma/prisma/pull/29624",
    "https://github.com/laravel/framework/pull/60609",
    "https://github.com/rails/rails/pull/57891",
    "https://github.com/hashicorp/terraform/pull/38792",
    "https://github.com/ansible/ansible/pull/87165",
    "https://github.com/denoland/deno/pull/35540",
    "https://github.com/psf/requests/pull/7539",
    "https://github.com/pallets/flask/pull/5928",
    "https://github.com/expressjs/express/pull/7305",
    "https://github.com/go-gorm/gorm/pull/7796",
)

Reviewer = Callable[[str], dict[str, Any]]


def build_pr_holdout_blind_eval(
    project: str | Path,
    *,
    pr_urls: list[str] | tuple[str, ...] | None = None,
    target_prs: int = 20,
    max_comments: int = 12,
    max_bytes: int = 400000,
    output: str | Path = "",
    reviewer: Reviewer | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    urls = tuple(_dedupe(pr_urls or DEFAULT_HOLDOUT_PR_URLS))
    known_urls = _known_pr_urls(root)
    review_call = reviewer or (lambda url: review_pr_url(url, max_comments=max_comments, max_bytes=max_bytes))
    cases = [_evaluate_case(url, review_call) for url in urls]
    reviewed = [case for case in cases if case["status"] == "reviewed"]
    accepted = [case for case in reviewed if case["accepted"]]
    repos = {_repo_slug(str(case.get("pr_url") or "")) for case in reviewed}
    repos.discard("")
    extensions = {ext for case in reviewed for ext in case.get("language_extensions") or [] if str(ext).strip()}
    overlap = sorted({str(case.get("pr_url") or "") for case in cases if str(case.get("pr_url") or "") in known_urls})
    pass_rate = len(accepted) / len(reviewed) if reviewed else 0.0
    summary = {
        "target_pr_count": target_prs,
        "candidate_pr_count": len(cases),
        "reviewed_pr_count": len(reviewed),
        "accepted_pr_count": len(accepted),
        "failed_pr_count": len(cases) - len(reviewed),
        "acceptance_pass_rate": round(pass_rate, 4),
        "distinct_repo_count": len(repos),
        "distinct_extension_count": len(extensions),
        "total_comment_count": sum(int(case.get("comment_count") or 0) for case in reviewed),
        "total_file_count": sum(int(case.get("file_count") or 0) for case in reviewed),
        "total_hunk_count": sum(int(case.get("hunk_count") or 0) for case in reviewed),
        "total_reviewed_new_change_count": sum(int(case.get("reviewed_new_change_count") or 0) for case in reviewed),
        "truncated_pr_count": sum(1 for case in reviewed if case.get("truncated")),
        "overlap_with_prior_long_run_count": len(overlap),
        "holdout_label_count": len(cases),
        "blind_against_prior_reports": len(overlap) == 0,
    }
    ready = (
        summary["reviewed_pr_count"] >= target_prs
        and summary["accepted_pr_count"] >= target_prs
        and summary["distinct_repo_count"] >= min(14, target_prs)
        and summary["distinct_extension_count"] >= min(8, target_prs)
        and summary["total_comment_count"] >= target_prs
        and summary["total_reviewed_new_change_count"] >= target_prs
        and summary["truncated_pr_count"] <= 2
        and summary["blind_against_prior_reports"]
    )
    result = {
        "status": "ready" if ready else "needs_more_evidence",
        "project": str(root),
        "summary": summary,
        "cases": cases,
        "evidence": {
            "reviewer": "retort_engine.pr_dry_run.review_pr_url",
            "scope": "blind_holdout_public_pull_requests",
            "sample_source": "github_search_closed_merged_prs_not_used_by_prior_long_run",
            "known_report_paths": [
                "docs/retort_complex_pr_replay.json",
                "docs/retort_pr_long_run_review.json",
            ],
            "overlap_urls": overlap,
            "stores_summaries_only": True,
            "failure_isolation": "single_pr_failure_recorded_without_aborting_holdout",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _evaluate_case(url: str, reviewer: Reviewer) -> dict[str, Any]:
    try:
        review = reviewer(url)
    except Exception as exc:  # pragma: no cover - exercised by injected tests.
        return {
            "pr_url": url,
            "repo": _repo_slug(url),
            "status": "failed",
            "accepted": False,
            "error": str(exc)[-300:],
            "expectation": _expectation(),
        }
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    nested_review = review.get("review") if isinstance(review.get("review"), dict) else {}
    nested_summary = nested_review.get("summary") if isinstance(nested_review.get("summary"), dict) else {}
    files = [item for item in nested_review.get("files") or [] if isinstance(item, dict)]
    extensions = sorted({_extension(str(item.get("path") or "")) for item in files if _extension(str(item.get("path") or ""))})
    status = str(review.get("status") or "")
    comment_count = int(summary.get("comment_count") or nested_summary.get("comment_count") or 0)
    reviewed_changes = int(nested_summary.get("reviewed_new_change_count") or summary.get("reviewed_new_change_count") or 0)
    file_count = int(summary.get("file_count") or nested_summary.get("file_count") or len(files))
    accepted = status == "reviewed" and file_count > 0 and comment_count > 0 and reviewed_changes > 0
    return {
        "pr_url": str(review.get("pr_url") or url),
        "repo": _repo_slug(str(review.get("pr_url") or url)),
        "status": status,
        "accepted": accepted,
        "file_count": file_count,
        "hunk_count": int(summary.get("hunk_count") or nested_summary.get("hunk_count") or 0),
        "comment_count": comment_count,
        "reviewed_new_change_count": reviewed_changes,
        "fetched_bytes": int(summary.get("fetched_bytes") or 0),
        "truncated": bool(summary.get("truncated")),
        "language_extensions": extensions,
        "expectation": _expectation(),
    }


def _expectation() -> dict[str, Any]:
    return {
        "review_status": "reviewed",
        "min_file_count": 1,
        "min_comment_count": 1,
        "min_reviewed_new_change_count": 1,
        "label_source": "predeclared_holdout_acceptance_properties",
    }


def _known_pr_urls(root: Path) -> set[str]:
    urls: set[str] = set()
    for rel in ("docs/retort_complex_pr_replay.json", "docs/retort_pr_long_run_review.json"):
        report = _read_json(root / rel)
        for item in report.get("pull_requests") or []:
            if isinstance(item, dict) and item.get("pr_url"):
                urls.add(str(item["pr_url"]))
    return urls


def _repo_slug(url: str) -> str:
    match = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/\d+", url)
    return match.group(1) if match else ""


def _extension(path: str) -> str:
    suffix = Path(path.strip().strip('"')).suffix.lower()
    return suffix[1:] if suffix else ""


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            deduped.append(text)
            seen.add(text)
    return deduped


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
