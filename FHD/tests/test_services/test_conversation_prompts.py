"""app/services/conversation/prompts PromptsMixin 测试。"""

from __future__ import annotations

import hashlib
import json

import pytest

from app.services.conversation.prompts import PromptsMixin


@pytest.fixture
def mixin():
    return PromptsMixin()


# ---------------------------------------------------------------------------
# _sanitize_kitten_dataset
# ---------------------------------------------------------------------------


class TestSanitizeKittenDataset:
    def test_non_dict_returns_empty(self, mixin):
        assert mixin._sanitize_kitten_dataset("not a dict") == {}
        assert mixin._sanitize_kitten_dataset(None) == {}
        assert mixin._sanitize_kitten_dataset(42) == {}

    def test_preview_text_truncated(self, mixin):
        kd = {"preview_text": "x" * 15000}
        result = mixin._sanitize_kitten_dataset(kd)
        assert len(result["preview_text"]) < 15000
        assert result["preview_text"].endswith("\n…（已截断）")

    def test_preview_text_not_truncated_when_short(self, mixin):
        kd = {"preview_text": "short text"}
        result = mixin._sanitize_kitten_dataset(kd)
        assert result["preview_text"] == "short text"

    def test_fields_list_truncated(self, mixin):
        kd = {"fields": [f"field_{i}" for i in range(250)]}
        result = mixin._sanitize_kitten_dataset(kd)
        assert len(result["fields"]) == 200
        assert result["fields_truncated"] is True

    def test_fields_list_not_truncated(self, mixin):
        kd = {"fields": ["a", "b", "c"]}
        result = mixin._sanitize_kitten_dataset(kd)
        assert result["fields"] == ["a", "b", "c"]
        assert "fields_truncated" not in result

    def test_field_names_as_fallback(self, mixin):
        kd = {"field_names": ["x", "y"]}
        result = mixin._sanitize_kitten_dataset(kd)
        assert result["fields"] == ["x", "y"]

    def test_fields_converted_to_str(self, mixin):
        kd = {"fields": [1, 2, 3]}
        result = mixin._sanitize_kitten_dataset(kd)
        assert result["fields"] == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# _sanitize_kitten_business_snapshot
# ---------------------------------------------------------------------------


class TestSanitizeKittenBusinessSnapshot:
    def test_non_dict_returns_empty(self, mixin):
        assert mixin._sanitize_kitten_business_snapshot("str") == {}

    def test_text_truncated(self, mixin):
        snap = {"text": "y" * 20000}
        result = mixin._sanitize_kitten_business_snapshot(snap)
        assert len(result["text"]) < 20000
        assert result["text"].endswith("\n…（已截断）")

    def test_text_not_truncated(self, mixin):
        snap = {"text": "short"}
        result = mixin._sanitize_kitten_business_snapshot(snap)
        assert result["text"] == "short"


# ---------------------------------------------------------------------------
# _sanitize_web_search_results
# ---------------------------------------------------------------------------


class TestSanitizeWebSearchResults:
    def test_non_list_returns_empty(self, mixin):
        assert mixin._sanitize_web_search_results("not a list") == []

    def test_max_8_items(self, mixin):
        hits = [
            {"title": f"t{i}", "url": f"http://u{i}.com", "snippet": f"s{i}"} for i in range(15)
        ]
        result = mixin._sanitize_web_search_results(hits)
        assert len(result) == 8

    def test_non_dict_items_skipped(self, mixin):
        hits = ["not a dict", {"title": "t", "url": "http://u.com", "snippet": "s"}]
        result = mixin._sanitize_web_search_results(hits)
        assert len(result) == 1

    def test_no_url_skipped(self, mixin):
        hits = [{"title": "t", "snippet": "s"}]
        result = mixin._sanitize_web_search_results(hits)
        assert len(result) == 0

    def test_fields_truncated(self, mixin):
        hits = [{"title": "t" * 400, "url": "u" * 600, "snippet": "s" * 700}]
        result = mixin._sanitize_web_search_results(hits)
        assert len(result[0]["title"]) <= 300
        assert len(result[0]["url"]) <= 500
        assert len(result[0]["snippet"]) <= 600


# ---------------------------------------------------------------------------
# _format_kitten_business_snapshot_block
# ---------------------------------------------------------------------------


class TestFormatKittenBusinessSnapshotBlock:
    def test_none_returns_empty(self, mixin):
        assert mixin._format_kitten_business_snapshot_block(None) == ""

    def test_empty_dict_returns_empty(self, mixin):
        assert mixin._format_kitten_business_snapshot_block({}) == ""

    def test_non_dict_returns_empty(self, mixin):
        assert mixin._format_kitten_business_snapshot_block("str") == ""

    def test_no_text_returns_empty(self, mixin):
        assert mixin._format_kitten_business_snapshot_block({"text": ""}) == ""

    def test_with_text(self, mixin):
        result = mixin._format_kitten_business_snapshot_block({"text": "some data"})
        assert "小猫分析" in result
        assert "some data" in result

    def test_with_generated_at(self, mixin):
        result = mixin._format_kitten_business_snapshot_block(
            {"text": "data", "generated_at": "2024-01-01"}
        )
        assert "生成时间" in result
        assert "2024-01-01" in result


# ---------------------------------------------------------------------------
# _format_kitten_dataset_block
# ---------------------------------------------------------------------------


class TestFormatKittenDatasetBlock:
    def test_none_returns_no_data_message(self, mixin):
        result = mixin._format_kitten_dataset_block(None)
        assert "未附带表格数据" in result

    def test_empty_dict_returns_no_data_message(self, mixin):
        result = mixin._format_kitten_dataset_block({})
        assert "未附带表格数据" in result

    def test_non_dict_returns_empty(self, mixin):
        assert mixin._format_kitten_dataset_block("str") == ""

    def test_with_file_name(self, mixin):
        result = mixin._format_kitten_dataset_block({"file_name": "test.xlsx"})
        assert "test.xlsx" in result

    def test_with_name_fallback(self, mixin):
        result = mixin._format_kitten_dataset_block({"name": "report.csv"})
        assert "report.csv" in result

    def test_with_rows_and_columns(self, mixin):
        result = mixin._format_kitten_dataset_block({"rows": 100, "columns": 5})
        assert "行数：100" in result
        assert "列数：5" in result

    def test_with_fields(self, mixin):
        result = mixin._format_kitten_dataset_block({"fields": ["name", "age", "city"]})
        assert "name" in result
        assert "字段" in result

    def test_fields_truncated_at_80(self, mixin):
        result = mixin._format_kitten_dataset_block({"fields": [f"f{i}" for i in range(90)]})
        assert "省略" in result

    def test_with_preview_text(self, mixin):
        result = mixin._format_kitten_dataset_block({"preview_text": "sample data"})
        assert "样本行" in result
        assert "sample data" in result


# ---------------------------------------------------------------------------
# _format_web_search_block
# ---------------------------------------------------------------------------


class TestFormatWebSearchBlock:
    def test_no_hits_with_error(self, mixin):
        result = mixin._format_web_search_block([], "timeout", {})
        assert "未拿到网页摘要" in result
        assert "timeout" in result

    def test_no_hits_no_error(self, mixin):
        result = mixin._format_web_search_block([], None, {})
        assert "勿虚构检索结果" in result

    def test_with_hits(self, mixin):
        hits = [
            {"title": "Title1", "url": "http://a.com", "snippet": "Snippet1"},
            {"title": "Title2", "url": "http://b.com", "snippet": "Snippet2"},
        ]
        result = mixin._format_web_search_block(hits, None, {})
        assert "Title1" in result
        assert "http://a.com" in result
        assert "严禁编造" in result

    def test_with_meta(self, mixin):
        result = mixin._format_web_search_block([], None, {"provider": "google", "query": "test"})
        assert "google" in result
        assert "test" in result

    def test_snippet_truncated(self, mixin):
        hits = [{"title": "T", "url": "http://u.com", "snippet": "s" * 600}]
        result = mixin._format_web_search_block(hits, None, {})
        assert "…" in result

    def test_non_dict_hits_skipped(self, mixin):
        hits = ["not_a_dict", {"title": "T", "url": "http://u.com", "snippet": "S"}]
        result = mixin._format_web_search_block(hits, None, {})
        assert "T" in result

    def test_max_8_hits(self, mixin):
        hits = [
            {"title": f"T{i}", "url": f"http://u{i}.com", "snippet": f"S{i}"} for i in range(15)
        ]
        result = mixin._format_web_search_block(hits, None, {})
        # Only 8 items should be listed (numbered 1-8)
        assert "8." in result
        assert "9." not in result


# ---------------------------------------------------------------------------
# _format_request_context_for_system
# ---------------------------------------------------------------------------


class TestFormatRequestContextForSystem:
    def test_none_returns_empty(self, mixin):
        assert mixin._format_request_context_for_system(None) == ""

    def test_empty_dict_returns_empty(self, mixin):
        assert mixin._format_request_context_for_system({}) == ""

    def test_non_dict_returns_empty(self, mixin):
        assert mixin._format_request_context_for_system("str") == ""

    def test_with_kitten_analyzer(self, mixin):
        req = {
            "kitten_analyzer": True,
            "kitten_dataset": {"file_name": "data.xlsx", "rows": 10, "columns": 3},
        }
        result = mixin._format_request_context_for_system(req)
        assert "小猫分析" in result
        assert "data.xlsx" in result

    def test_with_web_search(self, mixin):
        req = {
            "kitten_analyzer": True,
            "kitten_web_search": True,
            "web_search_results": [{"title": "T", "url": "http://u.com", "snippet": "S"}],
            "web_search_meta": {"provider": "google", "query": "test"},
        }
        result = mixin._format_request_context_for_system(req)
        assert "互联网检索" in result

    def test_with_business_snapshot(self, mixin):
        req = {
            "kitten_analyzer": True,
            "kitten_business_snapshot": {"text": "business data"},
        }
        result = mixin._format_request_context_for_system(req)
        assert "业务数据库快照" in result

    def test_with_excel_vector_context(self, mixin):
        req = {
            "excel_vector_context": {
                "index_id": "idx1",
                "query": "search term",
                "hits": [{"score": 0.95, "content": "cell data", "metadata": {"sheet": "Sheet1"}}],
            }
        }
        result = mixin._format_request_context_for_system(req)
        assert "Excel语义检索" in result

    def test_extra_context(self, mixin):
        req = {"custom_key": "custom_value"}
        result = mixin._format_request_context_for_system(req)
        assert "附加上下文" in result
        assert "custom_key" in result


# ---------------------------------------------------------------------------
# _format_excel_vector_block
# ---------------------------------------------------------------------------


class TestFormatExcelVectorBlock:
    def test_with_no_hits(self, mixin):
        payload = {"index_id": "idx1", "query": "q", "hits": []}
        result = mixin._format_excel_vector_block(payload)
        assert "未召回" in result

    def test_with_hits(self, mixin):
        payload = {
            "index_id": "idx1",
            "query": "search",
            "hits": [
                {
                    "score": 0.95,
                    "content": "cell data",
                    "metadata": {"sheet": "Sheet1", "row_index": 5},
                }
            ],
        }
        result = mixin._format_excel_vector_block(payload)
        assert "Sheet1" in result
        assert "row=5" in result
        assert "0.9500" in result

    def test_hit_without_row_index(self, mixin):
        payload = {"hits": [{"score": 0.8, "content": "data", "metadata": {"sheet": "S1"}}]}
        result = mixin._format_excel_vector_block(payload)
        assert "S1" in result
        assert "row" not in result

    def test_content_truncated(self, mixin):
        payload = {
            "hits": [
                {
                    "score": 0.9,
                    "content": "x" * 700,
                    "metadata": {"sheet": "S1"},
                }
            ]
        }
        result = mixin._format_excel_vector_block(payload)
        assert "..." in result

    def test_no_index_id(self, mixin):
        payload = {"query": "q", "hits": []}
        result = mixin._format_excel_vector_block(payload)
        assert "索引ID" not in result

    def test_no_query(self, mixin):
        payload = {"index_id": "idx1", "hits": []}
        result = mixin._format_excel_vector_block(payload)
        assert "问题" not in result


# ---------------------------------------------------------------------------
# _metadata_cache_hash
# ---------------------------------------------------------------------------


class TestMetadataCacheHash:
    def test_none_returns_empty(self, mixin):
        assert mixin._metadata_cache_hash(None) == ""

    def test_empty_dict_returns_empty(self, mixin):
        assert mixin._metadata_cache_hash({}) == ""

    def test_dict_returns_md5(self, mixin):
        result = mixin._metadata_cache_hash({"a": 1, "b": 2})
        expected = hashlib.md5(
            json.dumps({"a": 1, "b": 2}, sort_keys=True, ensure_ascii=False, default=str).encode(
                "utf-8"
            )
        ).hexdigest()
        assert result == expected

    def test_non_serializable_falls_back(self, mixin):
        result = mixin._metadata_cache_hash({"a": object()})
        # Should return a hash string (from frozenset fallback) not crash
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _build_context_prompt
# ---------------------------------------------------------------------------


class TestBuildContextPrompt:
    def test_empty_context(self, mixin):
        class FakeContext:
            metadata = {}
            current_intent = None
            current_tool_key = None
            intent_hints = None
            pending_confirmation = None
            last_action = None

        ctx = FakeContext()
        assert mixin._build_context_prompt(ctx) == ""

    def test_with_intent(self, mixin):
        class FakeContext:
            metadata = {}
            current_intent = "order"
            current_tool_key = None
            intent_hints = None
            pending_confirmation = None
            last_action = None

        ctx = FakeContext()
        result = mixin._build_context_prompt(ctx)
        assert "当前会话意图" in result
        assert "order" in result

    def test_with_tool_key(self, mixin):
        class FakeContext:
            metadata = {}
            current_intent = None
            current_tool_key = "calculator"
            intent_hints = None
            pending_confirmation = None
            last_action = None

        ctx = FakeContext()
        result = mixin._build_context_prompt(ctx)
        assert "当前工具" in result

    def test_with_pending_confirmation(self, mixin):
        class FakeContext:
            metadata = {}
            current_intent = None
            current_tool_key = None
            intent_hints = None
            pending_confirmation = {"action": "delete", "description": "删除记录"}
            last_action = None

        ctx = FakeContext()
        result = mixin._build_context_prompt(ctx)
        assert "待确认操作" in result

    def test_with_request_context(self, mixin):
        class FakeContext:
            metadata = {"request_context": {"custom_key": "val"}}
            current_intent = None
            current_tool_key = None
            intent_hints = None
            pending_confirmation = None
            last_action = None

        ctx = FakeContext()
        result = mixin._build_context_prompt(ctx)
        assert "附加上下文" in result
