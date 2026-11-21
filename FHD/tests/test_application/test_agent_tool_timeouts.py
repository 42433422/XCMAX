"""ELT batches switch from startup to individual stage deadlines."""

from app.application.agent_orchestrator.tool_timeouts import (
    ELT_FILE_PHASES,
    ELT_FILE_WATCHDOG_SECONDS,
    ELT_LINKED_PREVIEW_TIMEOUT_SECONDS,
    tool_timeout_seconds,
    uses_elt_file_deadlines,
)


def test_elt_batch_switches_to_per_file_deadlines():
    params = {"file_paths": ["x"] * 22}
    assert uses_elt_file_deadlines("elt_import", "preview", params)
    assert uses_elt_file_deadlines("elt_import", "execute", params)
    assert uses_elt_file_deadlines("elt_import", "execute", {"run_id": "r1,r2"})
    assert uses_elt_file_deadlines("elt_import", "execute", {"run_ids": ["r1", "r2"]})
    assert uses_elt_file_deadlines("elt_import", "preview", {"file_path": "x"})
    assert uses_elt_file_deadlines("elt_import", "execute", {"run_id": "r1"})
    assert not uses_elt_file_deadlines("elt_import", "execute", {})
    assert not uses_elt_file_deadlines("products", "list", params)
    assert tool_timeout_seconds("elt_import", "preview", params, 60) == 90


def test_other_tools_keep_registered_default():
    assert tool_timeout_seconds("products", "list", {"file_paths": ["a"] * 10}, 60) == 60
    assert tool_timeout_seconds("customers", "create", None, 0) == 60


def test_linked_preview_has_a_separate_deadline_from_write_execution():
    assert ELT_FILE_WATCHDOG_SECONDS[ELT_FILE_PHASES["linked_preview"]] == (
        ELT_LINKED_PREVIEW_TIMEOUT_SECONDS + 5
    )
    assert ELT_FILE_WATCHDOG_SECONDS[ELT_FILE_PHASES["execute"]] == 245
