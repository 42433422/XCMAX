"""Tests for employee brief routing extraction."""

from modstore_server.employee_brief_utils import (
    compact_routing_brief,
    extract_initial_idea_block,
    extract_routing_brief,
)
from modstore_server.word_extract_runtime import is_word_full_extract


def test_extract_initial_idea_block():
    text = "【初始想法】\n帮我做 Word 全量提取\n\n---\n\n【澄清对话】\n用户：hi"
    assert "Word 全量提取" in extract_initial_idea_block(text)


def test_compact_routing_brief_strips_placeholders():
    raw = (
        "【初始想法】\n（无回复）\n\n---\n\n" "【执行清单】\n帮我做 Word docx 全量提取 JSON 和 txt"
    )
    out = compact_routing_brief(raw)
    assert "（无回复）" not in out
    assert "Word" in out or is_word_full_extract(out)


def test_extract_routing_brief_prefers_short_brief():
    payload = {
        "brief": "帮我做 Word 文档全量提取，输出 JSON 和 txt",
        "employee_brief": "Word 全量提取员：解析 docx 输出 document_full.json",
    }
    rb = extract_routing_brief(payload)
    assert rb
    assert is_word_full_extract(rb)
