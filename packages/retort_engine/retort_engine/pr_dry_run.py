from __future__ import annotations

import re
from typing import Any
from urllib.request import Request, urlopen

from retort_engine.pr_review import review_diff


GITHUB_PR_RE = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)(?:[/?#].*)?$")
PROVIDER_FALLBACK_ORDER = ("openai", "anthropic", "gemini", "groq", "local_static")
PROMPT_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "system prompt",
    "developer message",
    "reveal your prompt",
    "act as",
    "jailbreak",
)


def review_pr_url(pr_url: str, *, previous_diff_text: str = "", max_comments: int = 20, max_bytes: int = 500_000) -> dict[str, Any]:
    diff_url = pr_diff_url(pr_url)
    diff_text, fetched_bytes, truncated = _fetch_diff(diff_url, max_bytes=max_bytes)
    prepared = prepare_review_input(diff_text, max_bytes=max_bytes)
    review = review_diff(prepared["diff_text"], previous_diff_text=previous_diff_text, max_comments=max_comments)
    summary = {
        "review_status": review.get("status"),
        "file_count": int((review.get("summary") or {}).get("file_count") or 0),
        "hunk_count": int((review.get("summary") or {}).get("hunk_count") or 0),
        "comment_count": int((review.get("summary") or {}).get("comment_count") or 0),
        "task_group_count": len(review.get("task_groups") or []),
        "incremental": bool((review.get("incremental") or {}).get("enabled")),
        "fetched_bytes": fetched_bytes,
        "truncated": truncated or bool(prepared["truncated"]),
        "input_original_bytes": prepared["original_bytes"],
        "input_review_bytes": prepared["review_bytes"],
        "prompt_injection_marker_count": prepared["prompt_injection_marker_count"],
        "prompt_injection_guarded": prepared["prompt_injection_marker_count"] > 0,
        "provider_fallback_order": list(PROVIDER_FALLBACK_ORDER),
        "provider_fallback_terminal": PROVIDER_FALLBACK_ORDER[-1],
    }
    return {
        "status": "reviewed" if review.get("status") in {"reviewed", "no_new_changes"} else str(review.get("status") or "failed"),
        "pr_url": pr_url,
        "diff_url": diff_url,
        "summary": summary,
        "review": review,
    }


def prepare_review_input(diff_text: str, *, max_bytes: int = 500_000) -> dict[str, Any]:
    encoded = diff_text.encode("utf-8", errors="replace")
    original_bytes = len(encoded)
    truncated = len(encoded) > max_bytes
    if truncated:
        encoded = encoded[:max_bytes]
        diff_text = encoded.decode("utf-8", errors="replace")
    lowered = diff_text.lower()
    marker_hits = [marker for marker in PROMPT_INJECTION_MARKERS if marker in lowered]
    return {
        "diff_text": diff_text,
        "original_bytes": original_bytes,
        "review_bytes": len(encoded),
        "truncated": truncated,
        "prompt_injection_marker_count": len(marker_hits),
        "prompt_injection_markers": marker_hits,
        "provider_fallback_order": list(PROVIDER_FALLBACK_ORDER),
        "policy": "diff_is_untrusted_data_not_instructions",
    }


def pr_diff_url(pr_url: str) -> str:
    value = pr_url.strip()
    if value.endswith(".diff"):
        return value
    match = GITHUB_PR_RE.match(value)
    if not match:
        raise ValueError("review-pr expects a GitHub pull request URL or a .diff URL")
    return f"https://github.com/{match.group('owner')}/{match.group('repo')}/pull/{match.group('number')}.diff"


def _fetch_diff(url: str, *, max_bytes: int) -> tuple[str, int, bool]:
    request = Request(url, headers={"User-Agent": "retort-engine", "Accept": "text/plain"})
    with urlopen(request, timeout=30) as response:
        data = response.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace"), len(data), truncated
