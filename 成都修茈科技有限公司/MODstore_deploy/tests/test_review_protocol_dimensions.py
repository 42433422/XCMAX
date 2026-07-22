"""自审协议：业务逻辑/性能维度 + 严格打回。"""

from modstore_server.self_maintenance_loop_runner import (
    _review_task_text,
    _validate_structured_review_protocol,
)


def _valid_review(**overrides):
    base = {
        "max_severity": "none",
        "blocking_findings": [],
        "risk_class": "low",
        "target_branch_available": True,
        "tested_commands": [],
        "dimensions": {
            "security": {"status": "pass", "findings": []},
            "business_logic": {"status": "pass", "findings": []},
            "performance": {"status": "pass", "findings": []},
        },
    }
    base.update(overrides)
    return base


def test_review_prompt_requires_three_dimensions():
    text = _review_task_text("run-x", "branch-x", {})
    assert "business_logic" in text
    assert "performance" in text
    assert "security" in text
    assert "dimensions" in text


def test_protocol_accepts_complete_dimensions():
    ok, reason = _validate_structured_review_protocol(_valid_review())
    assert ok is True
    assert reason == ""


def test_protocol_rejects_missing_dimensions():
    payload = _valid_review()
    del payload["dimensions"]
    ok, reason = _validate_structured_review_protocol(payload)
    assert ok is False
    assert reason == "missing_dimensions"


def test_protocol_rejects_perf_fail_without_blocking():
    payload = _valid_review(
        max_severity="medium",
        dimensions={
            "security": {"status": "pass", "findings": []},
            "business_logic": {"status": "pass", "findings": []},
            "performance": {"status": "fail", "findings": ["N+1 in loop"]},
        },
    )
    ok, reason = _validate_structured_review_protocol(payload)
    assert ok is False
    assert reason == "dimension_fail_without_blocking_findings"
