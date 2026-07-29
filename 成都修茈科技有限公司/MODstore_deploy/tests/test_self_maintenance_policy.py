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


def test_executable_change_blockers_unified_under_required_memory():
    from modstore_server.self_maintenance_policy import (
        assess_loop_memory_executable_change_blockers,
    )

    diff_too_large_memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-327c02",
                "kind": "automated_remediation",
                "reason": "para_ai_review_rejected",
                "review_veto_code": "diff-too-large",
            }
        ]
    }
    kb_result = assess_loop_memory_executable_change_blockers(
        [
            "FHD/XCAGI/kb/fixes/sample-fix.json",
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
        ],
        diff_too_large_memory,
    )
    assert kb_result["blocked"] is True
    assert kb_result["reason"] == "kb_paths_blocked_during_diff_too_large_remediation"

    marker_result = assess_loop_memory_executable_change_blockers(
        ["成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_loop_status.py"],
        diff_too_large_memory,
    )
    assert marker_result["blocked"] is True
    assert marker_result["reason"] == "marker_only_diff_requires_executable_change"

    production_result = assess_loop_memory_executable_change_blockers(
        [
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
            "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_policy.py",
        ],
        diff_too_large_memory,
    )
    assert production_result["blocked"] is False
