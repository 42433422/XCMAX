from __future__ import annotations

from retort_engine.intent_alignment import assess_change_intent_alignment
from retort_engine.pr_review import parse_unified_diff


def test_intent_alignment_detects_issue_overlap() -> None:
    diff = """diff --git a/app/auth/password_reset.py b/app/auth/password_reset.py
--- a/app/auth/password_reset.py
+++ b/app/auth/password_reset.py
@@ -0,0 +1,2 @@
+def send_password_reset_email():
+    return "reset"
"""

    result = assess_change_intent_alignment(parse_unified_diff(diff), issue_context="Add password reset flow for auth accounts")

    assert result["status"] == "aligned"
    assert {"password", "reset", "auth"} & set(result["overlap_keywords"])


def test_intent_alignment_flags_unrelated_changes() -> None:
    diff = """diff --git a/app/theme.css b/app/theme.css
--- a/app/theme.css
+++ b/app/theme.css
@@ -0,0 +1,2 @@
+.hero { color: blue; }
+.card { border-radius: 8px; }
"""

    result = assess_change_intent_alignment(parse_unified_diff(diff), issue_context="Fix password reset token expiry in auth flow")

    assert result["status"] == "misaligned"
    assert result["summary"]["overlap_keyword_count"] == 0
    assert "password" in result["missing_keywords"]
