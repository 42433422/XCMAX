"""数组字段接受模型常见的分隔字符串写法。"""

from __future__ import annotations

import pytest

from app.application.agent_orchestrator.tool_spec import validate_schema_object


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {"run_ids": {"type": "array", "items": {"type": "string"}}},
    }


def test_separated_string_is_split_into_array():
    payload = {"run_ids": "run-1, run-2；run-3"}
    ok, message = validate_schema_object(_schema(), payload)
    assert ok, message
    assert payload["run_ids"] == ["run-1", "run-2", "run-3"]


def test_single_string_becomes_single_item_array():
    payload = {"run_ids": "run-1"}
    ok, _ = validate_schema_object(_schema(), payload)
    assert ok
    assert payload["run_ids"] == ["run-1"]


def test_list_input_is_left_untouched():
    payload = {"run_ids": ["a", "b"]}
    ok, _ = validate_schema_object(_schema(), payload)
    assert ok
    assert payload["run_ids"] == ["a", "b"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
