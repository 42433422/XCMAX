# mypy: disable-error-code="attr-defined"
"""CrossEncoderReranker 单元测试。

覆盖：
- disabled 模式向后兼容（rerank 回退到原顺序截断）
- local 模式（mock sentence_transformers.CrossEncoder）
- rerank 排序正确性（按 predict 分数降序）
- top_k 截断
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.rag.cross_encoder_reranker import (
    CrossEncoderReranker,
    get_default_reranker,
)
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk


@pytest.fixture(autouse=True)
def _reset_reranker_singleton():
    """每个用例前后清理单例，避免 env 变化被缓存。"""
    CrossEncoderReranker.reset_singleton_for_tests()
    yield
    CrossEncoderReranker.reset_singleton_for_tests()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch):
    """清理 reranker 相关环境变量。"""
    for key in (
        "FHD_RERANKER_MODE",
        "FHD_RERANKER_LOCAL_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _make_chunks(texts: list[str]) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(text=t, score=0.0, chunk_index=i, source="hybrid")
        for i, t in enumerate(texts)
    ]


class TestRerankerDisabled:
    def test_disabled_mode_is_not_available(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_RERANKER_MODE", "disabled")
        rr = CrossEncoderReranker()
        assert rr.is_available() is False
        assert rr.mode == "disabled"

    def test_disabled_rerank_returns_original_order_truncated(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """disabled 时应保持原顺序并截断到 top_k，不调用任何模型。"""
        monkeypatch.setenv("FHD_RERANKER_MODE", "disabled")
        chunks = _make_chunks(["a", "b", "c", "d"])
        rr = CrossEncoderReranker()
        out = rr.rerank("query", chunks, top_k=2)
        assert len(out) == 2
        assert [c.text for c in out] == ["a", "b"]
        # source 不应被改写（没有 rerank 标记）
        assert all("+rerank" not in c.source for c in out)

    def test_disabled_rerank_empty_chunks(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_RERANKER_MODE", "disabled")
        rr = CrossEncoderReranker()
        assert rr.rerank("q", [], top_k=5) == []

    def test_get_default_reranker_returns_none_when_disabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_RERANKER_MODE", "disabled")
        assert get_default_reranker() is None

    def test_default_mode_when_env_unset_is_disabled(self):
        rr = CrossEncoderReranker()
        assert rr.mode == "disabled"
        assert rr.is_available() is False


class TestRerankerLocal:
    def test_local_mode_calls_cross_encoder_predict(self, monkeypatch: pytest.MonkeyPatch):
        """mock CrossEncoder，验证 local 模式正确调用 predict。"""
        monkeypatch.setenv("FHD_RERANKER_MODE", "local")
        monkeypatch.setenv("FHD_RERANKER_LOCAL_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

        fake_model = MagicMock()
        # predict 返回与输入 pairs 同长度的分数数组
        fake_model.predict.return_value = [0.1, 0.9, 0.5]
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.CrossEncoder = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        rr = CrossEncoderReranker()
        assert rr.is_available() is True

        chunks = _make_chunks(["doc1", "doc2", "doc3"])
        out = rr.rerank("query", chunks, top_k=3)

        # 应按分数降序：doc2(0.9) > doc3(0.5) > doc1(0.1)
        assert [c.text for c in out] == ["doc2", "doc3", "doc1"]
        # 分数应被写入 score 字段
        assert out[0].score == pytest.approx(0.9)
        assert out[1].score == pytest.approx(0.5)
        assert out[2].score == pytest.approx(0.1)
        # source 应被标记为 +rerank
        assert all("+rerank" in c.source for c in out)

        # 验证 predict 调用参数：[[query, doc1], [query, doc2], [query, doc3]]
        fake_model.predict.assert_called_once()
        pairs = fake_model.predict.call_args.args[0]
        assert pairs == [
            ["query", "doc1"],
            ["query", "doc2"],
            ["query", "doc3"],
        ]
        # 验证模型名传递给 CrossEncoder 构造器
        fake_module.CrossEncoder.assert_called_once_with("cross-encoder/ms-marco-MiniLM-L-6-v2")

    def test_local_mode_top_k_truncation(self, monkeypatch: pytest.MonkeyPatch):
        """top_k 截断：返回长度不应超过 top_k。"""
        monkeypatch.setenv("FHD_RERANKER_MODE", "local")

        fake_model = MagicMock()
        fake_model.predict.return_value = [0.1, 0.9, 0.5, 0.7, 0.3]
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.CrossEncoder = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        rr = CrossEncoderReranker()
        chunks = _make_chunks(["a", "b", "c", "d", "e"])
        out = rr.rerank("q", chunks, top_k=2)
        assert len(out) == 2
        # top-2 应是 b(0.9) 和 d(0.7)
        assert [c.text for c in out] == ["b", "d"]

    def test_local_mode_load_failure_falls_back_to_original_order(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """sentence_transformers 不可用时应回退到原顺序截断，不抛异常。"""
        monkeypatch.setenv("FHD_RERANKER_MODE", "local")

        class _Raiser:
            def __getattr__(self, name: str) -> Any:
                raise ImportError(f"cannot import {name}")

        monkeypatch.setitem(sys.modules, "sentence_transformers", _Raiser())

        rr = CrossEncoderReranker()
        assert rr.is_available() is True  # 模式 local，但模型不可用
        chunks = _make_chunks(["a", "b", "c"])
        out = rr.rerank("q", chunks, top_k=2)
        # 降级：原顺序 + 截断
        assert [c.text for c in out] == ["a", "b"]

    def test_local_mode_lazy_load(self, monkeypatch: pytest.MonkeyPatch):
        """构造时不应加载模型，首次 rerank 才加载。"""
        monkeypatch.setenv("FHD_RERANKER_MODE", "local")

        fake_module = types.ModuleType("sentence_transformers")
        fake_model = MagicMock()
        fake_model.predict.return_value = [0.5]
        fake_module.CrossEncoder = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        rr = CrossEncoderReranker()
        assert fake_module.CrossEncoder.call_count == 0
        rr.rerank("q", _make_chunks(["a"]), top_k=1)
        assert fake_module.CrossEncoder.call_count == 1
        # 第二次 rerank 复用模型
        rr.rerank("q", _make_chunks(["b"]), top_k=1)
        assert fake_module.CrossEncoder.call_count == 1

    def test_predict_failure_falls_back_to_original_order(self, monkeypatch: pytest.MonkeyPatch):
        """模型 predict 抛异常时应回退到原顺序截断。"""
        monkeypatch.setenv("FHD_RERANKER_MODE", "local")

        fake_model = MagicMock()
        fake_model.predict.side_effect = RuntimeError("inference crashed")
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.CrossEncoder = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        rr = CrossEncoderReranker()
        chunks = _make_chunks(["a", "b", "c"])
        out = rr.rerank("q", chunks, top_k=2)
        assert [c.text for c in out] == ["a", "b"]


class TestRerankerPreservesChunkFields:
    """rerank 后 chunk 的 metadata / source_url / page / char_* 应被保留。"""

    def test_preserves_all_fields(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_RERANKER_MODE", "local")

        fake_model = MagicMock()
        fake_model.predict.return_value = [0.5, 0.9]
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.CrossEncoder = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        rr = CrossEncoderReranker()
        chunks = [
            RetrievedChunk(
                text="alpha",
                score=0.1,
                source="vector",
                chunk_index=10,
                char_start=100,
                char_end=200,
                metadata={"doc": "x.pdf"},
                source_url="https://example.com/x.pdf",
                page=3,
            ),
            RetrievedChunk(
                text="beta",
                score=0.2,
                source="bm25",
                chunk_index=20,
                char_start=300,
                char_end=400,
                metadata={"doc": "y.pdf"},
                source_url="https://example.com/y.pdf",
                page=5,
            ),
        ]
        out = rr.rerank("q", chunks, top_k=2)
        # 分数高的 beta 在前
        assert out[0].text == "beta"
        assert out[0].chunk_index == 20
        assert out[0].char_start == 300
        assert out[0].char_end == 400
        assert out[0].metadata == {"doc": "y.pdf"}
        assert out[0].source_url == "https://example.com/y.pdf"
        assert out[0].page == 5
        # source 应标记 +rerank
        assert out[0].source == "bm25+rerank"
