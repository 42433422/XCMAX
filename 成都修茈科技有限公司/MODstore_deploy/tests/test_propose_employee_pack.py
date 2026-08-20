# 成都修茈科技有限公司/MODstore_deploy/tests/test_propose_employee_pack.py
"""LLM 提议器单元测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from modstore_server.employee_autonomy_service import (
    ProposalValidationError,
    propose_employee_pack,
    validate_proposal,
)


def _make_signal(source: str = "intent_benchmark", score: float = 0.08) -> dict:
    return {
        "legacy_usage": {"signal_score": 0.0 if source != "legacy_usage" else score},
        "intent_benchmark": {
            "signal_score": score if source == "intent_benchmark" else 0.0,
            "accuracy": 0.72,
            "below_threshold": source == "intent_benchmark",
        },
        "slo_metrics": {"signal_score": 0.0 if source != "slo_metrics" else score},
        "total_score": score,
        "signals_to_propose": 1,
    }


def test_propose_employee_pack_returns_valid_schema():
    signals = _make_signal("intent_benchmark", 0.08)
    with patch("modstore_server.employee_autonomy_service._call_llm") as mock_llm:
        mock_llm.return_value = {
            "proposal_id": "test-uuid",
            "triggered_by": "intent_benchmark",
            "signal_score": 0.08,
            "department": "engineering",
            "employee_pack": {
                "name": "intent-failure-triage-clerk",
                "responsibility": "scan failed intent cases and cluster failure patterns",
                "prompt_template": "You are an intent failure triage clerk...",
                "skills": ["intent-benchmark", "failure-clustering"],
                "tools": ["read_file", "write_pr_comment"],
                "acceptance_criteria": ["recall >= 0.7 on test set"],
            },
            "estimated_files": 3,
            "estimated_tokens": 45000,
        }
        proposal = propose_employee_pack(signals)
    assert proposal["department"] in {
        "engineering",
        "quality",
        "ops",
        "growth",
        "support",
        "security",
    }
    assert proposal["estimated_files"] <= 5
    assert proposal["estimated_tokens"] <= 100000
    assert "prompt_template" in proposal["employee_pack"]
    assert "acceptance_criteria" in proposal["employee_pack"]


def test_validate_proposal_rejects_too_many_files():
    bad_proposal = {
        "proposal_id": "x",
        "department": "engineering",
        "employee_pack": {
            "name": "x",
            "prompt_template": "x",
            "skills": [],
            "tools": [],
            "acceptance_criteria": [],
        },
        "estimated_files": 7,
        "estimated_tokens": 10000,
    }
    with pytest.raises(ProposalValidationError, match="estimated_files"):
        validate_proposal(bad_proposal)


def test_validate_proposal_rejects_high_token_budget():
    bad_proposal = {
        "proposal_id": "x",
        "department": "engineering",
        "employee_pack": {
            "name": "x",
            "prompt_template": "x",
            "skills": [],
            "tools": [],
            "acceptance_criteria": [],
        },
        "estimated_files": 3,
        "estimated_tokens": 200000,
    }
    with pytest.raises(ProposalValidationError, match="estimated_tokens"):
        validate_proposal(bad_proposal)


def test_validate_proposal_rejects_invalid_department():
    bad_proposal = {
        "proposal_id": "x",
        "department": "marketing",
        "employee_pack": {
            "name": "x",
            "prompt_template": "x",
            "skills": [],
            "tools": [],
            "acceptance_criteria": [],
        },
        "estimated_files": 3,
        "estimated_tokens": 10000,
    }
    with pytest.raises(ProposalValidationError, match="department"):
        validate_proposal(bad_proposal)


def test_validate_proposal_rejects_missing_fields():
    bad_proposal = {"proposal_id": "x", "department": "engineering"}
    with pytest.raises(ProposalValidationError, match="employee_pack"):
        validate_proposal(bad_proposal)


def test_propose_employee_pack_skips_when_no_signal():
    """无 signal 时不调用 LLM，返回 None。"""
    empty_signals = {
        "legacy_usage": {"signal_score": 0.0},
        "intent_benchmark": {"signal_score": 0.0},
        "slo_metrics": {"signal_score": 0.0},
        "total_score": 0.0,
        "signals_to_propose": 0,
    }
    with patch("modstore_server.employee_autonomy_service._call_llm") as mock_llm:
        result = propose_employee_pack(empty_signals)
    assert result is None
    mock_llm.assert_not_called()
