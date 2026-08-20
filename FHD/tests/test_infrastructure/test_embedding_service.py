# mypy: disable-error-code="attr-defined"
"""EmbeddingService 单元测试。

覆盖：
- disabled 模式向后兼容（is_available False / get_default_embedding_service 返回 None）
- local 模式（mock sentence_transformers.SentenceTransformer）
- remote 模式（mock requests.post，验证 OpenAI 兼容 payload）
- 维度查询 / embed_one / embed 批量
- 降级到 HashEmbedder（_get_default_embedder）
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application.excel_vector_app_service import HashEmbedder, _get_default_embedder
from app.infrastructure.llm.embedding_service import (
    EmbeddingService,
    get_default_embedding_service,
)


@pytest.fixture(autouse=True)
def _reset_embedding_singleton():
    """每个用例前后清理单例，避免 env 变化被缓存。"""
    EmbeddingService.reset_singleton_for_tests()
    yield
    EmbeddingService.reset_singleton_for_tests()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch):
    """清理 embedding 相关环境变量。"""
    for key in (
        "FHD_EMBEDDING_MODE",
        "FHD_EMBEDDING_LOCAL_MODEL",
        "FHD_EMBEDDING_REMOTE_URL",
        "FHD_EMBEDDING_REMOTE_API_KEY",
        "FHD_EMBEDDING_REMOTE_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


class TestEmbeddingServiceDisabled:
    def test_disabled_mode_is_not_available(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "disabled")
        svc = EmbeddingService()
        assert svc.is_available() is False
        assert svc.mode == "disabled"

    def test_disabled_embed_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "disabled")
        svc = EmbeddingService()
        assert svc.embed(["hello", "world"]) == []
        assert svc.embed_one("hello") == []

    def test_disabled_dim_returns_zero(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "disabled")
        svc = EmbeddingService()
        assert svc.dim() == 0

    def test_get_default_embedding_service_returns_none_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "disabled")
        # 通过 get_singleton 路径触发单例创建
        assert get_default_embedding_service() is None

    def test_default_mode_when_env_unset_is_hash_for_non_desktop(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """env 未设置时非 desktop 默认 hash（web omniscient 关键词+向量混合检索）。

        代码逻辑见 embedding_service._resolve_mode：未配置 FHD_EMBEDDING_MODE
        且非 desktop mode 时回退到 hash（用于 web 全知视图），desktop 才默认 disabled。
        """
        # 在 CI 中（非 desktop mode），默认应为 hash
        monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
        monkeypatch.delenv("XCAGI_RAG_ENABLED", raising=False)
        svc = EmbeddingService()
        assert svc.mode == "hash"
        assert svc.is_available() is True

    def test_invalid_mode_falls_back_to_hash_for_non_desktop(self, monkeypatch: pytest.MonkeyPatch):
        """非法 mode 在非 desktop 环境下回退到 hash（与 _resolve_mode 一致）。

        _resolve_mode 仅在 desktop mode 或 RAG 显式关闭时才回退到 disabled；
        其他未识别值在非 desktop 下落到末尾的 return "hash"。
        """
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "something-weird")
        monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
        monkeypatch.delenv("XCAGI_RAG_ENABLED", raising=False)
        svc = EmbeddingService()
        assert svc.mode == "hash"


class TestEmbeddingServiceLocal:
    def test_local_mode_calls_sentence_transformer(self, monkeypatch: pytest.MonkeyPatch):
        """mock SentenceTransformer，验证 local 模式正确调用 encode。"""
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")
        monkeypatch.setenv("FHD_EMBEDDING_LOCAL_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

        fake_model = MagicMock()
        # 模拟 encode 返回 numpy 风格的二维数组
        fake_model.encode.return_value = [
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
        ]
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService()
        assert svc.is_available() is True

        results = svc.embed(["hello", "world"])
        assert len(results) == 2
        assert results[0] == [0.1, 0.2, 0.3]
        assert results[1] == [0.4, 0.5, 0.6]
        # 验证 encode 被以 list[str] 调用
        fake_model.encode.assert_called_once_with(["hello", "world"])
        # 验证模型名传递给 SentenceTransformer 构造器
        fake_module.SentenceTransformer.assert_called_once_with(
            "sentence-transformers/all-MiniLM-L6-v2"
        )

    def test_local_mode_embed_one(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")

        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.7, 0.8, 0.9]]
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService()
        vec = svc.embed_one("hello")
        assert vec == [0.7, 0.8, 0.9]
        # 验证 embed_one 走的是 embed([text]) 路径
        fake_model.encode.assert_called_once_with(["hello"])

    def test_local_mode_dim_probed_from_first_embedding(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")

        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.1, 0.2, 0.3, 0.4]]
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService()
        # dim 会触发一次探测性 embed_one
        assert svc.dim() == 4
        # 再次调用 dim 走缓存，不应再次 encode
        assert svc.dim() == 4
        assert fake_model.encode.call_count == 1

    def test_local_mode_load_failure_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        """sentence_transformers 不可用时应静默降级为空列表，不抛异常。"""
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")

        # 模拟 import 失败
        fake_module = types.ModuleType("sentence_transformers")
        # 让 from sentence_transformers import SentenceTransformer 抛 ImportError

        class _Raiser:
            def __getattr__(self, name: str) -> Any:
                raise ImportError(f"cannot import {name}")

        monkeypatch.setitem(sys.modules, "sentence_transformers", _Raiser())

        svc = EmbeddingService()
        assert svc.is_available() is True  # 模式是 local，但模型不可用
        assert svc.embed(["hello"]) == []
        assert svc.embed_one("hello") == []

    def test_local_mode_lazy_load_only_on_first_embed(self, monkeypatch: pytest.MonkeyPatch):
        """构造时不应加载模型，首次 embed 才加载。"""
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")

        fake_module = types.ModuleType("sentence_transformers")
        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.0, 0.0]]
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService()
        # 构造后未触发加载
        assert fake_module.SentenceTransformer.call_count == 0
        # 触发 embed 才加载
        svc.embed(["x"])
        assert fake_module.SentenceTransformer.call_count == 1
        # 第二次 embed 复用模型，不重复加载
        svc.embed(["y"])
        assert fake_module.SentenceTransformer.call_count == 1


class TestEmbeddingServiceRemote:
    def test_remote_mode_calls_openai_compatible_api(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_API_KEY", "sk-test")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_MODEL", "text-embedding-3-small")

        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2], "index": 0},
                {"embedding": [0.3, 0.4], "index": 1},
            ]
        }
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp) as mock_post:
            svc = EmbeddingService()
            results = svc.embed(["hello", "world"])

        assert results == [[0.1, 0.2], [0.3, 0.4]]
        mock_post.assert_called_once()
        # 验证 URL / headers / payload
        call_args = mock_post.call_args
        assert call_args.args[0] == "https://api.example.com/v1/embeddings"
        headers = call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-test"
        assert headers["Content-Type"] == "application/json"
        payload = call_args.kwargs["json"]
        assert payload["input"] == ["hello", "world"]
        assert payload["model"] == "text-embedding-3-small"

    def test_remote_mode_handles_unsorted_data(self, monkeypatch: pytest.MonkeyPatch):
        """OpenAI 兼容 API 可能乱序返回，按 index 重新排序。"""
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")

        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "data": [
                {"embedding": [0.3, 0.4], "index": 1},
                {"embedding": [0.1, 0.2], "index": 0},
            ]
        }
        fake_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_resp):
            svc = EmbeddingService()
            results = svc.embed(["a", "b"])

        # 按 index 排序后：[0.1,0.2] 在前
        assert results == [[0.1, 0.2], [0.3, 0.4]]

    def test_remote_mode_missing_url_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        # 不设置 FHD_EMBEDDING_REMOTE_URL
        svc = EmbeddingService()
        assert svc.embed(["hello"]) == []

    def test_remote_mode_request_failure_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "remote")
        monkeypatch.setenv("FHD_EMBEDDING_REMOTE_URL", "https://api.example.com/v1/embeddings")

        with patch("requests.post", side_effect=ConnectionError("network down")):
            svc = EmbeddingService()
            assert svc.embed(["hello"]) == []


class TestEmbedderPortAdapter:
    """EmbeddingService 同时实现 EmbedderPort 协议（embed_texts / embed_query）。"""

    def test_embed_texts_delegates_to_embed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")
        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService()
        assert svc.embed_texts(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]

    def test_embed_query_delegates_to_embed_one(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")
        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.5, 0.6]]
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        svc = EmbeddingService()
        assert svc.embed_query("hello") == [0.5, 0.6]


class TestHashEmbedderFallback:
    """disabled 时 _get_default_embedder 应回退到 HashEmbedder。"""

    def test_disabled_returns_hash_embedder(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "disabled")
        emb = _get_default_embedder()
        assert isinstance(emb, HashEmbedder)

    def test_local_available_returns_embedding_service(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")
        # 即便模型加载会失败，_get_default_embedder 仍应返回 EmbeddingService
        # （模式是 available，真实加载在首次 embed 时降级）
        fake_module = types.ModuleType("sentence_transformers")

        class _Raiser:
            def __getattr__(self, name: str) -> Any:
                raise ImportError("no st")

        monkeypatch.setitem(sys.modules, "sentence_transformers", _Raiser())

        emb = _get_default_embedder()
        assert isinstance(emb, EmbeddingService)
        assert emb.is_available() is True

    def test_import_error_falls_back_to_hash(self, monkeypatch: pytest.MonkeyPatch):
        """app.infrastructure.llm 包加载异常时也回退到 HashEmbedder。"""
        monkeypatch.setenv("FHD_EMBEDDING_MODE", "local")
        # 注入一个 import 失败的 __init__ 路径
        with patch(
            "app.infrastructure.llm.get_default_embedding_service",
            side_effect=ImportError("simulated"),
        ):
            emb = _get_default_embedder()
        assert isinstance(emb, HashEmbedder)
