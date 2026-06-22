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
