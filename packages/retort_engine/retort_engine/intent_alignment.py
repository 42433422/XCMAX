from __future__ import annotations

import re
from typing import Any


STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "change",
    "changes",
    "code",
    "could",
    "feature",
    "from",
    "have",
    "issue",
    "make",
    "need",
    "needs",
    "only",
    "please",
    "pull",
    "request",
    "should",
    "that",
    "this",
    "with",
}


def assess_change_intent_alignment(
    files: list[dict[str, Any]],
    *,
    issue_context: str = "",
    pr_body: str = "",
    min_keyword_length: int = 4,
) -> dict[str, Any]:
    """Check whether changed paths and additions overlap with issue/task intent."""
    issue_terms = _keywords(issue_context, min_keyword_length=min_keyword_length)
    if not issue_terms:
        return {
            "status": "not_requested",
            "summary": {
                "issue_keyword_count": 0,
                "overlap_keyword_count": 0,
                "changed_file_count": len(files),
                "aligned": True,
            },
            "issue_keywords": [],
            "overlap_keywords": [],
            "missing_keywords": [],
            "evidence": {"style": "reviewscope_absorbed_issue_validation", "reason": "no_issue_context"},
        }
    changed_terms = _keywords(_changed_text(files, pr_body), min_keyword_length=min_keyword_length)
    overlap = sorted(issue_terms & changed_terms)
    missing = sorted(issue_terms - changed_terms)
    aligned = bool(overlap)
    return {
        "status": "aligned" if aligned else "misaligned",
        "summary": {
            "issue_keyword_count": len(issue_terms),
            "changed_keyword_count": len(changed_terms),
            "overlap_keyword_count": len(overlap),
            "changed_file_count": len(files),
            "aligned": aligned,
        },
        "issue_keywords": sorted(issue_terms),
        "overlap_keywords": overlap,
        "missing_keywords": missing[:12],
        "evidence": {
            "style": "reviewscope_absorbed_issue_validation",
            "source": "ReviewScope issue-mismatch rule",
        },
    }


def _changed_text(files: list[dict[str, Any]], pr_body: str) -> str:
    chunks = [pr_body]
    for file_review in files:
        chunks.append(str(file_review.get("path") or ""))
        for hunk in file_review.get("hunks") or []:
            for change in hunk.get("changes") or []:
                if change.get("type") == "add":
                    chunks.append(str(change.get("text") or ""))
    return "\n".join(chunks)


def _keywords(text: str, *, min_keyword_length: int) -> set[str]:
    normalized = re.sub(r"[_./:-]+", " ", text.lower())
    terms = set(re.findall(r"[a-z][a-z0-9]{2,}|[\u4e00-\u9fff]{2,}", normalized))
    return {term for term in terms if len(term) >= min_keyword_length and term not in STOPWORDS}
