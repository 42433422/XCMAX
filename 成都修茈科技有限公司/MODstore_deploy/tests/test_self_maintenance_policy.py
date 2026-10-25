import pytest

from modstore_server.self_maintenance_policy import (
    loop_memory_requires_executable_change,
    parse_diff_stat_paths,
    should_block_marker_only_diff_summary,
)


def test_diff_stat_parser_ignores_footer_line():
    diff_summary = """
 modstore_server/self_maintenance_loop_status.py | 4 ++++
 1 file changed, 4 insertions(+)
"""

    assert parse_diff_stat_paths(diff_summary) == [
        "modstore_server/self_maintenance_loop_status.py"
    ]


def test_marker_only_diff_blocks_when_memory_requires_executable_change():
    diff_summary = """
 modstore_server/self_maintenance_loop_status.py | 4 ++++
 1 file changed, 4 insertions(+)
"""
    memory = {
        "open_items": [
            {
                "kind": "review_qa_failure",
                "reason": "marker-only status file is not executable evidence",
            }
        ]
    }

    result = should_block_marker_only_diff_summary(diff_summary, memory)

    assert result["blocked"] is True
    assert result["paths"] == ["modstore_server/self_maintenance_loop_status.py"]


def test_malformed_loop_memory_fails_closed():
    requirement = loop_memory_requires_executable_change({"_parse_error": "bad json"})

    assert requirement["required"] is True


def test_indeterminate_merge_review_veto_requires_executable_change():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-d0a091",
                "kind": "automated_remediation",
                "reason": "para_ai_review_rejected",
                "review_veto_code": "indeterminate-review",
            }
        ]
    }

    requirement = loop_memory_requires_executable_change(memory)

    assert requirement["required"] is True
    assert "indeterminate merge-review" in requirement["reason"]


def test_diff_too_large_merge_review_veto_requires_executable_change():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-ee8a21",
                "kind": "automated_remediation",
                "reason": "para_ai_review_rejected",
                "review_feedback": "devfleet/cursor/sub-1-ee8a21: diff-too-large:37810",
            }
        ]
    }

    requirement = loop_memory_requires_executable_change(memory)

    assert requirement["required"] is True
    assert "diff-too-large merge-review" in requirement["reason"]


def test_actionable_merge_review_veto_requires_executable_change():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/codex/fix-1",
                "kind": "automated_remediation",
                "reason": "para_ai_review_rejected",
                "review_actionable_findings": True,
                "review_feedback": "REJECT: missing regression test for policy gate",
            }
        ]
    }

    requirement = loop_memory_requires_executable_change(memory)

    assert requirement["required"] is True
    assert "actionable merge-review" in requirement["reason"]


def test_parse_merge_review_diff_char_count_and_memory_flag():
    from modstore_server.self_maintenance_policy import (
        memory_has_diff_too_large_remediation,
        parse_merge_review_diff_char_count,
    )

    assert (
        parse_merge_review_diff_char_count("devfleet/cursor/sub-1-327c02: diff-too-large:50140")
        == 50140
    )
    memory = {
        "open_items": [
            {
                "kind": "automated_remediation",
                "reason": "para_ai_review_rejected",
                "review_veto_code": "diff-too-large",
            }
        ]
    }
    assert memory_has_diff_too_large_remediation(memory) is True
    assert memory_has_diff_too_large_remediation({"open_items": []}) is False


def test_retort_scope_remediation_requires_executable_change():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-6d8f01",
                "kind": "automated_remediation",
                "reason": "retort_scope_too_large",
                "detail": (
                    "Retort requested risk acceptance for 12 changed files; "
                    "rebuild the smallest valid fix from the clean base."
                ),
            }
        ]
    }

    requirement = loop_memory_requires_executable_change(memory)

    assert requirement["required"] is True
    assert "retort scope remediation" in requirement["reason"]


def test_memory_has_retort_scope_remediation_flag():
    from modstore_server.self_maintenance_policy import (
        memory_has_retort_scope_remediation,
    )

    memory = {
        "open_items": [
            {
                "kind": "automated_remediation",
                "reason": "retort_scope_too_large",
            }
        ]
    }
    assert memory_has_retort_scope_remediation(memory) is True
    assert memory_has_retort_scope_remediation({"open_items": []}) is False


@pytest.mark.parametrize(
    "hold_reason",
    [
        "structured_review_blocking_findings",
        "structured_qa_verdict_not_pass",
        "structured_qa_blocking_findings",
    ],
)
def test_structured_review_qa_holds_require_executable_change(hold_reason: str):
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-review",
                "kind": "automated_remediation",
                "reason": hold_reason,
                "run_id": "run-review",
                "task_id": "task-review",
            }
        ]
    }

    requirement = loop_memory_requires_executable_change(memory)

    assert requirement["required"] is True
    assert "structured review/QA hold" in requirement["reason"]


def test_target_branch_unavailable_hold_does_not_require_executable_change():
    branch = "devfleet/cursor/sub-1-target-ref"
    memory = {
        "last_policy_decision": {
            "reason": "structured_qa_verdict_not_pass",
            "structured_gate": {
                "qa": {
                    "blocking_findings": [f"target_branch_unavailable: origin/{branch}"],
                    "target_branch_available": False,
                }
            },
        },
        "open_items": [
            {
                "branch": branch,
                "kind": "automated_remediation",
                "reason": "structured_qa_verdict_not_pass",
                "run_id": "run-target-ref",
                "task_id": "task-target-ref",
            }
        ],
    }

    requirement = loop_memory_requires_executable_change(memory)

    assert requirement["required"] is False
    assert "no executable-change requirement" in requirement["reason"]


def test_report_only_protocol_holds_do_not_require_executable_change():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-protocol",
                "kind": "automated_remediation",
                "reason": "missing_structured_review_object",
                "run_id": "run-protocol",
                "task_id": "task-protocol",
            }
        ]
    }

    requirement = loop_memory_requires_executable_change(memory)

    assert requirement["required"] is False
