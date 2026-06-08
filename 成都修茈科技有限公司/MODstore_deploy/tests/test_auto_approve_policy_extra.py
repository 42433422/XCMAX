"""Targeted coverage for auto_approve_policy risk evaluation (no DB)."""

from __future__ import annotations

from modstore_server.auto_approve_policy import evaluate_risk


def test_high_risk_when_path_matches_builtin_pattern():
    risk, reason = evaluate_risk(".env.production", "TOKEN=xxx\n")
    assert risk == "high"
    assert "高风险" in reason or "forbidden" in reason


def test_high_risk_when_path_matches_forbidden_glob():
    risk, _ = evaluate_risk(
        "modstore_server/services/llm.py",
        "x = 1\n",
        forbidden_globs=["modstore_server/services/*"],
    )
    assert risk == "high"


def test_medium_when_outside_scope_globs():
    risk, _ = evaluate_risk(
        "modstore_server/playground/foo.py",
        "x = 1\n",
        scope_globs=["modstore_server/services/*"],
    )
    assert risk == "medium"


def test_medium_when_approval_required_glob_hits():
    risk, _ = evaluate_risk(
        "modstore_server/services/llm.py",
        "x = 1\n",
        scope_globs=["modstore_server/services/*"],
        approval_required_globs=["modstore_server/services/llm*"],
    )
    assert risk == "medium"


def test_low_when_inside_scope_and_short():
    risk, reason = evaluate_risk(
        "modstore_server/services/dummy.py",
        "x = 1\n",
        scope_globs=["modstore_server/services/*"],
    )
    assert risk == "low"
    assert "scope" in reason or "≤" in reason


def test_high_when_lines_exceed_4x_threshold(monkeypatch):
    monkeypatch.setenv("MODSTORE_AUTO_APPROVE_MAX_LINES", "5")
    big = "\n".join(f"line {i}" for i in range(60))
    risk, reason = evaluate_risk(
        "modstore_server/services/dummy.py",
        big,
        scope_globs=["modstore_server/services/*"],
    )
    assert risk == "high"
    assert "高风险" in reason
