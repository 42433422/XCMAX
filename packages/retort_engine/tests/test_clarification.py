from __future__ import annotations

from retort_engine.clarification import (
    build_clarification_questions,
    clarification_needed,
    enrich_strategy_intent,
)
from retort_engine.intent_alignment import assess_change_intent_alignment
from retort_engine.pr_review import parse_unified_diff


def test_build_questions_for_missing_intent() -> None:
    questions = build_clarification_questions(
        {"status": "not_requested"},
        strategy_intent="",
        changed_files=["app/auth.py"],
    )
    ids = {q["id"] for q in questions}
    assert "intent_missing" in ids
    assert clarification_needed({"status": "not_requested"}, "") is True


def test_build_questions_for_misaligned_change() -> None:
    diff = """\
diff --git a/docs/readme.md b/docs/readme.md
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1 +1 @@
-old
+typo fix
"""
    assessment = assess_change_intent_alignment(
        parse_unified_diff(diff),
        issue_context="Implement password reset token expiry for auth accounts",
    )
    questions = build_clarification_questions(
        assessment,
        strategy_intent="Implement password reset token expiry for auth accounts",
        changed_files=parse_unified_diff(diff),
    )
    assert any(q["id"] == "intent_misaligned" for q in questions)
    assert clarification_needed(assessment, "Implement password reset token expiry for auth accounts")


def test_enrich_strategy_intent_merges_answers() -> None:
    enriched = enrich_strategy_intent(
        "发布战略三席",
        {"intent_misaligned": "只改 strategic_council 回执契约"},
    )
    assert "发布战略三席" in enriched
    assert "strategic_council" in enriched
