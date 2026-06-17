"""测试蒸馏数据采集服务模块。"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.distillation_data_collector import (
    INTENT_LABELS,
    SAMPLE_QUERIES,
    export_training_data,
    generate_samples_from_queries,
    get_deepseek_api_key,
    get_sample_count,
    get_sample_stats,
    mark_samples_as_used,
    save_distillation_sample,
)


class TestIntentLabels:
    """测试意图标签常量。"""

    def test_intent_labels_not_empty(self):
        assert len(INTENT_LABELS) > 0

    def test_intent_labels_are_strings(self):
        for label in INTENT_LABELS:
            assert isinstance(label, str)

    def test_no_duplicates(self):
        assert len(INTENT_LABELS) == len(set(INTENT_LABELS))


class TestSampleQueries:
    """测试示例查询数据。"""

    def test_sample_queries_covers_all_intents(self):
        for intent in INTENT_LABELS:
            assert intent in SAMPLE_QUERIES, f"Missing queries for intent: {intent}"

    def test_sample_queries_are_non_empty_lists(self):
        for intent, queries in SAMPLE_QUERIES.items():
            assert isinstance(queries, list)
            assert len(queries) > 0

    def test_sample_queries_are_strings(self):
        for intent, queries in SAMPLE_QUERIES.items():
            for q in queries:
                assert isinstance(q, str)
                assert len(q) > 0


class TestGetDeepseekApiKey:
    """测试 API Key 获取。"""

    def test_returns_env_var(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key-123"}):
            result = get_deepseek_api_key()
            assert result == "test-key-123"

    def test_returns_empty_when_no_env(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            with patch("os.path.exists", return_value=False):
                result = get_deepseek_api_key()
                assert result == ""


class TestSaveDistillationSample:
    """测试样本保存。"""

    def test_save_distillation_sample(self):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            save_distillation_sample("你好", "greet", {}, 0.95, "manual")

        mock_conn.execute.assert_called_once()

    def test_save_distillation_sample_with_slots(self):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            save_distillation_sample(
                "给七彩乐园开单", "shipment_generate", {"unit_name": "七彩乐园"}, 0.9, "deepseek"
            )

        mock_conn.execute.assert_called_once()


class TestGenerateSamplesFromQueries:
    """测试基于模板生成样本。"""

    def test_generate_samples_from_queries(self):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            with patch(
                "app.services.distillation_data_collector.save_distillation_sample"
            ) as mock_save:
                count = generate_samples_from_queries(SAMPLE_QUERIES)

        assert count > 0
        assert mock_save.call_count == count

    def test_generate_samples_extracts_unit_name(self):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            with patch(
                "app.services.distillation_data_collector.save_distillation_sample"
            ) as mock_save:
                # 中文没有空格分隔，split()[0] 会取到"七彩乐园开单"
                queries = {"shipment_generate": ["给 七彩乐园 开单"]}
                count = generate_samples_from_queries(queries)

        assert count == 1
        call_args = mock_save.call_args
        slots = call_args[0][2]
        assert "unit_name" in slots

    def test_generate_samples_extracts_quantity(self):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            with patch(
                "app.services.distillation_data_collector.save_distillation_sample"
            ) as mock_save:
                queries = {"shipment_generate": ["3桶规格20的PE白底漆"]}
                count = generate_samples_from_queries(queries)

        assert count == 1
        call_args = mock_save.call_args
        slots = call_args[0][2]
        assert slots.get("quantity_tins") == 3

    def test_generate_samples_extracts_spec(self):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            with patch(
                "app.services.distillation_data_collector.save_distillation_sample"
            ) as mock_save:
                queries = {"shipment_generate": ["3桶规格20的PE白底漆"]}
                count = generate_samples_from_queries(queries)

        assert count == 1
        call_args = mock_save.call_args
        slots = call_args[0][2]
        assert slots.get("tin_spec") == 20.0

    def test_generate_samples_empty_queries(self):
        with patch("app.services.distillation_data_collector.ENGINE", MagicMock()):
            with patch("app.services.distillation_data_collector.save_distillation_sample"):
                count = generate_samples_from_queries({})
        assert count == 0

    def test_generate_samples_no_unit_name_for_short_after_give(self):
        """给后面只有一个字不应提取 unit_name（len <= 1）。"""
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            with patch(
                "app.services.distillation_data_collector.save_distillation_sample"
            ) as mock_save:
                queries = {"shipment_generate": ["给 a 开单"]}
                count = generate_samples_from_queries(queries)

        assert count == 1
        call_args = mock_save.call_args
        slots = call_args[0][2]
        # "a" 只有 1 个字符，不满足 len > 1 的条件
        assert "unit_name" not in slots


class TestGetSampleCount:
    """测试样本计数。"""

    def test_get_sample_count(self):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            result = get_sample_count()
        assert result == 42

    def test_get_sample_count_with_intent(self):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 10
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            result = get_sample_count(intent="greet")
        assert result == 10

    def test_get_sample_count_none_scalar(self):
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            result = get_sample_count()
        assert result == 0


class TestGetSampleStats:
    """测试样本统计。"""

    def test_get_sample_stats(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("greet", 10),
            ("shipment_generate", 20),
        ]
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            result = get_sample_stats()
        assert result == {"greet": 10, "shipment_generate": 20}


class TestExportTrainingData:
    """测试训练数据导出。"""

    def test_export_jsonl(self, tmp_path):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("你好", "greet", "{}"),
            ("开单", "shipment_generate", '{"unit_name": "七彩乐园"}'),
        ]
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        output_path = str(tmp_path / "training.jsonl")
        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            result = export_training_data(output_path=output_path, format="jsonl")

        assert result == output_path
        assert os.path.exists(output_path)
        with open(output_path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2
        data = json.loads(lines[0])
        assert "text" in data
        assert "label" in data

    def test_export_bert(self, tmp_path):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("你好", "greet", "{}"),
        ]
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        output_path = str(tmp_path / "training.jsonl")
        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            result = export_training_data(output_path=output_path, format="bert")

        bert_path = str(tmp_path / "training_bert.tsv")
        assert os.path.exists(bert_path)
        with open(bert_path, encoding="utf-8") as f:
            lines = f.readlines()
        assert lines[0] == "text\tlabel\n"
        assert "你好\tgreet" in lines[1]

    def test_export_default_path(self, tmp_path):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            with patch("app.services.distillation_data_collector.DISTILL_DIR", str(tmp_path)):
                result = export_training_data(format="jsonl")
        assert result.endswith("training_data.jsonl")


class TestMarkSamplesAsUsed:
    """测试标记样本已使用。"""

    def test_mark_samples_as_used(self):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            mark_samples_as_used([1, 2, 3])

        mock_conn.execute.assert_called_once()

    def test_mark_samples_as_used_empty(self):
        mock_engine = MagicMock()
        with patch("app.services.distillation_data_collector.ENGINE", mock_engine):
            mark_samples_as_used([])
        mock_engine.begin.assert_not_called()


class TestCallDeepseekIntent:
    """测试 DeepSeek API 调用。"""

    @pytest.mark.asyncio
    async def test_call_deepseek_intent_no_api_key(self):
        from app.services.distillation_data_collector import call_deepseek_intent

        result = await call_deepseek_intent("", "你好")
        assert result is None

    @pytest.mark.asyncio
    async def test_call_deepseek_intent_success(self):
        from app.services.distillation_data_collector import call_deepseek_intent

        mock_result = {
            "choices": [{"message": {"content": json.dumps({"intent": "greet", "slots": {}})}}]
        }
        mock_chat = AsyncMock(return_value=mock_result)
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            mock_chat,
        ):
            result = await call_deepseek_intent("test-key", "你好")

        assert result is not None
        assert result["intent"] == "greet"
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_call_deepseek_intent_api_failure(self):
        from app.services.distillation_data_collector import call_deepseek_intent

        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new_callable=AsyncMock,
            side_effect=ConnectionError("API down"),
        ):
            result = await call_deepseek_intent("test-key", "你好")

        assert result is None

    @pytest.mark.asyncio
    async def test_call_deepseek_intent_invalid_json(self):
        from app.services.distillation_data_collector import call_deepseek_intent

        mock_result = {"choices": [{"message": {"content": "not valid json"}}]}
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await call_deepseek_intent("test-key", "你好")

        assert result is None

    @pytest.mark.asyncio
    async def test_call_deepseek_intent_empty_choices(self):
        from app.services.distillation_data_collector import call_deepseek_intent

        mock_result = {"choices": []}
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await call_deepseek_intent("test-key", "你好")

        assert result is None

    @pytest.mark.asyncio
    async def test_call_deepseek_intent_none_result(self):
        from app.services.distillation_data_collector import call_deepseek_intent

        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await call_deepseek_intent("test-key", "你好")

        assert result is None


class TestCollectSamplesViaDeepseek:
    """测试通过 DeepSeek 收集样本。"""

    @pytest.mark.asyncio
    async def test_collect_already_satisfied(self):
        from app.services.distillation_data_collector import collect_samples_via_deepseek

        with patch(
            "app.services.distillation_data_collector.get_sample_count",
            return_value=600,
        ):
            result = await collect_samples_via_deepseek("test-key", target_count=500)
        assert result == 0
