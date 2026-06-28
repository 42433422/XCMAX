from __future__ import annotations

from retort_engine.diff_hunk_semantics import analyze_hunk_semantics, summarize_hunk_semantics


def test_analyze_hunk_semantics_detects_deleted_validation_before_publish() -> None:
    hunk = {
        "header": "@@ -1,4 +1,4 @@",
        "changes": [
            {"type": "context", "line": 1, "text": "def publish(payload):"},
            {"type": "delete", "line": None, "text": "    validate_permissions(payload)"},
            {"type": "delete", "line": None, "text": "    assert payload['rollback_receipt']"},
            {"type": "add", "line": 2, "text": "    publish(payload)"},
            {"type": "add", "line": 3, "text": "    return True"},
        ],
    }

    analysis = analyze_hunk_semantics("retort_engine/pr_publish.py", hunk, "runtime")

    assert analysis["status"] == "semantic_findings"
    assert analysis["finding_count"] == 1
    assert analysis["findings"][0]["type"] == "validation_regression"
    assert analysis["findings"][0]["removed_evidence"]
    assert analysis["findings"][0]["added_evidence"]
    assert analysis["findings"][0]["confidence"] >= 90


def test_summarize_hunk_semantics_keeps_finding_types_and_contexts() -> None:
    analyses = [
        {
            "findings": [
                {"type": "validation_regression", "review_context": "runtime", "confidence": 95},
                {"type": "test_weakening", "review_context": "tests", "confidence": 94},
            ]
        }
    ]

    summary = summarize_hunk_semantics(analyses)

    assert summary["status"] == "active"
    assert summary["finding_count"] == 2
    assert summary["finding_types"] == ["test_weakening", "validation_regression"]
    assert summary["review_contexts"] == ["runtime", "tests"]
    assert summary["core_behavior_active"] is True
