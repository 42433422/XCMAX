"""Tests for :mod:`vibe_coding.nl.parsing` — the tolerant LLM JSON parser."""

from __future__ import annotations

import pytest

from vibe_coding.nl.parsing import (
    JSONParseError,
    extract_first_object,
    safe_parse_json,
    safe_parse_json_object,
)


class TestStrictMode:
    """Strict, well-formed JSON should round-trip unchanged."""

    def test_object(self) -> None:
        assert safe_parse_json('{"a": 1}') == {"a": 1}

    def test_array(self) -> None:
        assert safe_parse_json("[1, 2, 3]") == [1, 2, 3]

    def test_nested(self) -> None:
        assert safe_parse_json('{"a": {"b": [1, 2]}}') == {"a": {"b": [1, 2]}}

    def test_empty_object(self) -> None:
        assert safe_parse_json("{}") == {}


class TestFenceStripping:
    def test_json_fence(self) -> None:
        raw = '```json\n{"x": 1}\n```'
        assert safe_parse_json_object(raw) == {"x": 1}

    def test_python_fence(self) -> None:
        raw = '```python\n{"x": 1}\n```'
        assert safe_parse_json_object(raw) == {"x": 1}

    def test_bare_fence(self) -> None:
        raw = '```\n{"x": 1}\n```'
        assert safe_parse_json_object(raw) == {"x": 1}

    def test_uppercase_fence(self) -> None:
        raw = '```JSON\n{"x": 1}\n```'
        assert safe_parse_json_object(raw) == {"x": 1}


class TestChatterPrefix:
    def test_chatter_before(self) -> None:
        raw = 'Sure, here is the JSON:\n{"a": 1}'
        assert safe_parse_json_object(raw) == {"a": 1}

    def test_chatter_after(self) -> None:
        raw = '{"a": 1}\n\nLet me know if you need anything else!'
        assert safe_parse_json_object(raw) == {"a": 1}

    def test_chinese_chatter(self) -> None:
        raw = "好的，下面是 JSON：\n{\"name\": \"测试\"}"
        assert safe_parse_json_object(raw) == {"name": "测试"}


class TestComments:
    def test_line_comment(self) -> None:
        raw = '{\n  "a": 1, // this is a comment\n  "b": 2\n}'
        assert safe_parse_json_object(raw) == {"a": 1, "b": 2}

    def test_block_comment(self) -> None:
        raw = '{/* leading */ "a": 1, "b": /* inline */ 2}'
        assert safe_parse_json_object(raw) == {"a": 1, "b": 2}

    def test_url_with_double_slash_preserved(self) -> None:
        """``//`` inside a string literal must NOT be stripped as a comment."""
        raw = '{"url": "https://example.com/path"}'
        assert safe_parse_json_object(raw) == {"url": "https://example.com/path"}


class TestTrailingCommas:
    def test_trailing_in_object(self) -> None:
        assert safe_parse_json_object('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}

    def test_trailing_in_array(self) -> None:
        raw = '{"items": [1, 2, 3,]}'
        assert safe_parse_json_object(raw) == {"items": [1, 2, 3]}

    def test_trailing_with_whitespace(self) -> None:
        raw = '{"a": 1, "b": 2 ,\n }'
        assert safe_parse_json_object(raw) == {"a": 1, "b": 2}


class TestSmartQuotes:
    def test_smart_double_quotes(self) -> None:
        raw = "{\u201ca\u201d: \u201cb\u201d}"
        assert safe_parse_json_object(raw) == {"a": "b"}


class TestInvisibleChars:
    def test_bom_stripped(self) -> None:
        raw = "\ufeff{\"a\": 1}"
        assert safe_parse_json_object(raw) == {"a": 1}

    def test_zero_width_space_stripped(self) -> None:
        raw = "{\u200b\"a\": 1}"
        assert safe_parse_json_object(raw) == {"a": 1}


class TestTruncation:
    def test_missing_closing_brace(self) -> None:
        raw = '{"a": 1, "b": 2'
        assert safe_parse_json_object(raw) == {"a": 1, "b": 2}

    def test_missing_closing_brace_nested(self) -> None:
        raw = '{"a": {"b": [1, 2'
        out = safe_parse_json_object(raw)
        assert out == {"a": {"b": [1, 2]}}

    def test_truncated_inside_string_value(self) -> None:
        raw = '{"source_code": "def demo(value):\\n    return {\\"out\\": value'
        out = safe_parse_json_object(raw)
        assert out["source_code"].startswith("def demo")

    def test_already_balanced_not_modified(self) -> None:
        # Truncation auto-close should not corrupt valid input.
        raw = '{"a": 1}'
        assert safe_parse_json_object(raw) == {"a": 1}


class TestExtractFirstObject:
    def test_simple_extract(self) -> None:
        raw = "before {\"a\": 1} after"
        out = extract_first_object(raw)
        assert out == '{"a": 1}'

    def test_nested_objects_picks_largest(self) -> None:
        raw = '{"a": 1} and also {"b": 2, "c": {"d": 3}}'
        out = extract_first_object(raw)
        assert '"d"' in out

    def test_no_object_returns_none(self) -> None:
        assert extract_first_object("just text") is None

    def test_brace_in_string_handled(self) -> None:
        raw = 'noise {"text": "has } brace"} more'
        out = extract_first_object(raw)
        assert out == '{"text": "has } brace"}'


class TestErrorPaths:
    def test_empty_string(self) -> None:
        with pytest.raises(JSONParseError):
            safe_parse_json("")

    def test_none_input(self) -> None:
        with pytest.raises(JSONParseError):
            safe_parse_json(None)  # type: ignore[arg-type]

    def test_completely_unparseable(self) -> None:
        with pytest.raises(JSONParseError):
            safe_parse_json("just random text with no structure")

    def test_array_when_object_required(self) -> None:
        with pytest.raises(JSONParseError, match="object"):
            safe_parse_json_object("[1, 2, 3]")


class TestRealWorldLLMOutputs:
    """Snapshots of actual broken LLM responses we've seen in production."""

    def test_full_response_with_fence_and_comments(self) -> None:
        raw = """Here's the patch:
```json
{
  // a brief explanation
  "patch_id": "fix-123",
  "summary": "Add type hints",
  "edits": [
    {"path": "a.py", "operation": "modify", "hunks": []},
  ]
}
```
That should fix it!
"""
        out = safe_parse_json_object(raw)
        assert out["patch_id"] == "fix-123"
        assert out["summary"] == "Add type hints"
        assert len(out["edits"]) == 1

    def test_truncated_at_token_limit(self) -> None:
        raw = '''{"hypotheses": [{"id": "h1", "hypothesis": "foo"}, {"id": "h2"'''
        out = safe_parse_json_object(raw)
        assert "hypotheses" in out
        assert isinstance(out["hypotheses"], list)

    def test_multiple_json_objects(self) -> None:
        raw = '{"first": 1}\n\n{"second": 2, "deeper": {"value": 42}}'
        out = safe_parse_json_object(raw)
        # Should pick the largest one.
        assert out.get("second") == 2

    def test_chinese_with_comments_and_smart_quotes(self) -> None:
        raw = """\u201c好的\u201d
```json
{
  "domain": "中文领域",  // 用于守卫
  "test_cases": [
    {"input": "测试"},
  ]
}
```
"""
        out = safe_parse_json_object(raw)
        assert out["domain"] == "中文领域"
        assert len(out["test_cases"]) == 1
