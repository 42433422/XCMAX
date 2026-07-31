from __future__ import annotations

import pytest

from modstore_server.employee_pack_proposal import (
    ProposalValidationError,
    extract_eval_spec,
    validate_eval_spec,
)


def test_extract_eval_spec_from_employee_pack_eval() -> None:
    proposal = {
        "employee_pack": {
            "eval": {
                "metric_name": "recall",
                "eval_command": "echo recall: 0.7",
                "higher_is_better": True,
            }
        }
    }
    spec = extract_eval_spec(proposal)
    assert spec is not None
    assert spec["metric_name"] == "recall"
    assert "recall: 0.7" in spec["eval_command"]


def test_extract_eval_spec_from_acceptance_criteria_dict() -> None:
    proposal = {
        "employee_pack": {
            "acceptance_criteria": [
                "string criterion",
                {
                    "metric_name": "latency",
                    "eval_command": "echo latency: 12",
                    "higher_is_better": False,
                },
            ]
        }
    }
    spec = extract_eval_spec(proposal)
    assert spec is not None
    assert spec["metric_name"] == "latency"
    assert spec["higher_is_better"] is False


def test_validate_eval_spec_rejects_missing() -> None:
    with pytest.raises(ProposalValidationError):
        validate_eval_spec({"employee_pack": {"acceptance_criteria": ["x"]}})
